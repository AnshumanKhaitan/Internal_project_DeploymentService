"""
Anti Gravity Deployments — Container Lifecycle Service

Manages Docker container creation, health checks, log streaming,
restart, stop, and cleanup operations.
"""

import logging
import re
import threading
import time

import docker
import requests

logger = logging.getLogger(__name__)


class ContainerLifecycleService:

    # ── Static / class methods (used without an instance) ────────────────────

    @classmethod
    def run_container(
        cls,
        image_tag: str,
        container_name: str,
        service: dict,
    ) -> dict:
        """
        Start a container, removing any existing container with the same name first.

        Returns {"container": <Container>, "host_port": <str>}.
        Raises on failure.
        """
        client = docker.from_env()
        runtime = str(service.get("runtime", "node")).lower()
        runtime_port = 8000 if runtime == "python" else 3000
        full_name = f"container-{container_name}"

        # ── Stale container cleanup ──────────────────────────────────────────
        cls._remove_existing_container(client, full_name)

        logger.info(
            "[Container] Starting '%s' from image '%s' (port=%d)",
            full_name,
            image_tag,
            runtime_port,
        )

        container = client.containers.run(
            image=image_tag,
            detach=True,
            ports={f"{runtime_port}/tcp": None},
            name=full_name,
        )

        container.reload()

        # Stream logs in background
        cls.stream_container_logs(container, container_name)

        ports = container.attrs["NetworkSettings"]["Ports"]
        logger.debug("[Container] Port mapping: %s", ports)

        port_data = ports.get(f"{runtime_port}/tcp")
        if not port_data:
            raise RuntimeError(
                f"No host port mapping for {full_name} on {runtime_port}/tcp. "
                f"Container may have exited immediately — check logs."
            )

        host_port = port_data[0]["HostPort"]
        logger.info(
            "[Container] '%s' started — container_id=%s host_port=%s",
            full_name,
            container.id[:12],
            host_port,
        )

        return {"container": container, "host_port": host_port}

    @staticmethod
    def _remove_existing_container(client, name: str) -> None:
        """Remove an existing container with the given name (idempotent)."""
        try:
            existing = client.containers.get(name)
            logger.info("[Container] Removing existing container '%s'", name)
            try:
                existing.stop(timeout=5)
            except Exception:
                pass
            existing.remove(force=True)
            logger.info("[Container] Removed existing container '%s'", name)
        except docker.errors.NotFound:
            pass  # Nothing to remove
        except Exception as exc:
            logger.warning("[Container] Could not remove existing '%s': %s", name, exc)

    @classmethod
    def stream_container_logs(
        cls,
        container,
        deployment_id: str,
    ) -> None:
        """Start a daemon thread that streams container logs into DEPLOYMENT_LOGS."""

        def _stream():
            try:
                from app.services.execution_engine import _append_log  # avoid circular at module level
                for raw_line in container.logs(stream=True, follow=True):
                    line = raw_line.decode("utf-8", errors="ignore").strip()
                    if line:
                        _append_log(deployment_id, line)
                        logger.debug("[ContainerLog][%s] %s", deployment_id, line)
            except Exception as exc:
                logger.warning("[ContainerLog][%s] Stream error: %s", deployment_id, exc)

        threading.Thread(target=_stream, daemon=True, name=f"logs-{deployment_id}").start()

    @classmethod
    def wait_for_health(
        cls,
        url: str,
        timeout: int = 90,
        interval: int = 3,
    ) -> bool:
        """
        Poll the given URL until it returns a non-5xx status.

        Returns True if healthy within timeout, False otherwise.
        Never raises.
        """
        logger.info("[Health] Waiting for %s (timeout=%ds, interval=%ds)", url, timeout, interval)
        start = time.time()
        attempt = 0

        while time.time() - start < timeout:
            attempt += 1
            try:
                resp = requests.get(url, timeout=5, allow_redirects=True)
                if resp.status_code < 500:
                    logger.info(
                        "[Health] %s healthy after %.1fs (attempt %d, status=%d)",
                        url,
                        time.time() - start,
                        attempt,
                        resp.status_code,
                    )
                    return True
            except requests.exceptions.ConnectionError:
                pass  # Container still starting
            except requests.exceptions.Timeout:
                pass  # Slow startup
            except Exception as exc:
                logger.debug("[Health] Unexpected probe error: %s", exc)

            time.sleep(interval)

        logger.warning(
            "[Health] %s did not become healthy within %ds (%d attempts)",
            url,
            timeout,
            attempt,
        )
        return False

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
                container.stop(timeout=10)
                stopped.append(container.name)
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
                container.remove(force=True)
                removed.append(container.name)

            # Remove images
            images = self.client.images.list()
            for image in images:
                for tag in image.tags:
                    if f"anti-gravity-{deployment_id}" in tag:
                        logger.info("[Lifecycle] Removing image %s", tag)
                        try:
                            self.client.images.remove(tag, force=True)
                        except Exception as exc:
                            logger.warning("[Lifecycle] Image removal failed: %s", exc)

            return {"success": True, "removed": removed}
        except Exception as exc:
            logger.error("[Lifecycle] delete failed: %s", exc)
            return {"success": False, "error": str(exc)}