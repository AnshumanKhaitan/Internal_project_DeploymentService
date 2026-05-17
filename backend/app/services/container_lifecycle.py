import docker
import logging


logger = logging.getLogger(__name__)


class ContainerLifecycleService:
    def __init__(self):
        self.client = docker.from_env()

    def stop_container(
        self,
        container_name: str,
    ):
        """
        Stop running deployment container.
        """

        try:
            container = self.client.containers.get(container_name)

            container.stop()

            logger.info(
                "Container stopped: %s",
                container_name,
            )

            return {
                "success": True,
                "container_name": container_name,
                "status": "stopped",
            }

        except Exception as e:
            logger.exception("Failed to stop container")

            return {
                "success": False,
                "error": str(e),
            }