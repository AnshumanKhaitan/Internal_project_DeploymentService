"""
Docker client helpers — connectivity checks and clear errors when the daemon
or Unix socket is unavailable (common for nested/self-hosted deployments).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import docker
from docker import DockerClient

_DOCKER_SOCK = "/var/run/docker.sock"


def docker_socket_path() -> str:
    return os.environ.get("DOCKER_HOST", _DOCKER_SOCK).removeprefix("unix://")


def docker_socket_available() -> bool:
    """Return True if the Docker Unix socket exists at the expected path."""
    if os.name == "nt":
        # On Windows host, docker uses a named pipe by default if DOCKER_HOST isn't set.
        # If it matches the default unix socket path, bypass the file check.
        path = docker_socket_path()
        if path == _DOCKER_SOCK:
            return True
    path = docker_socket_path()
    if not path.startswith("/"):
        return True
    return Path(path).exists()


def get_docker_client() -> DockerClient:
    """
    Return a Docker client, raising a clear error if the daemon/socket is missing.
    """
    if not docker_socket_available():
        raise RuntimeError(
            "Docker is not available: "
            f"{docker_socket_path()} was not found. "
            "Start the Docker daemon on the host, or run the deployment backend "
            "with /var/run/docker.sock mounted (see docker-compose.yml). "
            "Nested deployments of this platform require the Docker socket on the "
            "backend container."
        )
    try:
        client = docker.from_env()
        client.ping()
        return client
    except Exception as exc:
        raise RuntimeError(
            "Cannot connect to Docker. Ensure the daemon is running and the backend "
            f"can access {docker_socket_path()}. "
            f"Original error: {exc}"
        ) from exc


def service_needs_docker_socket(service: dict, project_root: str | None = None) -> bool:
    """
    True when a deployed service must orchestrate builds (e.g. this platform's API).
    """
    if service.get("mount_docker_socket"):
        return True

    runtime = str(service.get("runtime", "")).lower()
    if runtime not in ("python", "fastapi"):
        return False

    root = Path(project_root) if project_root else None
    if root and root.is_dir():
        req = root / "requirements.txt"
        if req.is_file():
            text = req.read_text(encoding="utf-8", errors="ignore").lower()
            if re.search(r"(^|\n)\s*docker[>=\s]", text):
                return True
        if (root / "app" / "services" / "execution_engine.py").is_file():
            return True

    return False


def docker_socket_volumes() -> dict[str, dict[str, str]]:
    """Volume binds required for Docker-in-Docker style orchestration."""
    sock = docker_socket_path()
    return {sock: {"bind": sock, "mode": "rw"}}
