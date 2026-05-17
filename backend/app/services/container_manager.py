import docker
import logging


logger = logging.getLogger(__name__)


class ContainerManager:
    def __init__(self):
        self.client = docker.from_env()

    def create_and_start_container(
        self,
        image_name: str,
        container_name: str,
        internal_port: int = 3000,
    ):
        """
        Create and start container from built image.
        """

        try:
            logger.info(
                "Creating container: %s",
                container_name,
            )

            container = self.client.containers.run(
                image=image_name,
                name=container_name,
                detach=True,
                ports={
                    f"{internal_port}/tcp": None
                },
                mem_limit="512m",
                nano_cpus=500000000,
            )

            container.reload()

            port_bindings = container.attrs["NetworkSettings"]["Ports"]

            assigned_port = None

            if f"{internal_port}/tcp" in port_bindings:
                assigned_port = int(
                    port_bindings[f"{internal_port}/tcp"][0]["HostPort"]
                )

            logger.info(
                "Container started: %s on port %s",
                container.name,
                assigned_port,
            )

            return {
                "success": True,
                "container_id": container.id,
                "container_name": container.name,
                "status": container.status,
                "assigned_port": assigned_port,
            }

        except Exception as e:
            logger.exception("Container startup failed")

            return {
                "success": False,
                "error": str(e),
            }