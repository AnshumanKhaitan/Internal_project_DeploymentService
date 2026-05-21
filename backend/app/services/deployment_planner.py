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
            runtime: str,
            framework: str,
            entry_points: list,
    ):

        prompt = f"""
You are a deployment planning engine.

Your task is to analyze project manifest files and return a deployment plan.

Return ONLY valid JSON.

Expected format:

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

Rules:

- Always return valid JSON
- Never include markdown
- Never include explanations
- Never include comments
- Never include text outside JSON
- Always include:
    - runtime
    - working_directory
    - install_command
    - start_command

Framework Rules:

- If Next.js detected:
    start_command = "npm run dev"

- If Vite detected:
    start_command = "npm run dev"

- If Express detected:
    start_command = "npm start"

Detected Runtime:
{runtime}

Detected Framework:
{framework}

Detected Entry Points:
{json.dumps(entry_points, indent=2)}

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

            print(
                "\nCLEANED OUTPUT:\n",
                cleaned_output,
            )

            # Deterministic fallback plan

            fallback_service = {
                "runtime": runtime,
                "working_directory": ".",
            }

            # Node.js defaults
            if runtime == "nodejs":

                fallback_service[
                    "install_command"
                ] = "npm install"

                if framework in [
                    "nextjs",
                    "vite",
                ]:

                    fallback_service[
                        "start_command"
                    ] = "npm run dev"

                elif entry_points:

                    fallback_service[
                        "start_command"
                    ] = (
                        f"node {entry_points[0]}"
                    )

                else:

                    fallback_service[
                        "start_command"
                    ] = "npm start"

            # Python defaults
            elif runtime == "python":

                fallback_service[
                    "install_command"
                ] = (
                    "pip install -r requirements.txt"
                )

                fallback_service[
                    "start_command"
                ] = (
                    "uvicorn app.main:app "
                    "--host 0.0.0.0 "
                    "--port 8000"
                )

            deployment_plan = json.loads(
                cleaned_output
            )

            # If model returns array directly
            if isinstance(
                    deployment_plan,
                    list
            ):
                deployment_plan = {
                    "services":
                        deployment_plan
                }

            # Safety validation
            if "services" not in deployment_plan:

                raise Exception(
                    "Deployment plan missing services key"
                )

            if (
                    runtime == "python"
                    and not deployment_plan["services"]
            ):
                deployment_plan = {
                    "services": [
                        {
                            "runtime": "python",
                            "working_directory": ".",
                            "install_command":
                                "pip install -r requirements.txt",
                            "start_command":
                                "python main.py",
                        }
                    ]
                }

            if (
                    runtime == "node"
                    and not deployment_plan["services"]
            ):
                deployment_plan = {
                    "services": [
                        {
                            "runtime": "node",
                            "working_directory": ".",
                            "install_command":
                                "npm install",
                            "start_command":
                                "npm start",
                        }
                    ]
                }

            # Normalize services
            normalized_services = []

            for service in deployment_plan["services"]:

                runtime = (
                    service.get(
                        "runtime",
                        "nodejs"
                    )
                    .lower()
                )

                if runtime == "node":
                    runtime = "nodejs"

                working_directory = (
                    service.get(
                        "working_directory",
                        "."
                    )
                    .strip()
                )

                install_command = service.get(
                    "install_command"
                )

                start_command = service.get(
                    "start_command"
                )

                # Defaults for Node.js
                if runtime == "nodejs":

                    if not install_command:
                        install_command = (
                            "npm install"
                        )

                    if not start_command:
                        start_command = (
                            "npm start"
                        )

                # Defaults for Python
                elif runtime == "python":

                    if not install_command:
                        install_command = (
                            "pip install -r requirements.txt"
                        )

                    if not start_command:
                        start_command = (
                            "uvicorn app.main:app "
                            "--host 0.0.0.0 "
                            "--port 8000"
                        )

                normalized_service = {
                    "runtime":
                        runtime,

                    "working_directory":
                        working_directory,

                    "install_command":
                        install_command,

                    "start_command":
                        start_command,
                }

                normalized_services.append(
                    normalized_service
                )

            deployment_plan = {
                "services":
                    normalized_services
            }

            print(
                "\nDEPLOYMENT PLAN:\n",
                deployment_plan,
            )

            return deployment_plan

        except Exception as e:

            print(
                "\nPLANNER ERROR:\n",
                str(e),
            )

            print(
                "\nRAW OUTPUT:\n",
                raw_output,
            )

            return {
                "services": [
                    fallback_service
                ]
            }