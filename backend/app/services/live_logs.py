import asyncio
import json
import docker

from app.models.schemas import DeploymentEvent


class LiveLogsService:
    def __init__(self):
        self.client = docker.from_env()

    async def stream_logs(
        self,
        deployment_id: str,
    ):
        container_name = f"container-{deployment_id}"

        container = self.client.containers.get(
            container_name
        )

        for log in container.logs(
            stream=True,
            follow=True,
        ):
            event = DeploymentEvent(
                event_type="log",
                deployment_id=deployment_id,
                data={
                    "message": log.decode().strip()
                },
            )

            yield f"data: {json.dumps(event.model_dump())}\n\n"

            await asyncio.sleep(0.01)