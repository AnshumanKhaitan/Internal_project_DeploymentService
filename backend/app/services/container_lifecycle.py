import docker
import logging
import shutil


logger = logging.getLogger(__name__)


class ContainerLifecycleService:
    def __init__(self):
        self.client = docker.from_env()

    def restart_containers_by_deployment(
            self,
            deployment_id: str,
    ):
        try:

            containers = (
                self.client.containers.list(
                    all=True
                )
            )

            restarted = []

            for container in containers:

                if (
                        container.name.startswith(
                            f"container-{deployment_id}"
                        )
                ):
                    print(
                        "RESTARTING:",
                        container.name,
                    )

                    container.restart()

                    restarted.append(
                        container.name
                    )

            return {
                "success": True,
                "restarted": restarted,
            }

        except Exception as e:

            return {
                "success": False,
                "error": str(e),
            }

    def stop_containers_by_deployment(
            self,
            deployment_id: str,
    ):
        try:

            containers = (
                self.client.containers.list(
                    all=True
                )
            )

            matching = []

            for container in containers:

                if (
                        container.name.startswith(
                            f"container-{deployment_id}"
                        )
                ):
                    matching.append(container)

            for container in matching:
                print(
                    "STOPPING:",
                    container.name,
                )

                container.stop()

            return {
                "success": True,
                "stopped": [
                    c.name
                    for c in matching
                ],
            }

        except Exception as e:

            return {
                "success": False,
                "error": str(e),
            }

    def delete_deployment_resources(
            self,
            deployment_id: str,
    ):
        try:

            containers = (
                self.client.containers.list(
                    all=True
                )
            )

            removed = []

            for container in containers:

                if (
                        container.name.startswith(
                            f"container-{deployment_id}"
                        )
                ):

                    print(
                        "REMOVING CONTAINER:",
                        container.name,
                    )

                    try:
                        container.stop()
                    except:
                        pass

                    container.remove(
                        force=True
                    )

                    removed.append(
                        container.name
                    )

            images = self.client.images.list()

            for image in images:

                tags = image.tags

                for tag in tags:

                    if (
                            f"anti-gravity-{deployment_id}"
                            in tag
                    ):

                        print(
                            "REMOVING IMAGE:",
                            tag,
                        )

                        try:

                            self.client.images.remove(
                                tag,
                                force=True,
                            )

                        except Exception as e:

                            print(
                                "IMAGE REMOVE ERROR:",
                                e,
                            )

            return {
                "success": True,
                "removed": removed,
            }

        except Exception as e:

            return {
                "success": False,
                "error": str(e),
            }