import docker
import logging


logger = logging.getLogger(__name__)


class ContainerLogsService:
    def __init__(self):
        self.client = docker.from_env()

    def get_logs(
        self,
        container_name: str,
        tail: int = 100,
    ):
        """
        Fetch container logs.
        """

        try:
            container = self.client.containers.get(container_name)

            logs = container.logs(
                tail=tail,
                timestamps=True,
            ).decode("utf-8")

            return {
                "success": True,
                "container_name": container.name,
                "logs": logs.splitlines(),
            }

        except Exception as e:
            logger.exception("Failed to fetch container logs")

            return {
                "success": False,
                "error": str(e),
            }