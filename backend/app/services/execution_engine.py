from pathlib import Path
import docker
DEPLOYMENT_LOGS = {}


class ExecutionEngine:

    @staticmethod
    def generate_dockerfile(
        service: dict,
    ):

        runtime = (
            service["runtime"]
            .lower()
        )

        working_dir = (
            service["working_directory"]
        )

        install_command = (
            service["install_command"]
        )

        start_command = (
            service["start_command"]
        )

        if runtime == "nodejs":

            base_image = "node:22"

            expose_port = 3000

        elif runtime == "python":

            base_image = "python:3.12"

            expose_port = 8000

        else:

            raise ValueError(
                f"Unsupported runtime: {runtime}"
            )

        dockerfile = f"""
FROM {base_image}

WORKDIR /app/{working_dir}

COPY . .

RUN {install_command}

EXPOSE {expose_port}

CMD {ExecutionEngine.shell_to_cmd(start_command)}
"""

        return dockerfile

    @staticmethod
    def shell_to_cmd(
        command: str,
    ):

        parts = command.split()

        quoted = [
            f'"{part}"'
            for part in parts
        ]

        return f"[{', '.join(quoted)}]"

    @staticmethod
    def save_dockerfile(
        project_root: str,
        dockerfile_content: str,
    ):

        dockerfile_path = (
            Path(project_root)
            / "Dockerfile"
        )

        dockerfile_path.write_text(
            dockerfile_content,
            encoding="utf-8",
        )

        return dockerfile_path

    @staticmethod
    def build_image(
            project_root: str,
            deployment_id: str,
    ):

        client = docker.from_env()

        image_tag = (
            f"anti-gravity-{deployment_id}"
        )

        image, logs = client.images.build(
            path=project_root,
            tag=image_tag,
        )

        log_lines = []

        for log in logs:

            if "stream" in log:
                line = log["stream"].strip()

                print(line)

                log_lines.append(line)

        DEPLOYMENT_LOGS[
            deployment_id
        ] = log_lines

        return image_tag

    @staticmethod
    def run_container(
            image_tag: str,
            deployment_id: str,
            port: int = 3000,
    ):

        client = docker.from_env()

        container = client.containers.run(
            image_tag,
            detach=True,
            name=f"container-{deployment_id}",
            ports={
                f"{port}/tcp": None
            },
        )

        return container