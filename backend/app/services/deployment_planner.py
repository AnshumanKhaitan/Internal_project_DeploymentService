"""
Anti Gravity Deployments — Deployment Planner

Calls Ollama (phi3) to generate a deployment plan from project manifests.
Falls back deterministically if Ollama is offline or returns malformed output.
"""

import json
import logging
import re
import requests
from pathlib import Path

logger = logging.getLogger(__name__)


# ── Deterministic fallback plans ──────────────────────────────────────────────

def _node_fallback(framework: str) -> dict:
    """Return a safe Node.js deployment plan."""
    start_cmd = "npm run dev" if framework in ("nextjs", "vite", "react") else "npm start"
    return {
        "runtime": "node",
        "working_directory": ".",
        "install_command": "npm install",
        "start_command": start_cmd,
    }


def _python_fallback(entry_points: list) -> dict:
    """Return a safe Python deployment plan."""
    # Try to detect the best entry point
    start_cmd = "python main.py"
    for ep in entry_points:
        ep_lower = ep.lower()
        if "main.py" in ep_lower:
            start_cmd = f"python {ep}"
            break
        if "app.py" in ep_lower:
            start_cmd = f"python {ep}"
            break

    # FastAPI / Uvicorn detection
    for ep in entry_points:
        if ep.endswith(".py"):
            start_cmd = f"uvicorn {ep.replace('/', '.').replace('.py', '')}:app --host 0.0.0.0 --port 8000"
            break

    return {
        "runtime": "python",
        "working_directory": ".",
        "install_command": "pip install -r requirements.txt",
        "start_command": start_cmd,
    }


def _build_fallback_plan(runtime: str, framework: str, entry_points: list) -> dict:
    """Build a deterministic fallback plan from scan data."""
    rt = (runtime or "").lower().strip()

    if rt in ("node", "nodejs"):
        svc = _node_fallback(framework)
    elif rt == "python":
        svc = _python_fallback(entry_points)
    else:
        # Last resort: default to Node
        logger.warning("[Planner] Unknown runtime '%s', defaulting to node fallback", runtime)
        svc = _node_fallback(framework)

    logger.info("[Planner] Using deterministic fallback: %s", svc)
    return {"services": [svc]}


# ── Normalization helpers ─────────────────────────────────────────────────────

def _normalize_runtime(raw: str | None, detected_runtime: str) -> str:
    """Normalize runtime string, falling back to detected_runtime."""
    if not raw or str(raw).lower() in ("null", "none", "unknown", ""):
        return (detected_runtime or "node").lower().strip()
    r = str(raw).lower().strip()
    if r in ("nodejs", "node.js"):
        return "node"
    if r in ("py", "python3"):
        return "python"
    return r


def _normalize_working_dir(raw: str | None, project_root: str | None = None) -> str:
    """
    Sanitize working_directory from planner output.

    LLMs frequently hallucinate absolute paths like /root/app or C:\\project.
    We collapse all such values to '.'.
    """
    if not raw:
        return "."
    wd = str(raw).strip()

    # Reject absolute paths (Unix or Windows)
    if wd.startswith("/") or (len(wd) > 1 and wd[1] == ":"):
        logger.warning("[Planner] Rejected hallucinated working_directory '%s' → '.'", wd)
        return "."

    # Reject path traversal
    if ".." in wd:
        return "."

    # Reject common LLM hallucinations
    bad_prefixes = ("/root", "/home", "/var", "/usr", "/opt", "/app", "/srv")
    for bp in bad_prefixes:
        if wd.startswith(bp):
            logger.warning("[Planner] Rejected hallucinated working_directory '%s' → '.'", wd)
            return "."

    # Validate directory exists if root is provided
    if project_root:
        candidate = Path(project_root) / wd
        if not candidate.exists():
            logger.warning(
                "[Planner] working_directory '%s' does not exist under project root '%s' → '.'",
                wd,
                project_root,
            )
            return "."

    return wd if wd else "."


