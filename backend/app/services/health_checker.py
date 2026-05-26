import requests
import time
import logging


logger = logging.getLogger(__name__)


class DeploymentHealthChecker:
    @staticmethod
    def wait_until_healthy(
        port: int,
        timeout: int = 30,
    ):
        """
        Wait until deployed application becomes healthy.
        """

        url = f"http://localhost:{port}"

        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                response = requests.get(url)

                if response.status_code == 200:
                    logger.info(
                        "Deployment healthy on port %s",
                        port,
                    )

                    return {
                        "healthy": True,
                        "url": url,
                        "status_code": response.status_code,
                    }

            except Exception:
                pass

            time.sleep(2)

        logger.error(
            "Deployment health check failed on port %s",
            port,
        )

        return {
            "healthy": False,
            "url": url,
        }