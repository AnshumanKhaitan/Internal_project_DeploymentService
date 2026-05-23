"""
Anti Gravity Deployments - API Routes

REST API endpoints for the deployment platform.
Stabilized for recursive self-hosting and production-grade reliability.
"""

import asyncio
import json
import logging
import docker
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator, Any

import httpx
from fastapi import APIRouter, File, UploadFile, HTTPException
from fastapi.responses import Response, StreamingResponse
from sqlmodel import Session

from app.db.models import DeploymentRecord
from app.models.schemas import (
    DeploymentEvent,
    DeploymentState,
    DeploymentStatus,
    HealthResponse,
    LogEntry,
    RuntimeType,
    UploadResponse,
)
from app.services.container_lifecycle import ContainerLifecycleService
from app.services.deployment import deployment_service
from app.services.deployment_db_service import DeploymentDBService
from app.services.deployment_planner import DeploymentPlanner
from app.services.deployment_store import DEPLOYMENT_PORTS
from app.services.execution_engine import DEPLOYMENT_LOGS, ExecutionEngine
from app.services.manifest_scanner import ManifestScanner
from app.services.scanner import project_scanner
from app.utils.helpers import (
    create_deployment_workspace,
    format_file_size,
    safe_extract_zip,
    validate_zip_file,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _safe_str(value: Any) -> str:
    """Convert any value to a non-empty string, defaulting to '.'."""
    if value is None:
        return "."
    return str(value).strip() or "."


def _deploy_service(
    service: dict,
    project_root: Path,
    deployment_id: str,
    service_label: str,
) -> dict | None:
    """
    Build image, run container, and return service info dict.

    Returns None on failure (logs error but does NOT raise).
    This allows partial deployments to still return useful URLs.
    """
    try:
        working_directory = _safe_str(service.get("working_directory", "."))

        # Normalize nodejs → node
        runtime = str(service.get("runtime", "node")).lower()
        if runtime == "nodejs":
            runtime = "node"
        service["runtime"] = runtime
        service["working_directory"] = working_directory

        service_root = (project_root / working_directory).resolve()

        logger.info(
            "[Deploy][%s] Service root: %s (runtime=%s)",
            service_label,
            service_root,
            runtime,
        )

        if not service_root.exists():
            logger.error(
                "[Deploy][%s] Service root does not exist: %s",
                service_label,
                service_root,
            )
            return None

        # Generate and save Dockerfile
        dockerfile_content = ExecutionEngine.generate_dockerfile(service)
        logger.info("[Deploy][%s] Generated Dockerfile:\n%s", service_label, dockerfile_content)
        ExecutionEngine.save_dockerfile(str(service_root), dockerfile_content)

        # Build image
        image_tag = ExecutionEngine.build_image(str(service_root), service_label)
        logger.info("[Deploy][%s] Image built: %s", service_label, image_tag)

        # Run container (auto-removes stale containers)
        container_data = ContainerLifecycleService.run_container(
            image_tag,
            service_label,
            service,
        )
        container = container_data["container"]
        host_port = container_data["host_port"]
        service_url = f"http://localhost:{host_port}"

        logger.info(
            "[Deploy][%s] Container started: id=%s host_port=%s url=%s",
            service_label,
            container.id[:12],
            host_port,
            service_url,
        )

        # Health check (non-fatal)
        healthy = ContainerLifecycleService.wait_for_health(service_url, timeout=90)
        if healthy:
            logger.info("[Deploy][%s] Health check PASSED at %s", service_label, service_url)
        else:
            logger.warning(
                "[Deploy][%s] Health check timed out at %s — container may still be starting",
                service_label,
                service_url,
            )

        return {
            "runtime": runtime,
            "working_directory": working_directory,
            "url": service_url,
            "host_port": host_port,
            "container_id": container.id[:12],
            "healthy": healthy,
        }

    except Exception as exc:
        logger.error(
            "[Deploy][%s] Service deployment failed: %s",
            service_label,
            exc,
            exc_info=True,
        )
        return None


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


# ─── Upload / Deploy ──────────────────────────────────────────────────────────

@router.post("/upload", response_model=UploadResponse, tags=["Deployment"])
async def upload_project(
    frontend_file: UploadFile = File(...),
    backend_file: UploadFile | None = File(None),
):
    """
    Upload project ZIP files and orchestrate full-stack deployment.

    Flow:
      validate → extract → scan → plan → build → run → health → persist → respond
    """
    # ── Validate frontend ZIP ───────────────────────────────────────────────
    if not frontend_file.filename or not frontend_file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only .zip files are accepted")

    try:
        content = await frontend_file.read()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to read uploaded file: {exc}")

    max_size = 500 * 1024 * 1024  # 500 MB
    if len(content) > max_size:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({format_file_size(len(content))}). Maximum: 500MB",
        )
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    # ── Create workspace ────────────────────────────────────────────────────
    project_name = frontend_file.filename.rsplit(".", 1)[0]
    deployment_id, workspace = create_deployment_workspace(project_name)

    logger.info(
        "[Upload] Starting deployment_id=%s project=%s",
        deployment_id,
        project_name,
    )

    # Create in-memory deployment record
    deployment = deployment_service.create_deployment(
        project_name=project_name,
        deployment_id=deployment_id,
        workspace=workspace,
    )
    deployment.status = DeploymentStatus.UPLOADING

    # ── Save and extract frontend ZIP ───────────────────────────────────────
    frontend_zip_path = workspace / frontend_file.filename
    try:
        with open(frontend_zip_path, "wb") as f:
            f.write(content)
    except OSError as exc:
        deployment_service.set_error(deployment_id, f"Failed to save upload: {exc}")
        raise HTTPException(status_code=500, detail=f"Failed to save uploaded file: {exc}")

    is_valid, error_msg = validate_zip_file(frontend_zip_path)
    if not is_valid:
        deployment_service.set_error(deployment_id, f"Invalid ZIP: {error_msg}")
        raise HTTPException(status_code=400, detail=f"Invalid ZIP file: {error_msg}")

    deployment.status = DeploymentStatus.RUNNING
    frontend_extract_dir = workspace / "extracted"
    frontend_extract_dir.mkdir(parents=True, exist_ok=True)

    success, extract_error, frontend_project_root = safe_extract_zip(
        frontend_zip_path, frontend_extract_dir
    )
    if not success:
        deployment_service.set_error(deployment_id, f"Extraction failed: {extract_error}")
        raise HTTPException(status_code=400, detail=f"ZIP extraction failed: {extract_error}")

    logger.info(
        "[Upload] Frontend extracted to %s (%d files)",
        frontend_project_root,
        len(list(frontend_project_root.rglob("*"))),
    )

    # Clean up frontend ZIP
    try:
        frontend_zip_path.unlink()
    except OSError:
        pass

    # ── Handle optional backend ZIP ─────────────────────────────────────────
    backend_project_root: Path | None = None

    if backend_file:
        try:
            backend_content = await backend_file.read()
            backend_zip_path = workspace / backend_file.filename
            with open(backend_zip_path, "wb") as f:
                f.write(backend_content)

            backend_extract_dir = workspace / "backend_extracted"
            backend_extract_dir.mkdir(parents=True, exist_ok=True)

            b_success, b_error, backend_project_root = safe_extract_zip(
                backend_zip_path, backend_extract_dir
            )
            if not b_success:
                logger.warning(
                    "[Upload] Backend extraction failed: %s — continuing without backend",
                    b_error,
                )
                backend_project_root = None
            else:
                logger.info("[Upload] Backend extracted to %s", backend_project_root)
            try:
                backend_zip_path.unlink()
            except OSError:
                pass

        except Exception as exc:
            logger.warning("[Upload] Backend ZIP handling failed: %s — skipping", exc)
            backend_project_root = None

    # ── Scan frontend project ────────────────────────────────────────────────
    try:
        analysis = project_scanner.scan(frontend_project_root)

        # Runtime fallback from files if scanner returned unknown
        if analysis.runtime.value == "unknown":
            if (frontend_project_root / "package.json").exists():
                analysis.runtime = RuntimeType.NODEJS
                logger.info("[Scan] Runtime inferred: nodejs (package.json found)")
            elif (frontend_project_root / "requirements.txt").exists():
                analysis.runtime = RuntimeType.PYTHON
                logger.info("[Scan] Runtime inferred: python (requirements.txt found)")

        deployment.analysis = analysis

    except Exception as exc:
        logger.exception("[Scan] Project scan failed for %s", deployment_id)
        deployment_service.set_error(deployment_id, f"Scan failed: {exc}")
        raise HTTPException(status_code=500, detail=f"Project analysis failed: {exc}")

    # ── Manifest scan (for planner) ──────────────────────────────────────────
    scan_result = ManifestScanner.scan(str(frontend_project_root))
    manifests = scan_result["manifests"]
    runtime = scan_result["runtime"]
    framework = scan_result["framework"]
    entry_points = scan_result["entry_points"]

    logger.info(
        "[Scan] Frontend — runtime=%s framework=%s manifests=%d entry_points=%s",
        runtime,
        framework,
        len(manifests),
        entry_points,
    )

    # ── URL trackers — always initialized ───────────────────────────────────
    preview_url: str | None = None
    frontend_url: str | None = None
    backend_url: str | None = None
    deployed_services: list[dict] = []

    # ── Deploy Backend first (so we can inject URL into frontend env) ────────
    if backend_project_root:
        logger.info("[Deploy] Starting backend deployment from %s", backend_project_root)

        backend_scan = ManifestScanner.scan(str(backend_project_root))
        logger.info(
            "[Deploy] Backend scan — runtime=%s framework=%s",
            backend_scan["runtime"],
            backend_scan["framework"],
        )

        backend_plan = DeploymentPlanner.plan(
            manifests=backend_scan["manifests"],
            runtime=backend_scan["runtime"],
            framework=backend_scan["framework"],
            entry_points=backend_scan["entry_points"],
            project_root=str(backend_project_root),
        )

        logger.info("[Deploy] Backend plan: %s", json.dumps(backend_plan))

        backend_services = backend_plan.get("services", [])
        if not backend_services:
            logger.warning("[Deploy] Backend plan returned no services — skipping backend")
        else:
            for b_idx, b_svc in enumerate(backend_services):
                b_label = f"{deployment_id}-backend-{b_idx}"
                result = _deploy_service(b_svc, backend_project_root, deployment_id, b_label)
                if result:
                    svc_url = result["url"]
                    if backend_url is None:
                        backend_url = svc_url
                        logger.info("[Deploy] Backend URL: %s", backend_url)
                    DEPLOYMENT_PORTS[f"{deployment_id}-backend-{b_idx}"] = result["host_port"]
                    deployed_services.append({
                        **result,
                        "service_type": "backend",
                        "label": b_label,
                    })
                else:
                    logger.warning("[Deploy] Backend service %s failed to deploy", b_label)

    # ── Inject backend URL into frontend env ─────────────────────────────────
    if backend_url:
        env_file = frontend_project_root / ".env"
        env_content = (
            f"NEXT_PUBLIC_API_URL={backend_url}\n"
            f"VITE_API_URL={backend_url}\n"
            f"REACT_APP_API_URL={backend_url}\n"
        )
        try:
            env_file.write_text(env_content, encoding="utf-8")
            logger.info("[Deploy] Frontend .env injected with backend URL: %s", backend_url)
        except Exception as exc:
            logger.warning("[Deploy] Could not write frontend .env: %s", exc)

    # ── Plan and deploy frontend ─────────────────────────────────────────────
    deployment_plan = DeploymentPlanner.plan(
        manifests=manifests,
        runtime=runtime,
        framework=framework,
        entry_points=entry_points,
        project_root=str(frontend_project_root),
    )

    logger.info("[Deploy] Frontend plan: %s", json.dumps(deployment_plan))

    frontend_services = deployment_plan.get("services", [])
    if not frontend_services:
        logger.error("[Deploy] Frontend plan returned no services for %s", deployment_id)
        # Don't crash — record the partial result
    else:
        for f_idx, f_svc in enumerate(frontend_services):
            f_label = f"{deployment_id}-{f_idx}"
            result = _deploy_service(f_svc, frontend_project_root, deployment_id, f_label)
            if result:
                svc_url = result["url"]
                if preview_url is None:
                    preview_url = svc_url
                    frontend_url = svc_url
                    DEPLOYMENT_PORTS[deployment_id] = result["host_port"]
                    logger.info("[Deploy] Frontend URL: %s", frontend_url)
                deployed_services.append({
                    **result,
                    "service_type": "frontend",
                    "label": f_label,
                })
            else:
                logger.warning("[Deploy] Frontend service %s failed to deploy", f_label)

    # ── Update in-memory deployment ──────────────────────────────────────────
    deployment_service.update_analysis(deployment_id, analysis)

    final_status = DeploymentStatus.RUNNING
    if not preview_url and not backend_url:
        final_status = DeploymentStatus.FAILED
    elif not preview_url or not backend_url:
        final_status = DeploymentStatus.DEGRADED

    deployment.status = final_status

    logger.info(
        "[Deploy] Deployment %s complete — status=%s frontend=%s backend=%s services=%d",
        deployment_id,
        final_status,
        frontend_url,
        backend_url,
        len(deployed_services),
    )

    # ── Persist to DB (non-fatal) ─────────────────────────────────────────────
    record = DeploymentRecord(
        deployment_id=deployment_id,
        project_name=project_name,
        frontend_url=frontend_url or preview_url,
        backend_url=backend_url,
        status=final_status.value,
    )
    db_saved = DeploymentDBService.create_deployment(record)
    if db_saved:
        logger.info("[Deploy] Persisted deployment %s to DB", deployment_id)
    else:
        logger.warning("[Deploy] DB persistence failed for %s (non-fatal)", deployment_id)

    # ── Build canonical response ──────────────────────────────────────────────
    response_payload = UploadResponse(
        success=True,
        deployment_id=deployment_id,
        status=final_status,
        message=(
            f"Project '{project_name}' deployed successfully."
            if final_status == DeploymentStatus.RUNNING
            else f"Project '{project_name}' deployed with partial success."
        ),
        analysis=analysis,
        preview_url=preview_url,
        frontend_url=frontend_url or preview_url,
        backend_url=backend_url,
        services=deployed_services,
    )

    logger.info(
        "[Response] payload=%s",
        response_payload.model_dump(exclude={"analysis"}),
    )

    return response_payload


