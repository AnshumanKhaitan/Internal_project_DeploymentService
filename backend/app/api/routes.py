"""
Anti Gravity Deployments - API Routes

REST API endpoints for the deployment platform.
Phase 2: Real ZIP upload, extraction, and project analysis.
"""

import asyncio
import json
import logging
import docker
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator, Any

import httpx

from fastapi.responses import Response
from app.services.deployment_store import DEPLOYMENT_PORTS
from app.models.schemas import RuntimeType
from app.services.execution_engine import (
ExecutionEngine,
    DEPLOYMENT_LOGS,
)
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
from app.services.container_lifecycle import ContainerLifecycleService
from app.services.scanner import project_scanner
from app.utils.helpers import (
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
async def  upload_project(frontend_file: UploadFile = File(...),
backend_file: UploadFile | None = File(None),):
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
    if not frontend_file.filename or not frontend_file.filename.endswith(".zip"):
        raise HTTPException(
            status_code=400,
            detail="Only .zip files are accepted",
        )

    # ── Read file content and check size ────────────────────────────────
    try:
        content = await frontend_file.read()
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
    project_name = frontend_file.filename.rsplit(".", 1)[0]
    deployment_id, workspace = create_deployment_workspace(project_name)

    # Create deployment entry
    deployment = deployment_service.create_deployment(
        project_name=project_name,
        deployment_id=deployment_id,
        workspace=workspace,
    )
    deployment.status = DeploymentStatus.UPLOADING

    # ── Save ZIP to workspace ───────────────────────────────────────────

    frontend_zip_path: Path | Any = (
            workspace
            / frontend_file.filename
    )
    try:
        with open(frontend_zip_path, "wb") as f:
            f.write(content)
    except OSError as e:
        deployment_service.set_error(deployment_id, f"Failed to save upload: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save uploaded file: {str(e)}",
        )

    # ── Validate ZIP integrity ──────────────────────────────────────────
    is_valid, error_msg = validate_zip_file(frontend_zip_path)
    if not is_valid:
        deployment_service.set_error(deployment_id, f"Invalid ZIP: {error_msg}")
        raise HTTPException(
            status_code=400,
            detail=f"Invalid ZIP file: {error_msg}",
        )

    # ── Safe extraction ─────────────────────────────────────────────────
    deployment.status = DeploymentStatus.RUNNING
    frontend_extract_dir = workspace / "extracted"
    frontend_extract_dir.mkdir(parents=True, exist_ok=True)

    success, extract_error, frontend_project_root = safe_extract_zip(frontend_zip_path, frontend_extract_dir)
    if not success:
        deployment_service.set_error(deployment_id, f"Extraction failed: {extract_error}")
        raise HTTPException(
            status_code=400,
            detail=f"ZIP extraction failed: {extract_error}",
        )

    logger.info(
        "Project extracted: %s → %s (%d files)",
        frontend_file.filename,
        frontend_project_root,
        len(list(frontend_project_root.rglob("*"))),
    )

    backend_project_root = None

    if backend_file:

        backend_content = (
            await backend_file.read()
        )

        backend_zip_path = (
                workspace
                / backend_file.filename
        )

        with open(
                backend_zip_path,
                "wb"
        ) as f:
            f.write(
                backend_content
            )

        backend_extract_dir = (
                workspace
                / "backend_extracted"
        )

        backend_extract_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        (
            backend_success,
            backend_error,
            backend_project_root,
        ) = safe_extract_zip(
            backend_zip_path,
            backend_extract_dir,
        )

        if not backend_success:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Backend extraction failed: "
                    f"{backend_error}"
                ),
            )

        print(
            "\nBACKEND PROJECT ROOT:\n",
            backend_project_root,
        )

    # ── Project scanning & analysis ─────────────────────────────────────
    try:
        analysis = project_scanner.scan(frontend_project_root)
        package_json = (
                frontend_project_root / "package.json"
        )

        requirements_txt = (
                frontend_project_root / "requirements.txt"
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
        scan_result = ManifestScanner.scan(
            str(frontend_project_root)
        )

        manifests = scan_result["manifests"]

        runtime = scan_result["runtime"]

        framework = scan_result["framework"]

        entry_points = scan_result["entry_points"]

        print(
            "\nMANIFESTS FOUND:\n",
            manifests,
        )

        try:

            deployment_plan = (
                DeploymentPlanner.plan(
                    manifests=manifests,
                    runtime=runtime,
                    framework=framework,
                    entry_points=entry_points,
                )
            )
            if isinstance(
                    deployment_plan,
                    list
            ):
                deployment_plan = (
                    deployment_plan[0]
                )

            print(
                "\nDEPLOYMENT PLAN:\n",
                deployment_plan,
            )

            deployed_services = []
            preview_url = None

            for index, service in enumerate(
                    deployment_plan["services"]
            ):
                working_directory = (
                    service.get(
                        "working_directory",
                        "."
                    )
                    .strip()
                )

                runtime = (
                    service.get(
                        "runtime",
                        ""
                    )
                    .lower()
                )

                if runtime == "nodejs":
                    runtime = "node"

                service["runtime"] = runtime
                service["working_directory"] = working_directory

                service_root = (
                        Path(frontend_project_root)
                        / working_directory
                ).resolve()

                print(
                    "\nSERVICE ROOT:\n",
                    service_root,
                )

                if not service_root.exists():
                    print(
                        "\nINVALID SERVICE ROOT:\n",
                        service_root,
                    )

                    continue

                print(
                    "\nDEPLOYING SERVICE:\n",
                    service,
                )

                service_root = (
                        Path(frontend_project_root)
                        / service["working_directory"]
                )

                dockerfile_content = (
                    ExecutionEngine.generate_dockerfile(
                        service
                    )
                )

                print(
                    "\nGENERATED DOCKERFILE:\n",
                    dockerfile_content,
                )

                ExecutionEngine.save_dockerfile(
                    str(service_root),
                    dockerfile_content,
                )

                image_tag = (
                    ExecutionEngine.build_image(
                        str(service_root),
                        f"{deployment_id}-{index}",
                    )
                )

                print(
                    "\nIMAGE BUILT:\n",
                    image_tag,
                )

                container_data = (
                    ExecutionEngine.run_container(
                        image_tag,
                        f"{deployment_id}-{index}",
                        service,
                    )
                )

                container = (
                    container_data["container"]
                )

                host_port = (
                    container_data["host_port"]
                )

                print(
                    "\nCONTAINER STARTED:\n",
                    container.id,
                )

                service_url = (
                    f"http://localhost:{host_port}"
                )

                DEPLOYMENT_PORTS[
                    deployment_id
                ] = host_port

                if preview_url is None:
                    preview_url = service_url

                    print(
                        "\nPREVIEW URL:\n",
                        preview_url,
                    )
                    print(
                        "\nPREVIEW URL:\n",
                        preview_url,
                    )

                deployed_services.append({
                    "runtime":
                        service["runtime"],

                    "working_directory":
                        service["working_directory"],

                    "url":
                        service_url,
                })

                backend_preview_url = None

                if backend_project_root:

                    print(
                        "\nSTARTING BACKEND DEPLOYMENT\n"
                    )

                    backend_scan_result = (
                        ManifestScanner.scan(
                            str(backend_project_root)
                        )
                    )

                    backend_manifests = (
                        backend_scan_result["manifests"]
                    )

                    backend_runtime = (
                        backend_scan_result["runtime"]
                    )

                    backend_framework = (
                        backend_scan_result["framework"]
                    )

                    backend_entry_points = (
                        backend_scan_result["entry_points"]
                    )

                    print(
                        "\nBACKEND MANIFESTS FOUND:\n",
                        backend_manifests,
                    )

                    backend_plan = (
                        DeploymentPlanner.plan(
                            manifests=backend_manifests,
                            runtime=backend_runtime,
                            framework=backend_framework,
                            entry_points=backend_entry_points,
                        )
                    )

                    print(
                        "\nBACKEND DEPLOYMENT PLAN:\n",
                        backend_plan,
                    )

                    for backend_index, backend_service in enumerate(
                            backend_plan["services"]
                    ):

                        backend_workdir = (
                            backend_service.get(
                                "working_directory",
                                "."
                            )
                            .strip()
                        )

                        backend_runtime_name = (
                            backend_service.get(
                                "runtime",
                                ""
                            )
                            .lower()
                        )

                        if backend_runtime_name == "nodejs":
                            backend_runtime_name = "node"

                        backend_service["runtime"] = (
                            backend_runtime_name
                        )

                        backend_service[
                            "working_directory"
                        ] = backend_workdir

                        backend_service_root = (
                                Path(backend_project_root)
                                / backend_workdir
                        ).resolve()

                        print(
                            "\nBACKEND SERVICE ROOT:\n",
                            backend_service_root,
                        )

                        backend_dockerfile = (
                            ExecutionEngine.generate_dockerfile(
                                backend_service
                            )
                        )

                        ExecutionEngine.save_dockerfile(
                            str(backend_service_root),
                            backend_dockerfile,
                        )

                        backend_image_tag = (
                            ExecutionEngine.build_image(
                                str(backend_service_root),
                                f"{deployment_id}-backend-{backend_index}",
                            )
                        )

                        print(
                            "\nBACKEND IMAGE BUILT:\n",
                            backend_image_tag,
                        )

                        backend_container_data = (
                            ExecutionEngine.run_container(
                                backend_image_tag,
                                f"{deployment_id}-backend-{backend_index}",
                                backend_service,
                            )
                        )

                        backend_container = (
                            backend_container_data[
                                "container"
                            ]
                        )

                        backend_host_port = (
                            backend_container_data[
                                "host_port"
                            ]
                        )

                        backend_url = (
                            f"http://localhost:{backend_host_port}"
                        )

                        print(
                            "\nBACKEND CONTAINER STARTED:\n",
                            backend_container.id,
                        )

                        print(
                            "\nBACKEND URL:\n",
                            backend_url,
                        )

                        deployed_services.append({
                            "runtime":
                                backend_service["runtime"],

                            "working_directory":
                                backend_service[
                                    "working_directory"
                                ],

                            "url":
                                backend_url,

                            "service_type":
                                "backend",
                        })

                        backend_preview_url = (
                            backend_url
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
    deployment.status = DeploymentStatus.RUNNING

    # ── Clean up the ZIP file (keep extracted only) ─────────────────────
    try:
        frontend_zip_path.unlink()
    except OSError:
        pass

    logger.info(
        "Analysis complete for %s: runtime=%s, framework=%s, deps=%d",
        deployment_id,
        analysis.runtime.value,
        analysis.framework.value,
        analysis.dependencies_count,
    )

    return {
        "deployment_id":
            deployment_id,

        "status":
            DeploymentStatus.RUNNING,

        "message":
            f"Project '{project_name}' deployed successfully.",

        "analysis":
            analysis.model_dump(),

        "preview_url":
            preview_url,

        "services":
            deployed_services,
    }



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

@router.get(
    "/deployments/{deployment_id}/status"
)
async def get_status(
    deployment_id: str,
):

    try:

        client = docker.from_env()

        container = (
            client.containers.get(
                f"container-{deployment_id}"
            )
        )

        container.reload()

        return {
            "status":
                container.status
        }

    except Exception as e:

        return {
            "status": "unknown",
            "error": str(e),
        }

@router.get("/preview/{deployment_id}")

async def preview_proxy(
    deployment_id: str,
):

    port = DEPLOYMENT_PORTS.get(
        deployment_id
    )

    if not port:

        return Response(
            content="Deployment not found",
            status_code=404,
        )

    target_url = (
        f"http://localhost:{port}"
    )

    async with httpx.AsyncClient() as client:

        upstream = await client.get(
            target_url
        )

    excluded_headers = {
        "content-encoding",
        "transfer-encoding",
        "connection",
    }

    headers = {
        k: v
        for k, v in upstream.headers.items()
        if k.lower() not in excluded_headers
    }

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=headers,
    )

# Deployement LOGS -------------------------------------------------------
@router.get(
    "/deployments/{deployment_id}/logs"
)
async def get_logs(
    deployment_id: str,
):

    logs = DEPLOYMENT_LOGS.get(
        deployment_id,
        [],
    )

    return {
        "logs": logs
    }
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
