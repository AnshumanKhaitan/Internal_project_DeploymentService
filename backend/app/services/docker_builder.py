import docker
import logging
from pathlib import Path


logger = logging.getLogger(__name__)


class DockerImageBuilder:
    def __init__(self):
        self.client = docker.from_env()

    def build_image(
        self,
        deployment_id: str,
        project_path: str,
        image_name: str,
    ):
        """
        Build Docker image from generated Dockerfile.
        """

        try:
            logger.info(
                "Starting Docker image build for %s",
                deployment_id,
            )

            image, build_logs = self.client.images.build(
                path=project_path,
                tag=image_name,
                rm=True,
            )

            parsed_logs = []

            for chunk in build_logs:
                if "stream" in chunk:
                    log_line = chunk["stream"].strip()

                    if log_line:
                        parsed_logs.append(log_line)

                        logger.info(log_line)

            logger.info(
                "Docker image built successfully: %s",
                image_name,
            )

            return {
                "success": True,
                "image_id": image.id,
                "image_tags": image.tags,
                "logs": parsed_logs,
            }

        except docker.errors.BuildError as e:
            logger.exception("Docker build failed")

            return {
                "success": False,
                "error": str(e),
            }

        except Exception as e:
            logger.exception("Unexpected Docker build error")

            return {
                "success": False,
                "error": str(e),
            }