# ─── Deployment Lifecycle ──────────────────────────────────────────────────────

@router.post("/deployments/{deployment_id}/restart", tags=["Deployment"])
async def restart_deployment(deployment_id: str):
    """Restart all containers for a deployment."""
    result = ContainerLifecycleService().restart_containers_by_deployment(deployment_id)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@router.post("/deployments/{deployment_id}/stop", tags=["Deployment"])
async def stop_deployment(deployment_id: str):
    """Stop running deployment containers."""
    result = ContainerLifecycleService().stop_containers_by_deployment(deployment_id)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


# ─── Deployments CRUD ─────────────────────────────────────────────────────────

@router.get("/deployments/{deployment_id}", response_model=DeploymentState, tags=["Deployment"])
async def get_deployment(deployment_id: str):
    deployment = deployment_service.get_deployment(deployment_id)
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")
    return deployment


@router.get("/deployments", tags=["Deployment"])
async def list_deployments():
    """Return all deployments from PostgreSQL (persistent across restarts)."""
    return DeploymentDBService.get_all_deployments()


@router.delete("/deployments/{deployment_id}", tags=["Deployment"])
async def delete_deployment(deployment_id: str):
    """Fully delete deployment containers, images, and DB record."""
    result = ContainerLifecycleService().delete_deployment_resources(deployment_id)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


