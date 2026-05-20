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

        if runtime in ["nodejs", "node"]:

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

    @classmethod
    def run_container(
            cls,
            image_tag: str,
            container_name: str,
    ):

        import docker

        client = docker.from_env()

        runtime_port = 3000

        container = client.containers.run(
            image=image_tag,
            detach=True,
            ports={
                f"{runtime_port}/tcp": None
            },
            name=f"container-{container_name}",
        )

        container.reload()

        ports = (
            container.attrs
            ["NetworkSettings"]
            ["Ports"]
        )

        print(
            "\nCONTAINER PORTS:\n",
            ports,
        )

        port_data = ports.get(
            f"{runtime_port}/tcp"
        )

        if not port_data:
            raise Exception(
                "No port mapping found"
            )

        host_port = (
            port_data[0]["HostPort"]
        )

        print(
            "\nHOST PORT:\n",
            host_port,
        )

        return {
            "container": container,
            "host_port": host_port,
        }