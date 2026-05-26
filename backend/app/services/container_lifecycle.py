"""
Anti Gravity Deployments — Container Lifecycle Service

Manages Docker container creation, health checks, log streaming,
restart, stop, and cleanup operations.

Key improvements:
- Port derived from service descriptor (not hardcoded 3000/8000)
- Stale container cleanup before every start
- Orphan container cleanup for previous deployment generations
- Health check with configurable timeout and interval
- Never raises from wait_for_health
"""

import logging
import os
import re
import threading
import time
from pathlib import Path

import docker
import requests

from app.utils.docker_client import (
    docker_socket_volumes,
    get_docker_client,
    service_needs_docker_socket,
)
from app.utils.helpers import get_upload_dir

logger = logging.getLogger(__name__)

_UPLOAD_DIR = os.environ.get("UPLOAD_DIR", str(get_upload_dir()))


def _port_from_service(service: dict) -> int:
    """
    Determine the container-internal port from a service descriptor.

    Priority:
    1. Explicit 'port' field in service dict
    2. Parse port from start_command string
    3. Runtime default (8000 for python, 3000 for node)
    """
    # Explicit field
    explicit = service.get("port")
    if explicit:
        try:
            return int(explicit)
        except (ValueError, TypeError):
            pass

    # Parse from start_command — handles both '--port 8000' and ':8000'
    start_cmd = str(service.get("start_command", ""))
    match = re.search(r"(?:--port[=\s]+|:)(\d{4,5})\b", start_cmd)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            pass

    # Framework defaults
    framework = str(service.get("framework", "")).lower()
    framework_ports = {
        "nextjs": 3000, "react": 3000, "vite": 5173, "vue": 5173,
        "angular": 4200, "express": 3000, "node": 3000,
        "fastapi": 8000, "flask": 5000, "django": 8000, "python": 8000,
    }
    if framework in framework_ports:
        return framework_ports[framework]

    # Runtime default
    runtime = str(service.get("runtime", "node")).lower()
    return 8000 if runtime == "python" else 3000


