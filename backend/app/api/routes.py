"""
Anti Gravity Deployments - API Routes

REST API endpoints for the deployment platform.
Phase 2: Real ZIP upload, extraction, and project analysis.
"""

import asyncio
import json
import logging
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator
from app.models.schemas import RuntimeType
from app.services.manifest_scanner import (
    ManifestScanner,
)

from app.services.deployment_planner import (
    DeploymentPlanner,
)

from fastapi import APIRouter, File, UploadFile, HTTPException
from fastapi.responses import StreamingResponse

from app.models.schemas import (
    HealthResponse,
    UploadResponse,
    DeploymentState,
    DeploymentStatus,
    DeploymentEvent,
    LogEntry,
)
from app.services.deployment import deployment_service
from app.services.traefik_service import TraefikService
from app.services.container_lifecycle import ContainerLifecycleService
from app.services.health_checker import DeploymentHealthChecker
from app.services.dockerfile_generator import DockerfileGenerator
from app.services.docker_builder import DockerImageBuilder
from app.services.container_logs import ContainerLogsService
from app.services.container_manager import ContainerManager
from app.services.scanner import project_scanner
from app.utils.helpers import (
    get_upload_dir,
    create_deployment_workspace,
    validate_zip_file,
    safe_extract_zip,
    format_file_size,
)


logger = logging.getLogger(__name__)

router = APIRouter()


# ─── Health ────────────────────────────────────────────────────────────────────

@router.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """Health check endpoint for monitoring and Docker health checks."""
    return HealthResponse(
        status="healthy",
        version="0.1.0",
        service="anti-gravity-deployments",
        timestamp=datetime.utcnow(),
    )


# ─── Upload ───────────────────────────────────────────────────────────────────

