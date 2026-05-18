from pathlib import Path
import yaml


TRAEFIK_DYNAMIC_CONFIG = Path("C:/traefik/dynamic.yml")


class TraefikService:
    @staticmethod
    def register_deployment_route(
        deployment_id: str,
        assigned_port: int,
    ):
        """
        Dynamically register deployment route in Traefik.
        """

        route_name = f"deployment-{deployment_id}"

        config = {
            "http": {
                "routers": {
                    route_name: {
                        "rule": f"PathPrefix(`/deployments/{deployment_id}`)",
                        "service": route_name,
                        "middlewares": [
                            f"{route_name}-strip"
                        ],
                    }
                },
                "middlewares": {
                    f"{route_name}-strip": {
                        "stripPrefix": {
                            "prefixes": [
                                f"/deployments/{deployment_id}"
                            ]
                        }
                    }
                },
                "services": {
                    route_name: {
                        "loadBalancer": {
                            "servers": [
                                {
                                    "url": f"http://host.docker.internal:{assigned_port}"
                                }
                            ]
                        }
                    }
                },
            }
        }

        with open(TRAEFIK_DYNAMIC_CONFIG, "w") as f:
            yaml.dump(config, f)

        return {
            "success": True,
            "route": f"/deployments/{deployment_id}",
        }