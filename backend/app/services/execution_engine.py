"""
Anti Gravity Deployments — Execution Engine

Handles Dockerfile generation, image builds, and log collection.
"""

import logging
from pathlib import Path

import docker

logger = logging.getLogger(__name__)

DEPLOYMENT_LOGS: dict[str, list[str]] = {}


def _append_log(deployment_id: str, message: str) -> None:
    """Thread-safe log append (GIL protects list.append)."""
    if deployment_id not in DEPLOYMENT_LOGS:
        DEPLOYMENT_LOGS[deployment_id] = []
    DEPLOYMENT_LOGS[deployment_id].append(message)


class ExecutionEngine:

    @classmethod
    def append_log(cls, deployment_id: str, message: str) -> None:
        _append_log(deployment_id, message)
        logger.debug("[Logs][%s] %s", deployment_id, message)

    # ── Dockerfile generation ─────────────────────────────────────────────────

    @staticmethod
    def generate_dockerfile(service: dict) -> str:
        """
        Generate a Dockerfile for the given service descriptor.

        Handles node and python runtimes.  Unknown runtimes fall back
        to node:22 rather than raising so deployments don't crash.
        """
        runtime = str(service.get("runtime", "node")).lower().strip()
        working_dir = str(service.get("working_directory", ".")).strip() or "."
        install_command = str(service.get("install_command", "")).strip()
        start_command = str(service.get("start_command", "")).strip()

        # ── Runtime-specific defaults ────────────────────────────────────────
        if runtime in ("node", "nodejs"):
            base_image = "node:20-alpine"
            expose_port = 3000
            if not install_command:
                install_command = "npm install"
            if not start_command:
                start_command = "npm start"
            # For Next.js we need to make sure host binding works
            # Override PORT env so Next.js / Vite bind to 0.0.0.0
            env_block = "ENV PORT=3000\nENV HOSTNAME=0.0.0.0\n"

        elif runtime == "python":
            base_image = "python:3.11-slim"
            expose_port = 8000
            if not install_command:
                install_command = "pip install -r requirements.txt"
            if not start_command:
                start_command = "python main.py"
            env_block = "ENV PYTHONUNBUFFERED=1\n"

        else:
            # Safe fallback — unknown runtime treated as Node
            logger.warning(
                "[Dockerfile] Unknown runtime '%s', defaulting to node:20-alpine", runtime
            )
            base_image = "node:20-alpine"
            expose_port = 3000
            if not install_command:
                install_command = "npm install"
            if not start_command:
                start_command = "npm start"
            env_block = "ENV PORT=3000\nENV HOSTNAME=0.0.0.0\n"

        install_line = f"RUN {install_command}" if install_command else "# no install step"

        dockerfile = f"""FROM {base_image}

WORKDIR /app

{env_block}
COPY . .

{install_line}

EXPOSE {expose_port}

CMD {ExecutionEngine.shell_to_cmd(start_command)}
"""
        logger.info(
            "[Dockerfile] Generated for runtime=%s expose=%d start='%s'",
            runtime,
            expose_port,
            start_command,
        )
        return dockerfile

    @staticmethod
    def shell_to_cmd(command: str) -> str:
        """Convert a shell command string to JSON-array Docker CMD format."""
        if not command:
            return '["sh", "-c", "echo No start command defined"]'
        parts = command.split()
        quoted = [f'"{part}"' for part in parts]
        return f"[{', '.join(quoted)}]"

    @staticmethod
    def save_dockerfile(project_root: str, dockerfile_content: str) -> Path:
        """Write Dockerfile to the project root directory."""
        dockerfile_path = Path(project_root) / "Dockerfile"
        dockerfile_path.write_text(dockerfile_content, encoding="utf-8")
        logger.info("[Dockerfile] Saved to %s", dockerfile_path)
        return dockerfile_path

    # ── Image build ───────────────────────────────────────────────────────────

    @staticmethod
    def build_image(project_root: str, deployment_id: str) -> str:
        """
        Build a Docker image from the project root.

        Returns the image tag on success, raises on failure.
        Build logs are appended to DEPLOYMENT_LOGS keyed by the
        base deployment ID (without service suffix).
        """
        client = docker.from_env()
        image_tag = f"anti-gravity-{deployment_id}"

        logger.info(
            "[Build] Starting image build tag=%s root=%s", image_tag, project_root
        )
        _append_log(deployment_id, f"[Build] Building image: {image_tag}")

        image, logs = client.images.build(
            path=project_root,
            tag=image_tag,
            rm=True,
            forcerm=True,
        )

        # Collect and stream build logs
        log_lines: list[str] = []
        for log in logs:
            if "stream" in log:
                line = log["stream"].strip()
                if line:
                    log_lines.append(line)
                    logger.debug("[Build][%s] %s", image_tag, line)

        # Key logs under the base deployment ID
        base_id = deployment_id.split("-backend")[0].rsplit("-", 1)[0]
        if base_id not in DEPLOYMENT_LOGS:
            DEPLOYMENT_LOGS[base_id] = []
        DEPLOYMENT_LOGS[base_id].extend(log_lines)

        logger.info(
            "[Build] Image %s built successfully (%d log lines)", image_tag, len(log_lines)
        )
        return image_tag

    # ── Container run ─────────────────────────────────────────────────────────

    @classmethod
    def run_container(
        cls,
        image_tag: str,
        container_name: str,
        service: dict,
    ) -> dict:
        """
        Run a container from the given image.

        Returns {"container": <Container>, "host_port": <str>}.
        Raises on failure.
        """
        from app.services.container_lifecycle import ContainerLifecycleService  # noqa: avoid circular

        client = docker.from_env()
        runtime = str(service.get("runtime", "node")).lower()
        runtime_port = 8000 if runtime == "python" else 3000

        logger.info(
            "[Container] Running %s from image %s (container_port=%d)",
            container_name,
            image_tag,
            runtime_port,
        )

        container = client.containers.run(
            image=image_tag,
            detach=True,
            ports={f"{runtime_port}/tcp": None},
            name=f"container-{container_name}",
        )

        container.reload()

        # Stream logs in background thread
        ContainerLifecycleService.stream_container_logs(
            container=container,
            deployment_id=container_name,
        )

        ports = container.attrs["NetworkSettings"]["Ports"]
        port_data = ports.get(f"{runtime_port}/tcp")

        if not port_data:
            raise RuntimeError(
                f"No port mapping found for container {container_name} "
                f"(expected {runtime_port}/tcp)"
            )

        host_port = port_data[0]["HostPort"]
        logger.info(
            "[Container] %s started, host_port=%s container_id=%s",
            container_name,
            host_port,
            container.id[:12],
        )

        return {"container": container, "host_port": host_port}