@router.post("/upload", response_model=UploadResponse, tags=["Deployment"])
async def  upload_project(file: UploadFile = File(...)):
    """
    Upload a project ZIP file for deployment.

    Phase 2: Real upload → extraction → scanning → analysis.

    1. Validates the uploaded file (ZIP only, size limit)
    2. Saves to a unique deployment workspace
    3. Safely extracts the ZIP (path traversal protection)
    4. Scans the project to detect runtime/framework/dependencies
    5. Returns structured analysis response
    """
    # ── Validate file type ──────────────────────────────────────────────
    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(
            status_code=400,
            detail="Only .zip files are accepted",
        )

    # ── Read file content and check size ────────────────────────────────
    try:
        content = await file.read()
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to read uploaded file: {str(e)}",
        )

    max_size = 500 * 1024 * 1024  # 500 MB
    if len(content) > max_size:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({format_file_size(len(content))}). Maximum: 500MB",
        )

    if len(content) == 0:
        raise HTTPException(
            status_code=400,
            detail="Uploaded file is empty",
        )

    # ── Create deployment workspace ─────────────────────────────────────
    project_name = file.filename.rsplit(".", 1)[0]
    deployment_id, workspace = create_deployment_workspace(project_name)

    # Create deployment entry
    deployment = deployment_service.create_deployment(
        project_name=project_name,
        deployment_id=deployment_id,
        workspace=workspace,
    )
    deployment.status = DeploymentStatus.UPLOADING

    # ── Save ZIP to workspace ───────────────────────────────────────────
    zip_path = workspace / file.filename
    try:
        with open(zip_path, "wb") as f:
            f.write(content)
    except OSError as e:
        deployment_service.set_error(deployment_id, f"Failed to save upload: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save uploaded file: {str(e)}",
        )

    # ── Validate ZIP integrity ──────────────────────────────────────────
    is_valid, error_msg = validate_zip_file(zip_path)
    if not is_valid:
        deployment_service.set_error(deployment_id, f"Invalid ZIP: {error_msg}")
        raise HTTPException(
            status_code=400,
            detail=f"Invalid ZIP file: {error_msg}",
        )

    # ── Safe extraction ─────────────────────────────────────────────────
    deployment.status = DeploymentStatus.ANALYZING
    extract_dir = workspace / "extracted"
    extract_dir.mkdir(parents=True, exist_ok=True)

    success, extract_error, project_root = safe_extract_zip(zip_path, extract_dir)
    if not success:
        deployment_service.set_error(deployment_id, f"Extraction failed: {extract_error}")
        raise HTTPException(
            status_code=400,
            detail=f"ZIP extraction failed: {extract_error}",
        )

    logger.info(
        "Project extracted: %s → %s (%d files)",
        file.filename,
        project_root,
        len(list(project_root.rglob("*"))),
    )

    # ── Project scanning & analysis ─────────────────────────────────────
    try:
        analysis = project_scanner.scan(project_root)
        package_json = (
                project_root / "package.json"
        )

        requirements_txt = (
                project_root / "requirements.txt"
        )

        if (
                analysis.runtime.value == "unknown"
        ):

            if package_json.exists():

                analysis.runtime = RuntimeType.NODEJS

                print(
                    "Runtime inferred from package.json"
                )

            elif requirements_txt.exists():

                analysis.runtime = RuntimeType.PYTHON

                print(
                    "Runtime inferred from requirements.txt"
                )

        deployment.analysis = analysis
        manifests = ManifestScanner.scan(
            str(project_root)
        )

        print(
            "\nMANIFESTS FOUND:\n",
            manifests,
        )

        try:

            deployment_plan = (
                DeploymentPlanner.plan(
                    manifests
                )
            )

            print(
                "\nDEPLOYMENT PLAN:\n",
                deployment_plan,
            )
            from app.services.execution_engine import (
                ExecutionEngine,
            )

            first_service = (
                deployment_plan["services"][0]
            )

            dockerfile_content = (
                ExecutionEngine.generate_dockerfile(
                    first_service
                )
            )

            print(
                "\nGENERATED DOCKERFILE:\n",
                dockerfile_content,
            )

            ExecutionEngine.save_dockerfile(
                str(project_root),
                dockerfile_content,
            )

            image_tag = (
                ExecutionEngine.build_image(
                    str(project_root),
                    deployment_id,
                )
            )

            print(
                "\nIMAGE BUILT:\n",
                image_tag,
            )

            container = (
                ExecutionEngine.run_container(
                    image_tag,
                    deployment_id,
                )
            )

            print(
                "\nCONTAINER STARTED:\n",
                container.id,
            )

        except Exception as e:

            print(
                "Deployment planning failed:",
                e,
            )

            deployment_plan = {}
    except Exception as e:
        logger.exception("Project scan failed for %s", deployment_id)
        deployment_service.set_error(deployment_id, f"Scan failed: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Project analysis failed: {str(e)}",
        )

    # ── Update deployment with analysis ─────────────────────────────────
    deployment_service.update_analysis(deployment_id, analysis)
    deployment.status = DeploymentStatus.ANALYZING

    # ── Clean up the ZIP file (keep extracted only) ─────────────────────
    try:
        zip_path.unlink()
    except OSError:
        pass

    logger.info(
        "Analysis complete for %s: runtime=%s, framework=%s, deps=%d",
        deployment_id,
        analysis.runtime.value,
        analysis.framework.value,
        analysis.dependencies_count,
    )

    return UploadResponse(
        deployment_id=deployment_id,
        status=DeploymentStatus.ANALYZING,
        message=f"Project '{project_name}' uploaded and analyzed successfully.",
        analysis=analysis,
    )


# ─── Deployments ──────────────────────────────────────────────────────────────

@router.get("/deployments/{deployment_id}", response_model=DeploymentState, tags=["Deployment"])
async def get_deployment(deployment_id: str):
    deployment = deployment_service.get_deployment(deployment_id)

    if not deployment:
        raise HTTPException(
            status_code=404,
            detail="Deployment not found"
        )

    return deployment
