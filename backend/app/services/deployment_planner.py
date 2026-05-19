import json
import requests


class DeploymentPlanner:

    OLLAMA_URL = (
        "http://localhost:11434/api/generate"
    )

    MODEL = "phi3"

    @classmethod
    def plan(
        cls,
        manifests: list,
    ):

        prompt = f"""
        You are a deployment planner.

        Your job is to generate deployment instructions
        ONLY from manifest file names and paths.

        STRICT RULES:

        - package.json means Node.js runtime
        - requirements.txt means Python runtime

        Rules:
        - package.json:
            install_command = npm install
            start_command = npm start

        - requirements.txt:
            install_command = pip install -r requirements.txt

        DO NOT:
        - explain anything
        - add comments
        - add markdown
        - add placeholders
        - add assumptions
        - add extra commands
        - add audit commands

        Return ONLY valid raw JSON.
Do NOT include markdown.
Do NOT include comments.
Do NOT include explanations.
Do NOT wrap response in ```json.

        EXAMPLE OUTPUT:

        {{
          "services": [
            {{
              "runtime": "nodejs",
              "working_directory": ".",
              "install_command": "npm install",
              "start_command": "npm start"
            }}
          ]
        }}

        Manifest Files:
        {json.dumps(manifests, indent=2)}
        """

        response = requests.post(
            cls.OLLAMA_URL,
            json={
                "model": cls.MODEL,
                "prompt": prompt,
                "stream": False,
            },
            timeout=300,
        )

        result = response.json()

        raw_output = result.get(
            "response",
            "{}"
        )

        print(
            "\nLLM RAW OUTPUT:\n",
            raw_output,
        )

        try:

            cleaned_output = (
                raw_output
                .replace("```json", "")
                .replace("```", "")
                .strip()
            )

            lines = cleaned_output.splitlines()

            cleaned_lines = []

            for line in lines:

                if "//" in line:
                    line = line.split("//")[0]

                cleaned_lines.append(line)

            cleaned_output = "\n".join(
                cleaned_lines
            ).strip()

            deployment_plan = json.loads(
                cleaned_output
            )

            if isinstance(
                    deployment_plan,
                    list
            ):
                deployment_plan = {
                    "services":
                        deployment_plan
                }

            if "services" not in deployment_plan:
                deployment_plan = {
                    "services": []
                }

            if "services" not in deployment_plan:
                deployment_plan = {
                    "services": []
                }

            for service in deployment_plan["services"]:

                workdir = (
                    service["working_directory"]
                    .lower()
                )

                if "frontend" in workdir:

                    service["runtime"] = "nodejs"

                    service["install_command"] = (
                        "npm install"
                    )

                    service["start_command"] = (
                        "npm start"
                    )

                    if not service.get(
                            "start_command"
                    ):
                        service["start_command"] = (
                            "npm run dev"
                        )

                if "backend" in workdir:

                    service["runtime"] = "python"

                    service["install_command"] = (
                        "pip install -r requirements.txt"
                    )

                    service["start_command"] = (
                        "uvicorn app.main:app "
                        "--host 0.0.0.0 "
                        "--port 8000"
                    )

                    if not service.get(
                            "start_command"
                    ):
                        service["start_command"] = (
                            "uvicorn app.main:app --host 0.0.0.0 --port 8000"
                        )

            return deployment_plan

        except Exception:

            return {
                "error": "Invalid JSON",
                "raw_output": raw_output,
            }