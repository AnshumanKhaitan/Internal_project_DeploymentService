"""
Anti Gravity Deployments - API Routes

REST API endpoints for the deployment platform.
Stabilized for recursive self-hosting and production-grade reliability.

Key improvements:
- Scanner's install_command / start_command / framework seed the planner
- Monorepo workspace root respected for service_root resolution
- _deploy_service never raises (returns None on any failure)
- Full build stderr + runtime stdout captured in logs
- All URL fields always present in UploadResponse
- DEGRADED status on partial success, never crashes
- DB failure never blocks response
- Preview proxy forwards ALL sub-paths (_next/static/*, images, fonts etc.)
"""

import asyncio
import json
import logging
import docker
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator, Any

import httpx
from fastapi import APIRouter, File, Request, UploadFile, HTTPException
from fastapi.responses import Response, StreamingResponse

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
from app.utils.docker_client import docker_socket_available, docker_socket_path
from app.utils.helpers import (
    browser_api_url_for_deploy,
    create_deployment_workspace,
    format_file_size,
    is_anti_gravity_platform,
    orchestrator_public_api_url,
    resolve_project_tree,
    safe_extract_zip,
    validate_zip_file,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _coerce_str(value: Any, default: str = ".") -> str:
    """Convert any value to a non-null, non-empty string."""
    if value is None:
        return default
    s = str(value).strip()
    if s.lower() in ("none", "null", "undefined", ""):
        return default
    return s


def _deploy_service(
    service: dict,
    project_root: Path,
    deployment_id: str,
    service_label: str,
    workspace_subdir: str | None = None,
) -> dict | None:
    """
    Build image, run container, and return service info dict.

    Returns None on any failure — never raises.
    Handles monorepo workspace roots via workspace_subdir.
    """
    from app.services.execution_engine import _append_log

    try:
        # ── Normalize service fields ────────────────────────────────────────
        runtime = _coerce_str(service.get("runtime", "node")).lower()
        if runtime in ("nodejs", "node.js"):
            runtime = "node"
        service["runtime"] = runtime

        working_directory = _coerce_str(service.get("working_directory", "."))
        service["working_directory"] = working_directory

        install_command = _coerce_str(service.get("install_command", ""), "")
        start_command = _coerce_str(service.get("start_command", ""), "")
        framework = _coerce_str(service.get("framework", ""), "")

        # ── Resolve service root ────────────────────────────────────────────
        # Priority: workspace_subdir (monorepo) → working_directory from plan → project_root
        if workspace_subdir and workspace_subdir not in (".", ""):
            service_root = (project_root / workspace_subdir).resolve()
            logger.info("[Deploy][%s] Using monorepo workspace root: %s", service_label, service_root)
        else:
            service_root = (project_root / working_directory).resolve()

        logger.info(
            "[Deploy][%s] service_root=%s runtime=%s framework=%s",
            service_label, service_root, runtime, framework
        )

        if not service_root.exists():
            logger.error("[Deploy][%s] Service root does not exist: %s", service_label, service_root)
            _append_log(deployment_id, f"[Error] Service root not found: {service_root}")
            return None

        # ── Generate Dockerfile ─────────────────────────────────────────────
        # Enrich service with framework so Dockerfile generator picks right base image/port
        # Pass service_root so Python Dockerfile can run dependency sanitization
        enriched_service = {**service, "framework": framework}
        dockerfile_content = ExecutionEngine.generate_dockerfile(
            enriched_service, project_root=str(service_root)
        )
        logger.info("[Deploy][%s] Dockerfile generated (%d bytes)", service_label, len(dockerfile_content))
        _append_log(deployment_id, f"[Build] Generating Dockerfile for {service_label}")
        ExecutionEngine.save_dockerfile(str(service_root), dockerfile_content)

        # ── Build Docker image ──────────────────────────────────────────────
        _append_log(deployment_id, f"[Build] Building image for {service_label}...")
        image_tag = ExecutionEngine.build_image(str(service_root), service_label)
        logger.info("[Deploy][%s] Image built: %s", service_label, image_tag)
        _append_log(deployment_id, f"[Build] Image {image_tag} built successfully")

        # ── Run container ───────────────────────────────────────────────────
        _append_log(deployment_id, f"[Deploy] Starting container for {service_label}...")
        container_data = ContainerLifecycleService.run_container(
            image_tag,
            service_label,
            enriched_service,
            project_root=str(service_root),
        )
        container = container_data["container"]
        host_port = container_data["host_port"]
        service_url = f"http://localhost:{host_port}"

        logger.info(
            "[Deploy][%s] Container started: id=%s port=%s url=%s",
            service_label, container.id[:12], host_port, service_url
        )
        _append_log(deployment_id, f"[Deploy] Container running at {service_url}")

        # ── Health check + crash diagnosis ──────────────────────────────────
        _append_log(deployment_id, f"[Health] Checking {service_url}...")
        healthy = ContainerLifecycleService.wait_for_health(
            service_url,
            timeout=180,
            framework=framework,
        )

        if healthy:
            _append_log(deployment_id, f"[Health] {service_url} is UP ✓")
        else:
            # Health check timed out — run crash diagnosis to find exact reason
            _append_log(deployment_id, f"[Health] {service_url} did not respond within 180s — diagnosing...")
            diagnosis = ContainerLifecycleService.diagnose_container_crash(
                service_label, deployment_id=deployment_id
            )
            if diagnosis["crash_detected"]:
                _append_log(
                    deployment_id,
                    f"[Health][CRASH] Container exited (code={diagnosis['exit_code']}) — "
                    f"{diagnosis['crash_category']}: {diagnosis['crash_reason'][:300]}"
                )
            else:
                _append_log(
                    deployment_id,
                    f"[Health] Container still running but not responding — "
                    f"possible slow startup or port mismatch. Category: {diagnosis['crash_category']}"
                )

        return {
            "runtime": runtime,
            "framework": framework,
            "working_directory": working_directory,
            "url": service_url,
            "host_port": host_port,
            "container_id": container.id[:12],
            "healthy": healthy,
        }

    except Exception as exc:
        logger.error("[Deploy][%s] Failed: %s", service_label, exc, exc_info=True)
        from app.services.execution_engine import _append_log as _al
        try:
            _al(deployment_id, f"[Error] {service_label}: {exc}")
        except Exception:
            pass
        return None


# ─── Health ───────────────────────────────────────────────────────────────────

@router.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """Health check endpoint for monitoring."""
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
    Upload project ZIP file(s) and orchestrate full-stack deployment.

    Flow:
      validate → extract → scan (ManifestScanner) → plan (Ollama + fallback)
      → build → run → health → persist → respond

    Always returns: deployment_id, status, preview_url, frontend_url, backend_url.
    """
    if not docker_socket_available():
        raise HTTPException(
            status_code=503,
            detail=(
                "Docker is not available on this API server "
                f"({docker_socket_path()} missing). "
                "Deploy from the main app at http://localhost:3000 with Docker running, "
                "or restart the root backend with /var/run/docker.sock mounted. "
                "Uploading from an in-preview copy only works if that preview's backend "
                "was started with Docker socket access."
            ),
        )

    # ── Validate frontend ZIP ───────────────────────────────────────────────
    if not frontend_file.filename or not frontend_file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only .zip files are accepted")

    try:
        content = await frontend_file.read()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to read uploaded file: {exc}")

    if len(content) > 500 * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({format_file_size(len(content))}). Maximum: 500MB",
        )
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    # ── Create workspace ────────────────────────────────────────────────────
    project_name = frontend_file.filename.rsplit(".", 1)[0]
    deployment_id, workspace = create_deployment_workspace(project_name)

    logger.info("[Upload] deployment_id=%s project=%s", deployment_id, project_name)

    deployment = deployment_service.create_deployment(
        project_name=project_name,
        deployment_id=deployment_id,
        workspace=workspace,
    )
    deployment.status = DeploymentStatus.UPLOADING

    # ── Initialize URL trackers BEFORE any try/except ──────────────────────
    preview_url: str | None = None
    frontend_url: str | None = None
    backend_url: str | None = None
    deployed_services: list[dict] = []
    analysis = None

    # ── Extract frontend ZIP ────────────────────────────────────────────────
    frontend_zip_path = workspace / frontend_file.filename
    try:
        frontend_zip_path.write_bytes(content)
    except OSError as exc:
        deployment_service.set_error(deployment_id, f"Save failed: {exc}")
        raise HTTPException(status_code=500, detail=f"Failed to save file: {exc}")

    is_valid, error_msg = validate_zip_file(frontend_zip_path)
    if not is_valid:
        deployment_service.set_error(deployment_id, f"Invalid ZIP: {error_msg}")
        raise HTTPException(status_code=400, detail=f"Invalid ZIP: {error_msg}")

    frontend_extract_dir = workspace / "extracted"
    frontend_extract_dir.mkdir(parents=True, exist_ok=True)
    success, extract_error, frontend_project_root = safe_extract_zip(
        frontend_zip_path, frontend_extract_dir
    )
    if not success:
        deployment_service.set_error(deployment_id, f"Extraction failed: {extract_error}")
        raise HTTPException(status_code=400, detail=f"ZIP extraction failed: {extract_error}")

    # Cleanup zip
    try:
        frontend_zip_path.unlink()
    except OSError:
        pass

    logger.info(
        "[Upload] Frontend extracted: root=%s files=%d",
        frontend_project_root,
        sum(1 for _ in frontend_project_root.rglob("*") if _.is_file()),
    )

    # ── Extract optional backend ZIP ────────────────────────────────────────
    backend_project_root: Path | None = None

    if backend_file and backend_file.filename:
        try:
            backend_content = await backend_file.read()
            if backend_content:
                backend_zip_path = workspace / backend_file.filename
                backend_zip_path.write_bytes(backend_content)
                backend_extract_dir = workspace / "backend_extracted"
                backend_extract_dir.mkdir(parents=True, exist_ok=True)
                b_ok, b_err, backend_project_root = safe_extract_zip(
                    backend_zip_path, backend_extract_dir
                )
                if not b_ok:
                    logger.warning("[Upload] Backend extraction failed: %s — skipping", b_err)
                    backend_project_root = None
                else:
                    logger.info("[Upload] Backend extracted: %s", backend_project_root)
                try:
                    backend_zip_path.unlink()
                except OSError:
                    pass
        except Exception as exc:
            logger.warning("[Upload] Backend ZIP error: %s — skipping", exc)
            backend_project_root = None

    # ── Scan frontend project (ProjectScanner for analysis display) ─────────
    try:
        analysis = project_scanner.scan(frontend_project_root)
        # Fallback runtime from filesystem if scanner returns unknown
        if analysis.runtime == RuntimeType.UNKNOWN or analysis.runtime.value == "unknown":
            if (frontend_project_root / "package.json").exists():
                analysis.runtime = RuntimeType.NODEJS
            elif (frontend_project_root / "requirements.txt").exists():
                analysis.runtime = RuntimeType.PYTHON
        deployment.analysis = analysis
    except Exception as exc:
        logger.warning("[Scan] ProjectScanner failed: %s — continuing without analysis", exc)
        analysis = None

    # ── ManifestScanner — enriched scan for deployment planner ─────────────
    try:
        scan_result = ManifestScanner.scan(str(frontend_project_root))
    except Exception as exc:
        logger.error("[Scan] ManifestScanner failed: %s — using minimal fallback", exc)
        scan_result = {
            "runtime": "node",
            "framework": "unknown",
            "start_command": "npm start",
            "install_command": "npm install",
            "detected_port": 3000,
            "entry_points": [],
            "manifests": [],
            "package_manager": "npm",
            "workspace_root": None,
            "is_monorepo": False,
            "scan_root": str(frontend_project_root),
        }

    runtime = scan_result["runtime"]
    framework = scan_result["framework"]
    entry_points = scan_result["entry_points"]
    manifests = scan_result["manifests"]
    install_command = scan_result.get("install_command", "")
    start_command = scan_result.get("start_command", "")
    workspace_subdir = scan_result.get("workspace_root")  # None or e.g. "frontend"

    logger.info(
        "[Scan] Frontend — runtime=%s framework=%s workspace=%s start='%s'",
        runtime, framework, workspace_subdir, start_command,
    )

    deployment.status = DeploymentStatus.BUILDING

    # ── Deploy Backend first (so URL can be injected into frontend env) ─────
    if backend_project_root:
        logger.info("[Deploy] Backend deployment from %s", backend_project_root)

        try:
            b_scan = ManifestScanner.scan(str(backend_project_root))
        except Exception as exc:
            logger.warning("[Deploy] Backend scan failed: %s — using fallback", exc)
            b_scan = {
                "runtime": "python",
                "framework": "fastapi",
                "start_command": "uvicorn main:app --host 0.0.0.0 --port 8000",
                "install_command": "pip install -r requirements.txt",
                "detected_port": 8000,
                "entry_points": [],
                "manifests": [],
                "workspace_root": None,
            }

        backend_plan = DeploymentPlanner.plan(
            manifests=b_scan["manifests"],
            runtime=b_scan["runtime"],
            framework=b_scan["framework"],
            entry_points=b_scan["entry_points"],
            project_root=str(backend_project_root),
            install_command=b_scan.get("install_command", ""),
            start_command=b_scan.get("start_command", ""),
        )
        logger.info("[Deploy] Backend plan: %s", json.dumps(backend_plan))

        for b_idx, b_svc in enumerate(backend_plan.get("services", [])):
            b_label = f"{deployment_id}-backend-{b_idx}"
            # Add framework to service for Dockerfile generator
            b_svc.setdefault("framework", b_scan["framework"])
            if is_anti_gravity_platform(backend_project_root):
                b_svc["mount_docker_socket"] = True

            result = _deploy_service(
                b_svc,
                backend_project_root,
                deployment_id,
                b_label,
                workspace_subdir=b_scan.get("workspace_root"),
            )
            if result:
                svc_url = result["url"]
                if backend_url is None:
                    backend_url = svc_url
                    logger.info("[Deploy] Backend URL: %s", backend_url)
                DEPLOYMENT_PORTS[f"{deployment_id}-backend-{b_idx}"] = result["host_port"]
                deployed_services.append({**result, "service_type": "backend", "label": b_label})
            else:
                logger.warning("[Deploy] Backend service %s failed", b_label)

    # ── Inject API URL into frontend env (baked into Next.js at docker build) ─
    api_for_browser = browser_api_url_for_deploy(
        frontend_project_root, backend_url, workspace_subdir
    )
    env_tree = resolve_project_tree(frontend_project_root, workspace_subdir)
    env_path = env_tree / ".env"
    env_content = (
        f"NEXT_PUBLIC_API_URL={api_for_browser}\n"
        f"VITE_API_URL={api_for_browser}\n"
        f"REACT_APP_API_URL={api_for_browser}\n"
        f"API_URL={api_for_browser}\n"
    )
    try:
        env_path.write_text(env_content, encoding="utf-8")
        logger.info(
            "[Deploy] Frontend .env → %s (api=%s)",
            env_path,
            api_for_browser,
        )
        if is_anti_gravity_platform(env_tree):
            from app.services.execution_engine import _append_log

            _append_log(
                deployment_id,
                f"[Deploy] Platform preview uses root API {api_for_browser} — "
                "upload other projects from that preview or localhost:3000",
            )
    except Exception as exc:
        logger.warning("[Deploy] Could not write .env: %s", exc)

    # ── Plan and deploy frontend ─────────────────────────────────────────────
    frontend_plan = DeploymentPlanner.plan(
        manifests=manifests,
        runtime=runtime,
        framework=framework,
        entry_points=entry_points,
        project_root=str(frontend_project_root),
        install_command=install_command,
        start_command=start_command,
    )
    logger.info("[Deploy] Frontend plan: %s", json.dumps(frontend_plan))

    for f_idx, f_svc in enumerate(frontend_plan.get("services", [])):
        f_label = f"{deployment_id}-{f_idx}"
        # Add framework to service for Dockerfile generator
        f_svc.setdefault("framework", framework)

        result = _deploy_service(
            f_svc,
            frontend_project_root,
            deployment_id,
            f_label,
            workspace_subdir=workspace_subdir,
        )
        if result:
            svc_url = result["url"]
            if preview_url is None:
                preview_url = svc_url
                frontend_url = svc_url
                DEPLOYMENT_PORTS[deployment_id] = result["host_port"]
                logger.info("[Deploy] Frontend URL: %s", frontend_url)
            deployed_services.append({**result, "service_type": "frontend", "label": f_label})
        else:
            logger.warning("[Deploy] Frontend service %s failed", f_label)

    # ── Determine final status ───────────────────────────────────────────────
    if preview_url or frontend_url:
        if backend_file and not backend_url:
            final_status = DeploymentStatus.DEGRADED  # backend failed
        else:
            final_status = DeploymentStatus.RUNNING
    elif backend_url:
        final_status = DeploymentStatus.DEGRADED  # frontend failed
    else:
        final_status = DeploymentStatus.FAILED

    deployment.status = final_status
    if analysis:
        deployment_service.update_analysis(deployment_id, analysis)

    logger.info(
        "[Deploy] %s complete — status=%s frontend=%s backend=%s services=%d",
        deployment_id, final_status, frontend_url, backend_url, len(deployed_services),
    )

    # ── Persist to DB (non-fatal) ─────────────────────────────────────────────
    try:
        record = DeploymentRecord(
            deployment_id=deployment_id,
            project_name=project_name,
            frontend_url=frontend_url or preview_url,
            backend_url=backend_url,
            status=final_status.value,
        )
        db_ok = DeploymentDBService.create_deployment(record)
        if db_ok:
            logger.info("[Deploy] Persisted to DB: %s", deployment_id)
        else:
            logger.warning("[Deploy] DB persistence failed (non-fatal): %s", deployment_id)
    except Exception as exc:
        logger.error("[Deploy] DB exception (non-fatal): %s", exc)

    # ── Canonical response — all URL fields always present ─────────────────
    message = (
        f"'{project_name}' deployed successfully."
        if final_status == DeploymentStatus.RUNNING
        else f"'{project_name}' deployed with partial success."
        if final_status == DeploymentStatus.DEGRADED
        else f"'{project_name}' deployment failed. Check logs."
    )

    return UploadResponse(
        success=final_status != DeploymentStatus.FAILED,
        deployment_id=deployment_id,
        status=final_status,
        message=message,
        analysis=analysis,
        preview_url=preview_url,
        frontend_url=frontend_url or preview_url,
        backend_url=backend_url,
        services=deployed_services,
    )


# ─── Deployment Lifecycle ──────────────────────────────────────────────────────

@router.post("/deployments/{deployment_id}/restart", tags=["Deployment"])
async def restart_deployment(deployment_id: str):
    """Restart all containers for a deployment."""
    result = ContainerLifecycleService().restart_containers_by_deployment(deployment_id)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Restart failed"))
    return result


@router.post("/deployments/{deployment_id}/stop", tags=["Deployment"])
async def stop_deployment(deployment_id: str):
    """Stop running deployment containers."""
    result = ContainerLifecycleService().stop_containers_by_deployment(deployment_id)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Stop failed"))
    return result


@router.post("/deployments/{deployment_id}/cleanup", tags=["Deployment"])
async def cleanup_deployment(deployment_id: str):
    """Remove orphaned containers for a deployment (for failed/partial deployments)."""
    removed = ContainerLifecycleService.cleanup_orphaned_containers(deployment_id)
    return {"success": True, "removed": removed}


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
        raise HTTPException(status_code=500, detail=result.get("error", "Delete failed"))
    return result


# ─── Deployment Status ────────────────────────────────────────────────────────

@router.get("/deployments/{deployment_id}/status", tags=["Deployment"])
async def get_status(deployment_id: str):
    """Return live container status from Docker."""
    try:
        client = docker.from_env()
        containers = [
            {
                "name": c.name,
                "status": c.status,
                "id": c.id[:12],
                "ports": c.ports,
            }
            for c in client.containers.list(all=True)
            if c.name.startswith(f"container-{deployment_id}")
        ]
        return {"deployment_id": deployment_id, "containers": containers}
    except Exception as exc:
        return {"deployment_id": deployment_id, "containers": [], "error": str(exc)}


# ─── Deployment Logs ──────────────────────────────────────────────────────────

@router.get("/deployments/{deployment_id}/logs", tags=["Deployment"])
async def get_logs(deployment_id: str):
    """Return accumulated deployment logs (build + runtime)."""
    # Merge all log keys that belong to this deployment_id
    all_logs: list[str] = []

    # Main deployment log
    all_logs.extend(DEPLOYMENT_LOGS.get(deployment_id, []))

    # Per-service logs (e.g. {deployment_id}-0, {deployment_id}-backend-0)
    for key, logs in DEPLOYMENT_LOGS.items():
        if key != deployment_id and key.startswith(deployment_id):
            all_logs.extend(logs)

    return {"deployment_id": deployment_id, "logs": all_logs}


# ─── Preview Proxy ────────────────────────────────────────────────────────────
# Proxies ALL paths so _next/static/*, images, fonts, API sub-routes all work.

_PROXY_EXCLUDED_HEADERS = frozenset({
    "content-encoding", "transfer-encoding", "connection",
    "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "upgrade",
})


async def _proxy_to_container(
    deployment_id: str,
    path: str,
    request,
) -> Response:
    """Core proxy logic — forwards any path to the container and returns its response."""
    port = DEPLOYMENT_PORTS.get(deployment_id)
    if not port:
        return Response(
            content="<html><body><h2>Deployment not found or not running</h2></body></html>",
            status_code=404,
            media_type="text/html",
        )

    target_url = f"http://localhost:{port}/{path}"
    if request.query_params:
        target_url = f"{target_url}?{request.query_params}"

    # Forward safe request headers
    forward_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in (
            "host", "content-length", "transfer-encoding",
            "connection", "upgrade",
        )
    }
    # Rewrite host to container
    forward_headers["host"] = f"localhost:{port}"
    forward_headers["accept-encoding"] = "identity"
    accept = forward_headers.get("accept", "")
    if "text/html" not in accept.lower():
        forward_headers["accept"] = (
            "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        )

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,
            limits=httpx.Limits(max_keepalive_connections=10),
        ) as client:
            method  = request.method.upper()
            body    = await request.body() if method in ("POST", "PUT", "PATCH") else None
            upstream = await client.request(
                method=method,
                url=target_url,
                headers=forward_headers,
                content=body,
            )
    except httpx.ConnectError:
        if path == "" or path == "/":
            return Response(
                content="<html><body><h2>Container not reachable — may still be starting</h2></body></html>",
                status_code=502,
                media_type="text/html",
            )
        # For assets, return proper 503 so browser retries
        return Response(status_code=503)
    except httpx.TimeoutException:
        return Response(status_code=504)
    except Exception as exc:
        logger.warning("[Proxy] Error for %s%s: %s", deployment_id, path, exc)
        return Response(content=f"Proxy error: {exc}", status_code=502)

    # Filter hop-by-hop headers
    resp_headers = {
        k: v for k, v in upstream.headers.items()
        if k.lower() not in _PROXY_EXCLUDED_HEADERS
    }
    # Ensure CORS permissive for preview
    resp_headers["access-control-allow-origin"] = "*"

    content_type = resp_headers.get("content-type", "")

    # ── HTML rewriting ─────────────────────────────────────────────────────────
    # Next.js embeds absolute root-relative paths like /_next/static/... in its
    # HTML output. The browser (inside an iframe on localhost:3000) resolves these
    # against the iframe's origin, not through our proxy. We rewrite them so
    # every /_next/* and /favicon.ico request goes through /api/preview/{id}/...
    if "text/html" in content_type:
        try:
            html = upstream.content.decode("utf-8", errors="replace")
            proxy_base = f"/api/preview/{deployment_id}"
            html = _rewrite_preview_html(html, proxy_base)
            content = html.encode("utf-8")
            resp_headers["content-type"] = "text/html; charset=utf-8"
            # Remove content-length — it changed after rewriting
            resp_headers.pop("content-length", None)
        except Exception as exc:
            logger.warning("[Proxy] HTML rewrite failed (serving raw): %s", exc)
            content = upstream.content
    else:
        content = upstream.content

    return Response(
        content=content,
        status_code=upstream.status_code,
        headers=resp_headers,
    )


def _rewrite_preview_html(html: str, proxy_base: str) -> str:
    """
    Rewrite root-relative asset paths in proxied Next.js HTML so that
    /_next/static/*, /_next/image, /favicon.ico, etc. all route through
    the Anti Gravity preview proxy instead of hitting the iframe origin.

    proxy_base example: "/api/preview/0641fa4b"
    """
    import re as _re

    # ── 1. Rewrite href/src/action/data-src attributes ────────────────────────
    # Matches: src="/_next/..." href="/_next/..." and common static files
    html = _re.sub(
        r'(src|href|action|data-src)=(["\'])(/_next/[^"\']*|/favicon\.ico|/robots\.txt|/sitemap\.xml)(["\'])',
        lambda m: f'{m.group(1)}={m.group(2)}{proxy_base}{m.group(3)}{m.group(4)}',
        html,
    )

    # ── 2. Rewrite CSS url("/_next/...") references ───────────────────────────
    html = _re.sub(
        r'url\((["\']?)(/_next/[^"\')\s]+)(["\']?)\)',
        lambda m: f'url({m.group(1)}{proxy_base}{m.group(2)}{m.group(3)})',
        html,
    )

    # ── 3. Rewrite Next.js __NEXT_DATA__ assetPrefix ──────────────────────────
    # This JSON blob is injected into every Next.js page. Setting assetPrefix
    # makes the Next.js runtime load _next/static chunks through the proxy.
    html = _re.sub(
        r'"assetPrefix"\s*:\s*""',
        f'"assetPrefix":"{proxy_base}"',
        html,
    )

    # ── 4. Rewrite <link rel="preload"> / <link rel="stylesheet"> hrefs ───────
    html = _re.sub(
        r'(<link[^>]+(?:href|as)=["\'])(/_next/[^"\']+)(["\'])',
        lambda m: f'{m.group(1)}{proxy_base}{m.group(2)}{m.group(3)}',
        html,
    )

    # ── 5. Inject <base> as belt-and-suspenders ───────────────────────────────
    # Catches any root-relative path not matched by the regexes above.
    # Next.js uses pushState so <base> doesn't break client-side routing.
    if "<base " not in html and "<head>" in html:
        html = html.replace(
            "<head>",
            f'<head><base href="{proxy_base}/" data-ag-injected="1">',
            1,
        )

    return html


@router.get("/preview/{deployment_id}", tags=["Preview"])
async def preview_proxy_root(deployment_id: str, request: Request):
    """Proxy the root / of the deployed frontend container."""
    return await _proxy_to_container(deployment_id, "", request)


@router.api_route(
    "/preview/{deployment_id}/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    tags=["Preview"],
)
async def preview_proxy_path(deployment_id: str, path: str, request: Request):
    """
    Wildcard proxy — forwards ALL paths to the container.
    Handles: _next/static/*, _next/image/*, public/*, images, fonts, API routes.
    """
    return await _proxy_to_container(deployment_id, path, request)


# ─── SSE Event Stream ─────────────────────────────────────────────────────────

async def _log_event_stream(deployment_id: str) -> AsyncGenerator[str, None]:
    """Stream deployment log lines as Server-Sent Events."""
    sent = 0
    idle_cycles = 0

    for _ in range(120):  # max 120 iterations × 1s = 2 min
        all_logs: list[str] = []
        all_logs.extend(DEPLOYMENT_LOGS.get(deployment_id, []))
        for key, logs in DEPLOYMENT_LOGS.items():
            if key != deployment_id and key.startswith(deployment_id):
                all_logs.extend(logs)

        new_lines = all_logs[sent:]
        if new_lines:
            idle_cycles = 0
            for line in new_lines:
                event = {"type": "log", "line": line, "index": sent}
                yield f"data: {json.dumps(event)}\n\n"
                sent += 1
        else:
            idle_cycles += 1
            if idle_cycles >= 10:
                yield f"data: {json.dumps({'type': 'done', 'total': sent})}\n\n"
                break

        await asyncio.sleep(1)


@router.get("/deployments/{deployment_id}/events", tags=["Deployment"])
async def deployment_events(deployment_id: str):
    """Stream deployment log events via Server-Sent Events."""
    return StreamingResponse(
        _log_event_stream(deployment_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