@router.get("/deployments", tags=["Deployment"])
async def list_deployments():
    return deployment_service.list_deployments()
@router.delete("/deployments/{deployment_id}", tags=["Deployment"])
async def delete_deployment(deployment_id: str):
    """
    Fully delete deployment and cleanup resources.
    """

    with Session(engine) as session:
        deployment_record = session.get(
            DeploymentRecord,
            deployment_id
        )

    if not deployment_record:
        raise HTTPException(
            status_code=404,
            detail="Deployment not found"
        )

    image_name = f"anti-gravity-{deployment_id}".lower()

    workspace_path = f"./tmp/ag-uploads/deployments/{deployment_record.project_name}/{deployment_id}"

    lifecycle_service = ContainerLifecycleService()

    result = lifecycle_service.delete_deployment_resources(
        deployment_id=deployment_id,
        image_name=image_name,
        workspace_path=workspace_path,
    )

    if not result["success"]:
        raise HTTPException(
            status_code=500,
            detail=result["error"]
        )

    deployment_service.delete_deployment(deployment_id)

    return result
# ─── Deployment Preparation ────────────────────────────────────────────────

# ─── Deployment Preparation ────────────────────────────────────────────────

@router.post("/deployments/{deployment_id}/prepare", tags=["Deployment"])
async def prepare_deployment(deployment_id: str):
    """
    Prepare deployment by generating Dockerfile dynamically.

    Flow:
    - detect runtime
    - generate Dockerfile
    - build Docker image
    - create/start container
    - verify health
    """

    deployment = deployment_service.get_deployment(
        deployment_id
    )

    if not deployment:
        raise HTTPException(
            status_code=404,
            detail="Deployment not found"
        )

    runtime = deployment.analysis.runtime.value
    project_path = Path(
        deployment.analysis.project_root
    )

    print("PROJECT PATH:", project_path)

    if not project_path.exists():
        raise HTTPException(
            status_code=400,
            detail="Extracted project not found"
        )

    try:
        # ── Generate Dockerfile ─────────────────────────────

        dockerfile_content = DockerfileGenerator.generate(runtime)

        dockerfile_path = DockerfileGenerator.save(
            dockerfile_content,
            str(project_path)
        )

        image_name = f"anti-gravity-{deployment_id}".lower()

        container_name = f"container-{deployment_id}".lower()

        logger.info(
            "Dockerfile generated for %s (%s)",
            deployment_id,
            runtime,
        )

        # ── Build Docker image ─────────────────────────────

        docker_builder = DockerImageBuilder()

        build_result = docker_builder.build_image(
            deployment_id=deployment_id,
            project_path=str(project_path),
            image_name=image_name,
        )

        if not build_result["success"]:
            raise HTTPException(
                status_code=500,
                detail=f"Docker build failed: {build_result['error']}"
            )

        # ── Start container ─────────────────────────────

        container_manager = ContainerManager()

        container_result = container_manager.create_and_start_container(
            image_name=image_name,
            container_name=container_name,
            internal_port=3000,
        )

        if not container_result["success"]:
            raise HTTPException(
                status_code=500,
                detail=f"Container startup failed: {container_result['error']}"
            )

        # ── Deployment health check ─────────────────────

        health_result = DeploymentHealthChecker.wait_until_healthy(
            port=container_result["assigned_port"]
        )

        deployment_status = (
            "healthy"
            if health_result["healthy"]
            else "unhealthy"
        )

        # ── Register Traefik Route ─────────────────────

        traefik_result = TraefikService.register_deployment_route(
            deployment_id=deployment_id,
            assigned_port=container_result["assigned_port"],
        )

        return {
            "success": True,
            "deployment_id": deployment_id,
            "runtime": runtime,
            "dockerfile": dockerfile_content,
            "dockerfile_path": dockerfile_path,
            "image_name": image_name,
            "container_name": container_name,
            "image_id": build_result["image_id"],
            "image_tags": build_result["image_tags"],
            "build_logs": build_result["logs"],
            "container_id": container_result["container_id"],
            "container_status": container_result["status"],
            "assigned_port": container_result["assigned_port"],
            "deployment_status": deployment_status,
            "health_check": health_result,
            "application_url": health_result["url"],
            "traefik_route": traefik_result["route"],
        }

    except Exception as e:
        logger.exception("Deployment preparation failed")

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