def _strip_json_comments(text: str) -> str:
    """
    Strip // line comments from JSON-like text.

    Only strips when // appears OUTSIDE quoted strings.
    A simple but effective heuristic: only strip // that appear after
    whitespace at start-of-content on a line, or after a closing bracket.
    """
    result_lines = []
    for line in text.splitlines():
        # Only strip // that appear outside strings.
        # Strategy: walk char by char to find // outside quotes.
        in_string = False
        escape_next = False
        stripped = line
        for i, ch in enumerate(line):
            if escape_next:
                escape_next = False
                continue
            if ch == "\\":
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if not in_string and ch == "/" and i + 1 < len(line) and line[i + 1] == "/":
                stripped = line[:i].rstrip()
                break
        result_lines.append(stripped)
    return "\n".join(result_lines)


def _extract_json_from_text(text: str) -> str:
    """
    Try to extract a JSON object from potentially noisy LLM output.

    Handles cases where the model wraps output in markdown fences,
    adds prose before/after, etc.
    """
    # Remove markdown fences
    text = re.sub(r"```(?:json)?", "", text)
    text = text.strip()

    # Find the first { and last }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]

    return text


class DeploymentPlanner:

    OLLAMA_URL = "http://localhost:11434/api/generate"
    MODEL = "phi3"
    # Shorter timeout so Ollama offline doesn't block the entire request for 5 min
    OLLAMA_TIMEOUT = 120

    @classmethod
    def plan(
        cls,
        manifests: list,
        runtime: str,
        framework: str,
        entry_points: list,
        project_root: str | None = None,
    ) -> dict:
        """
        Generate a deployment plan.

        Tries Ollama first.  If Ollama is offline or returns garbage,
        falls back to a deterministic plan based on scan data.
        Returns a dict with guaranteed 'services' list (never empty).
        """
        logger.info(
            "[Planner] Starting — runtime=%s, framework=%s, entry_points=%s, manifests=%d",
            runtime,
            framework,
            entry_points,
            len(manifests),
        )

        # ── Deterministic fallback defined BEFORE any try/except ────────────
        # This guarantees it's always in scope for the except handler.
        fallback_plan = _build_fallback_plan(runtime, framework, entry_points)

        try:
            plan = cls._call_ollama(
                manifests=manifests,
                runtime=runtime,
                framework=framework,
                entry_points=entry_points,
                fallback_plan=fallback_plan,
                project_root=project_root,
            )
            logger.info("[Planner] Final plan: %s", json.dumps(plan))
            return plan

        except Exception as exc:
            logger.error("[Planner] Unhandled exception, using fallback: %s", exc)
            return fallback_plan

    @classmethod
    def _call_ollama(
        cls,
        manifests: list,
        runtime: str,
        framework: str,
        entry_points: list,
        fallback_plan: dict,
        project_root: str | None,
    ) -> dict:
        """Call Ollama and parse/validate the response."""

        prompt = f"""You are a deployment planning engine.

Your task is to analyze project manifest files and return a deployment plan.

Return ONLY valid JSON. No markdown. No explanations. No comments.

Expected format:

{{
  "services": [
    {{
      "runtime": "node",
      "working_directory": ".",
      "install_command": "npm install",
      "start_command": "npm start"
    }}
  ]
}}

Rules:
- Always return valid JSON
- Never include markdown fences
- Never include explanations or comments
- working_directory MUST be "." (a relative path)  — never an absolute path
- runtime must be "node" or "python" only
- Always include: runtime, working_directory, install_command, start_command

Framework rules:
- Next.js → start_command = "npm run dev"
- Vite → start_command = "npm run dev"
- Express → start_command = "npm start"
- FastAPI → start_command = "uvicorn main:app --host 0.0.0.0 --port 8000"
- Flask → start_command = "python app.py"

Detected Runtime: {runtime}
Detected Framework: {framework}
Detected Entry Points: {json.dumps(entry_points, indent=2)}

Manifest Files:
{json.dumps(manifests, indent=2)}
"""

        # ── Ollama request ───────────────────────────────────────────────────
        try:
            logger.info("[Planner] Calling Ollama model=%s timeout=%ds", cls.MODEL, cls.OLLAMA_TIMEOUT)
            response = requests.post(
                cls.OLLAMA_URL,
                json={
                    "model": cls.MODEL,
                    "prompt": prompt,
                    "stream": False,
                },
                timeout=cls.OLLAMA_TIMEOUT,
            )
            response.raise_for_status()
        except requests.exceptions.ConnectionError:
            logger.warning("[Planner] Ollama is offline — using deterministic fallback")
            return fallback_plan
        except requests.exceptions.Timeout:
            logger.warning("[Planner] Ollama timed out (%ds) — using deterministic fallback", cls.OLLAMA_TIMEOUT)
            return fallback_plan
        except requests.exceptions.RequestException as exc:
            logger.warning("[Planner] Ollama request failed (%s) — using deterministic fallback", exc)
            return fallback_plan

        # ── Parse raw output ─────────────────────────────────────────────────
        result = response.json()
        raw_output = result.get("response", "").strip()
        logger.info("[Planner] LLM raw output (%d chars): %s", len(raw_output), raw_output[:500])

        if not raw_output:
            logger.warning("[Planner] Empty LLM response — using fallback")
            return fallback_plan

        # ── Clean and parse JSON ─────────────────────────────────────────────
        try:
            cleaned = _extract_json_from_text(raw_output)
            cleaned = _strip_json_comments(cleaned)
            logger.info("[Planner] Cleaned output: %s", cleaned[:500])

            deployment_plan = json.loads(cleaned)

            # Handle array at top level
            if isinstance(deployment_plan, list):
                deployment_plan = {"services": deployment_plan}

        except json.JSONDecodeError as exc:
            logger.warning("[Planner] JSON parse failed (%s) — using fallback", exc)
            return fallback_plan

        # ── Validate and normalize services ──────────────────────────────────
        services_raw = deployment_plan.get("services", [])

        if not isinstance(services_raw, list) or len(services_raw) == 0:
            logger.warning("[Planner] No valid services in LLM output — using fallback")
            return fallback_plan

        normalized_services = []

        for svc in services_raw:
            if not isinstance(svc, dict):
                continue

            raw_runtime = svc.get("runtime")
            runtime_name = _normalize_runtime(raw_runtime, runtime)

            working_dir = _normalize_working_dir(
                svc.get("working_directory", "."),
                project_root,
            )

            install_command = str(svc.get("install_command", "")).strip()
            start_command = str(svc.get("start_command", "")).strip()

            # ── Safe defaults per runtime ────────────────────────────────────
            if runtime_name in ("node", "nodejs"):
                runtime_name = "node"
                if not install_command:
                    install_command = "npm install"
                # Reject prefix-style install commands (LLM hallucination)
                if install_command.startswith("npm install --prefix"):
                    install_command = "npm install"
                if not start_command:
                    if framework in ("nextjs", "vite", "react"):
                        start_command = "npm run dev"
                    else:
                        start_command = "npm start"

            elif runtime_name == "python":
                if not install_command:
                    install_command = "pip install -r requirements.txt"
                if not start_command:
                    # Detect FastAPI/Flask from entry points
                    for ep in entry_points:
                        if ep.endswith(".py"):
                            module = ep.replace("/", ".").replace(".py", "")
                            start_command = f"uvicorn {module}:app --host 0.0.0.0 --port 8000"
                            break
                    if not start_command:
                        start_command = "python main.py"
            else:
                # Unsupported runtime from LLM — override with fallback for detected runtime
                logger.warning(
                    "[Planner] Unrecognized runtime '%s' in service, overriding with detected runtime '%s'",
                    runtime_name,
                    runtime,
                )
                fallback_svc = _build_fallback_plan(runtime, framework, entry_points)["services"][0]
                runtime_name = fallback_svc["runtime"]
                install_command = fallback_svc["install_command"]
                start_command = fallback_svc["start_command"]

            normalized_services.append({
                "runtime": runtime_name,
                "working_directory": working_dir,
                "install_command": install_command,
                "start_command": start_command,
            })

        if not normalized_services:
            logger.warning("[Planner] Normalization produced empty services list — using fallback")
            return fallback_plan

        final_plan = {"services": normalized_services}
        logger.info("[Planner] Normalized plan: %s", json.dumps(final_plan))
        return final_plan