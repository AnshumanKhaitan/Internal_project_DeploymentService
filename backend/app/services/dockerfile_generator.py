from pathlib import Path


class DockerfileGenerator:
    @staticmethod
    def generate(runtime: str) -> str:
        """
        Generate Dockerfile content based on runtime.
        """

        runtime = runtime.lower()

        if runtime == "nodejs":
            return """FROM node:22

WORKDIR /app

COPY . .

RUN npm install

EXPOSE 3000

CMD ["npm", "start"]
"""

        elif runtime == "python":
            return """FROM python:3.12

WORKDIR /app

COPY . .

RUN pip install -r requirements.txt

EXPOSE 8000

CMD ["python", "app.py"]
"""

        raise ValueError(f"Unsupported runtime: {runtime}")

    @staticmethod
    def save(dockerfile_content: str, deployment_path: str):
        """
        Save generated Dockerfile into deployment workspace.
        """

        dockerfile_path = Path(deployment_path) / "Dockerfile"

        with open(dockerfile_path, "w", encoding="utf-8") as f:
            f.write(dockerfile_content)

        return str(dockerfile_path)