# ─── Deployment Logs ───────────────────────────────────────────────────────

@router.get(
    "/deployments/{deployment_id}/logs",
    tags=["Deployment"]
)
async def get_deployment_logs(deployment_id: str):
    """
    Fetch logs for deployment container.
    """

    container_name = f"container-{deployment_id}".lower()

    logs_service = ContainerLogsService()

    result = logs_service.get_logs(
        container_name=container_name
    )

    if not result["success"]:
        raise HTTPException(
            status_code=500,
            detail=result["error"]
        )

    return result


# ─── Deployment Lifecycle ───────────────────────────────────────────────

@router.post(
    "/deployments/{deployment_id}/stop",
    tags=["Deployment"]
)
async def stop_deployment(deployment_id: str):
    """
    Stop running deployment container.
    """

    container_name = f"container-{deployment_id}".lower()

    lifecycle_service = ContainerLifecycleService()

    result = lifecycle_service.stop_container(
        container_name=container_name
    )

    if not result["success"]:
        raise HTTPException(
            status_code=500,
            detail=result["error"]
        )

    return result

# ─── SSE (Server-Sent Events) ─────────────────────────────────────────────────

async def _mock_event_stream(deployment_id: str) -> AsyncGenerator[str, None]:
    """
    Generate mock Server-Sent Events for deployment progress.

    Placeholder implementation — will be connected to real deployment
    pipeline in later phases.
    """
    mock_events = [
        {"event_type": "status", "data": {"status": "analyzing", "message": "Analyzing project..."}},
        {"event_type": "log", "data": {"level": "info", "message": "Detected runtime: Node.js 20"}},
        {"event_type": "log", "data": {"level": "info", "message": "Detected framework: Next.js 15"}},
        {"event_type": "status", "data": {"status": "building", "message": "Building Docker image..."}},
        {"event_type": "log", "data": {"level": "info", "message": "Step 1/5: FROM node:20-alpine"}},
        {"event_type": "log", "data": {"level": "info", "message": "Step 2/5: COPY package*.json ./"}},
        {"event_type": "log", "data": {"level": "info", "message": "Step 3/5: RUN npm ci"}},
        {"event_type": "log", "data": {"level": "info", "message": "Step 4/5: COPY . ."}},
        {"event_type": "log", "data": {"level": "info", "message": "Step 5/5: RUN npm run build"}},
        {"event_type": "log", "data": {"level": "success", "message": "Image built successfully"}},
        {"event_type": "status", "data": {"status": "deploying", "message": "Starting container..."}},
        {"event_type": "log", "data": {"level": "info", "message": "Container started"}},
        {"event_type": "log", "data": {"level": "info", "message": "Health check passed"}},
        {"event_type": "status", "data": {"status": "running", "message": "Deployment successful!"}},
    ]

    for event in mock_events:
        event_data = DeploymentEvent(
            event_type=event["event_type"],
            deployment_id=deployment_id,
            data=event["data"],
        )
        yield f"data: {json.dumps(event_data.model_dump())}\n\n"
        await asyncio.sleep(0.8)


@router.get("/deployments/{deployment_id}/events", tags=["Deployment"])
async def deployment_events(deployment_id: str):
    """
    Stream deployment events via Server-Sent Events (SSE).

    Placeholder — returns mock events for UI development.
    """
    deployment = deployment_service.get_deployment(deployment_id)

    return StreamingResponse(
        _mock_event_stream(deployment_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