class ContainerLifecycleService:

    # ── Class methods (stateless, no Docker client needed at class level) ──────

    @classmethod
    def run_container(
        cls,
        image_tag: str,
        container_name: str,
        service: dict,
        project_root: str | None = None,
    ) -> dict:
        """
        Start a container, removing any existing container with the same name first.

        Returns {"container": <Container>, "host_port": <str>}.
        Raises on unrecoverable failure.
        """
        client = get_docker_client()
        full_name = f"container-{container_name}"
        container_port = _port_from_service(service)

        # ── Stale container cleanup ──────────────────────────────────────────
        cls._remove_existing_container(client, full_name)

        network_name = None
        try:
            import socket
            me = client.containers.get(socket.gethostname())
            networks = list(me.attrs["NetworkSettings"]["Networks"].keys())
            if networks:
                network_name = networks[0]
        except Exception as exc:
            logger.warning("[Container] Could not detect network: %s", exc)

        logger.info(
            "[Container] Starting '%s' from image '%s' (container_port=%d)",
            full_name, image_tag, container_port,
        )

        run_kwargs: dict = {
            "image": image_tag,
            "detach": True,
            "ports": {f"{container_port}/tcp": None},
            "name": full_name,
            "network": network_name,
        }

        if service_needs_docker_socket(service, project_root):
            upload_host = str(Path(_UPLOAD_DIR).resolve())
            Path(upload_host).mkdir(parents=True, exist_ok=True)
            volumes = docker_socket_volumes()
            volumes[upload_host] = {"bind": upload_host, "mode": "rw"}
            run_kwargs["volumes"] = volumes
            logger.info(
                "[Container] Docker socket + uploads mounted for orchestrator '%s'",
                full_name,
            )

        internal_api = service.get("internal_api_url")
        if internal_api:
            run_kwargs["environment"] = {
                **service.get("environment", {}),
                "INTERNAL_API_URL": str(internal_api),
                "NEXT_PUBLIC_API_URL": os.environ.get(
                    "ORCHESTRATOR_PUBLIC_API_URL",
                    f"http://localhost:{service.get('orchestrator_api_port', 8000)}",
                ),
            }

        container = client.containers.run(**run_kwargs)

        container.reload()

        # Stream logs in background
        cls.stream_container_logs(container, container_name)

        ports = container.attrs["NetworkSettings"]["Ports"]
        logger.debug("[Container] Port bindings: %s", ports)

        port_data = ports.get(f"{container_port}/tcp")
        if not port_data:
            # Container may have immediately exited — get last few log lines for diagnosis
            try:
                last_logs = container.logs(tail=20).decode("utf-8", errors="ignore")
                logger.error("[Container] '%s' exited immediately. Last logs:\n%s", full_name, last_logs)
            except Exception:
                pass
            raise RuntimeError(
                f"No host port mapping for {full_name} on {container_port}/tcp. "
                f"Container may have exited — check build/startup logs."
            )

        host_port = port_data[0]["HostPort"]
        logger.info(
            "[Container] '%s' started — id=%s host_port=%s",
            full_name, container.id[:12], host_port,
        )

        return {"container": container, "host_port": host_port}

    @staticmethod
    def _remove_existing_container(client, name: str) -> None:
        """Remove an existing container with the given name (idempotent)."""
        try:
            existing = client.containers.get(name)
            logger.info("[Container] Removing stale container '%s' (id=%s)", name, existing.id[:12])
            try:
                existing.stop(timeout=5)
            except Exception:
                pass
            existing.remove(force=True)
            logger.info("[Container] Stale container '%s' removed", name)
        except docker.errors.NotFound:
            pass
        except Exception as exc:
            logger.warning("[Container] Could not remove '%s': %s", name, exc)

    @classmethod
    def stream_container_logs(
        cls,
        container,
        deployment_id: str,
    ) -> None:
        """
        Start a daemon thread that streams container stdout/stderr into DEPLOYMENT_LOGS.
        Includes both build-time and runtime output.
        """
        def _stream():
            try:
                from app.services.execution_engine import _append_log
                # Stream from container start
                for raw_line in container.logs(stream=True, follow=True, stdout=True, stderr=True):
                    line = raw_line.decode("utf-8", errors="ignore").strip()
                    if line:
                        _append_log(deployment_id, f"[Runtime] {line}")
                        logger.debug("[ContainerLog][%s] %s", deployment_id, line)
            except Exception as exc:
                logger.warning("[ContainerLog][%s] Stream ended: %s", deployment_id, exc)

        t = threading.Thread(target=_stream, daemon=True, name=f"logs-{deployment_id}")
        t.start()
        logger.debug("[Container] Log streaming started for %s", deployment_id)

    @classmethod
    def wait_for_health(
        cls,
        url: str,
        timeout: int = 180,
        interval: int = 3,
        framework: str = "",
    ) -> bool:
        """
        Poll the given URL until it returns a non-5xx status or timeout.

        - timeout: 180s default (Next.js build+start can take 60-120s)
        - interval: 3s between attempts
        - framework: used for log hints only
        Returns True if healthy within timeout, False otherwise. Never raises.
        """
        label = f"[{framework.upper()}]" if framework else ""
        logger.info(
            "[Health]%s Waiting for %s (timeout=%ds interval=%ds)",
            label, url, timeout, interval,
        )
        start = time.time()
        attempt = 0

        while time.time() - start < timeout:
            attempt += 1
            try:
                resp = requests.get(url, timeout=8, allow_redirects=True)
                if resp.status_code < 500:
                    elapsed = time.time() - start
                    logger.info(
                        "[Health]%s %s healthy in %.1fs (attempt=%d status=%d)",
                        label, url, elapsed, attempt, resp.status_code,
                    )
                    from app.services.execution_engine import _append_log
                    try:
                        dep_id = url.split("localhost:")[-1].split("/")[0] if "localhost" in url else url
                        _append_log(dep_id, f"[Health] Service UP at {url} (status={resp.status_code}, elapsed={elapsed:.1f}s)")
                    except Exception:
                        pass
                    return True
                else:
                    logger.debug("[Health]%s attempt=%d status=%d", label, attempt, resp.status_code)
            except requests.exceptions.ConnectionError:
                if attempt % 10 == 0:
                    logger.info("[Health]%s Still starting... attempt=%d (%.0fs elapsed)", label, attempt, time.time() - start)
            except requests.exceptions.Timeout:
                logger.debug("[Health]%s Timeout on attempt=%d", label, attempt)
            except Exception as exc:
                logger.debug("[Health]%s Probe error attempt=%d: %s", label, attempt, exc)

            time.sleep(interval)

        logger.warning(
            "[Health]%s %s not healthy after %ds (%d attempts) — deployment degraded",
            label, url, timeout, attempt,
        )
        return False

    @staticmethod
    def get_container_logs(container_name: str, tail: int = 80) -> str:
        """
        Fetch the last `tail` lines of logs from a named container.
        Returns empty string on any failure. Never raises.
        """
        try:
            client = docker.from_env()
            full_name = f"container-{container_name}" if not container_name.startswith("container-") else container_name
            try:
                container = client.containers.get(full_name)
            except docker.errors.NotFound:
                container = client.containers.get(container_name)
            return container.logs(tail=tail).decode("utf-8", errors="ignore")
        except Exception as exc:
            logger.debug("[Container] get_container_logs failed for %s: %s", container_name, exc)
            return ""

    @staticmethod
    def diagnose_container_crash(
        container_name: str,
        deployment_id: str = "",
    ) -> dict:
        """
        Inspect a container after a failed health check to determine:
        - Did the container crash (exit) vs is it still starting slowly?
        - What was the exact crash reason?

        Returns:
        {
            "crash_detected": bool,        # True if container has exited
            "exit_code": int | None,       # Container exit code
            "crash_reason": str,           # Human-readable reason
            "crash_category": str,         # "import_error" | "db_error" | "port_error" | "oom" | "unknown"
            "last_logs": str,              # Last 50 log lines
            "diagnosis": str,             # Summary for deployment log
        }
        Never raises.
        """
        result = {
            "crash_detected": False,
            "exit_code": None,
            "crash_reason": "Unknown",
            "crash_category": "unknown",
            "last_logs": "",
            "diagnosis": "",
        }

        try:
            client = docker.from_env()
            full_name = (
                f"container-{container_name}"
                if not container_name.startswith("container-")
                else container_name
            )

            try:
                container = client.containers.get(full_name)
            except docker.errors.NotFound:
                try:
                    container = client.containers.get(container_name)
                except docker.errors.NotFound:
                    result["diagnosis"] = f"Container '{full_name}' not found"
                    return result

            container.reload()
            status    = container.status         # "running", "exited", "created", etc.
            exit_code = None

            if status == "exited":
                result["crash_detected"] = True
                try:
                    exit_code = container.attrs["State"].get("ExitCode")
                    result["exit_code"] = exit_code
                except Exception:
                    pass

            # Always grab logs — even running containers may have error output
            try:
                raw_logs = container.logs(tail=80).decode("utf-8", errors="ignore")
                result["last_logs"] = raw_logs
            except Exception:
                raw_logs = ""

            # ── Pattern-match crash reasons ────────────────────────────────
            log_lower = raw_logs.lower()
            lines = raw_logs.strip().splitlines()

            crash_patterns = [
                # Python import errors
                ("ModuleNotFoundError",        "import_error",  "Missing Python module"),
                ("ImportError",                "import_error",  "Python import failure"),
                ("No module named",            "import_error",  "Missing Python module"),
                # Database connectivity
                ("could not connect to server","db_error",      "PostgreSQL connection refused"),
                ("connection refused",         "db_error",      "Database connection refused"),
                ("OperationalError",           "db_error",      "Database operational error"),
                ("password authentication failed","db_error",   "Database auth failure"),
                ("could not translate host",   "db_error",      "Database host not found"),
                ("FATAL:  database",           "db_error",      "Database fatal error"),
                # Port / binding
                ("address already in use",     "port_error",    "Port already in use"),
                ("bind: address already",      "port_error",    "Port bind failure"),
                # Memory
                ("out of memory",              "oom",           "Out of memory"),
                ("killed",                     "oom",           "Process killed (OOM or signal)"),
                # Node.js
                ("cannot find module",         "import_error",  "Missing npm module"),
                ("module not found",           "import_error",  "Missing npm module"),
                # Config
                ("syntaxerror",                "config_error",  "Syntax error in code"),
                ("typeerror",                  "config_error",  "TypeError at startup"),
                ("keyerror",                   "config_error",  "Missing config key"),
                ("valueerror",                 "config_error",  "Invalid configuration value"),
                # Environment
                ("permission denied",          "permission",    "Permission denied"),
                ("no such file or directory",  "file_error",    "File not found at startup"),
            ]

            for pattern, category, description in crash_patterns:
                if pattern.lower() in log_lower:
                    result["crash_category"] = category
                    result["crash_reason"]    = description
                    # Extract the actual error line for precision
                    for line in lines:
                        if pattern.lower() in line.lower():
                            result["crash_reason"] = f"{description}: {line.strip()[:200]}"
                            break
                    break

            # Build diagnosis summary
            status_str = f"exited(code={exit_code})" if result["crash_detected"] else f"status={status}"
            result["diagnosis"] = (
                f"Container {status_str} | {result['crash_category']}: {result['crash_reason']}"
            )

            # Log to deployment
            if deployment_id:
                from app.services.execution_engine import _append_log
                try:
                    if result["crash_detected"]:
                        _append_log(deployment_id, f"[Health][CRASH] {result['diagnosis']}")
                        if raw_logs:
                            # Log last 15 lines to deployment log
                            for log_line in lines[-15:]:
                                if log_line.strip():
                                    _append_log(deployment_id, f"[Runtime] {log_line.rstrip()}")
                    else:
                        _append_log(deployment_id, f"[Health] Container still running (slow startup?) — {result['diagnosis']}")
                except Exception:
                    pass

            logger.info("[Diagnose] %s: %s", container_name, result["diagnosis"])

        except Exception as exc:
            logger.error("[Diagnose] Failed for %s: %s", container_name, exc)
            result["diagnosis"] = f"Diagnosis failed: {exc}"

        return result


    @classmethod
    def cleanup_orphaned_containers(cls, deployment_prefix: str) -> list[str]:
        """
        Remove all containers whose name starts with 'container-{deployment_prefix}'.
        Used for cleaning up failed/partial deployments before retry.
        """
        try:
            client = docker.from_env()
            removed = []
            for container in client.containers.list(all=True):
                if container.name.startswith(f"container-{deployment_prefix}"):
                    logger.info("[Cleanup] Removing orphaned container: %s", container.name)
                    try:
                        container.stop(timeout=3)
                    except Exception:
                        pass
                    try:
                        container.remove(force=True)
                        removed.append(container.name)
                    except Exception as exc:
                        logger.warning("[Cleanup] Could not remove %s: %s", container.name, exc)
            return removed
        except Exception as exc:
            logger.error("[Cleanup] Orphan cleanup failed: %s", exc)
            return []

    # ── Instance methods (need Docker client) ─────────────────────────────────

    def __init__(self):
        self.client = docker.from_env()

    def _find_deployment_containers(self, deployment_id: str) -> list:
        """Return all containers belonging to this deployment_id."""
        try:
            all_containers = self.client.containers.list(all=True)
            return [
                c for c in all_containers
                if c.name.startswith(f"container-{deployment_id}")
            ]
        except Exception as exc:
            logger.error("[Lifecycle] Cannot list containers: %s", exc)
            return []

    def restart_containers_by_deployment(self, deployment_id: str) -> dict:
        """Restart all containers for a deployment."""
        try:
            containers = self._find_deployment_containers(deployment_id)
            if not containers:
                return {"success": False, "error": "No containers found for deployment"}
            restarted = []
            for container in containers:
                logger.info("[Lifecycle] Restarting %s", container.name)
                container.restart()
                restarted.append(container.name)
            return {"success": True, "restarted": restarted}
        except Exception as exc:
            logger.error("[Lifecycle] restart failed: %s", exc)
            return {"success": False, "error": str(exc)}

    def stop_containers_by_deployment(self, deployment_id: str) -> dict:
        """Stop all containers for a deployment."""
        try:
            containers = self._find_deployment_containers(deployment_id)
            stopped = []
            for container in containers:
                logger.info("[Lifecycle] Stopping %s", container.name)
                try:
                    container.stop(timeout=10)
                    stopped.append(container.name)
                except Exception as exc:
                    logger.warning("[Lifecycle] Could not stop %s: %s", container.name, exc)
            return {"success": True, "stopped": stopped}
        except Exception as exc:
            logger.error("[Lifecycle] stop failed: %s", exc)
            return {"success": False, "error": str(exc)}

    def delete_deployment_resources(self, deployment_id: str) -> dict:
        """Stop + remove all containers and images for a deployment."""
        try:
            containers = self._find_deployment_containers(deployment_id)
            removed = []

            for container in containers:
                logger.info("[Lifecycle] Removing container %s", container.name)
                try:
                    container.stop(timeout=5)
                except Exception:
                    pass
                try:
                    container.remove(force=True)
                    removed.append(container.name)
                except Exception as exc:
                    logger.warning("[Lifecycle] Container removal failed: %s", exc)

            # Remove associated images
            try:
                for image in self.client.images.list():
                    for tag in image.tags:
                        if f"anti-gravity-{deployment_id}" in tag:
                            logger.info("[Lifecycle] Removing image %s", tag)
                            try:
                                self.client.images.remove(tag, force=True)
                            except Exception as exc:
                                logger.warning("[Lifecycle] Image removal failed %s: %s", tag, exc)
            except Exception as exc:
                logger.warning("[Lifecycle] Image listing failed: %s", exc)

            return {"success": True, "removed": removed}
        except Exception as exc:
            logger.error("[Lifecycle] delete failed: %s", exc)
            return {"success": False, "error": str(exc)}