import docker
import logging
import shutil


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

    def delete_deployment_resources(
        self,
        deployment_id: str,
        image_name: str,
        workspace_path: str,
    ):
        """
        Fully clean deployment resources.
        """

        container_name = f"container-{deployment_id}".lower()

        try:
            # ── Remove container ─────────────────────────

            try:
                container = self.client.containers.get(container_name)

                try:
                    container.stop()
                except Exception:
                    pass

                container.remove(force=True)

                logger.info(
                    "Container removed: %s",
                    container_name,
                )

            except Exception:
                logger.warning(
                    "Container not found: %s",
                    container_name,
                )

            # ── Remove image ─────────────────────────────

            try:
                self.client.images.remove(
                    image=image_name,
                    force=True,
                )

                logger.info(
                    "Image removed: %s",
                    image_name,
                )

            except Exception:
                logger.warning(
                    "Image not found: %s",
                    image_name,
                )

            # ── Remove workspace ─────────────────────────

            shutil.rmtree(
                workspace_path,
                ignore_errors=True,
            )

            logger.info(
                "Workspace removed: %s",
                workspace_path,
            )

            return {
                "success": True,
                "deployment_id": deployment_id,
                "status": "deleted",
            }

        except Exception as e:
            logger.exception("Deployment cleanup failed")

            return {
                "success": False,
                "error": str(e),
            }