# ─── Deployment Status ────────────────────────────────────────────────────────

@router.get("/deployments/{deployment_id}/status", tags=["Deployment"])
async def get_status(deployment_id: str):
    """Return live container status from Docker."""
    try:
        client = docker.from_env()
        containers = client.containers.list(all=True)
        deployment_containers = [
            {"name": c.name, "status": c.status}
            for c in containers
            if c.name.startswith(f"container-{deployment_id}")
        ]
        return {"deployment_id": deployment_id, "containers": deployment_containers}
    except Exception as exc:
        return {"deployment_id": deployment_id, "status": "unknown", "error": str(exc)}


# ─── Deployment Logs ──────────────────────────────────────────────────────────

@router.get("/deployments/{deployment_id}/logs", tags=["Deployment"])
async def get_logs(deployment_id: str):
    """Return accumulated deployment logs."""
    logs = DEPLOYMENT_LOGS.get(deployment_id, [])
    return {"deployment_id": deployment_id, "logs": logs}


# ─── Preview Proxy ────────────────────────────────────────────────────────────

@router.get("/preview/{deployment_id}", tags=["Preview"])
async def preview_proxy(deployment_id: str):
    """Proxy the root response from the deployed frontend container."""
    port = DEPLOYMENT_PORTS.get(deployment_id)
    if not port:
        return Response(content="Deployment not found or not running", status_code=404)

    target_url = f"http://localhost:{port}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            upstream = await client.get(target_url, follow_redirects=True)
    except Exception as exc:
        return Response(content=f"Upstream error: {exc}", status_code=502)

    excluded_headers = {"content-encoding", "transfer-encoding", "connection"}
    headers = {k: v for k, v in upstream.headers.items() if k.lower() not in excluded_headers}

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=headers,
    )


# ─── SSE Events (mock — placeholder for future real streaming) ────────────────

async def _mock_event_stream(deployment_id: str) -> AsyncGenerator[str, None]:
    """Generate mock Server-Sent Events for deployment progress."""
    mock_events = [
        {"event_type": "status", "data": {"status": "analyzing", "message": "Analyzing project..."}},
        {"event_type": "status", "data": {"status": "building", "message": "Building Docker image..."}},
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
    """Stream deployment events via Server-Sent Events."""
    return StreamingResponse(
        _mock_event_stream(deployment_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
