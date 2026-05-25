"""
Anti Gravity Deployments — Deployment Planner

Calls Ollama (phi3) to generate a deployment plan from scan results.
Falls back deterministically if Ollama is offline, times out,
or returns malformed / empty output.

Key guarantees:
  - fallback_plan is ALWAYS defined before try/except (no UnboundLocalError)
  - All service fields are always populated (no None/null values)
  - working_directory is ALWAYS a safe relative path (never absolute)
  - services is NEVER empty
  - Runtime is ALWAYS "node" or "python"
"""

import json
import logging
import re
import requests
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ── NULL / NONE guard ──────────────────────────────────────────────────────────

def _safe(value, default: str = "") -> str:
    """
    Convert any value to a safe non-None string.
    Catches the string literals "None", "null", "undefined".
    """
    if value is None:
        return default
    s = str(value).strip()
    if s.lower() in ("none", "null", "undefined", "n/a", ""):
        return default
    return s


# ── Deterministic Fallback Plans ───────────────────────────────────────────────

_FRAMEWORK_COMMANDS: dict[str, tuple[str, int]] = {
    # (start_command, port)  — ALL production-grade, never dev-server
    "nextjs":   ("npm run start",  3000),   # Assumes already built — Dockerfile builds first
    "react":    ("npx serve -s build -l 3000", 3000),
    "vite":     ("npx serve -s dist -l 4173", 4173),
    "vue":      ("npx serve -s dist -l 4173", 4173),
    "express":  ("npm start",    3000),
    "angular":  ("npx serve -s dist -l 4200", 4200),
    "node":     ("npm start",    3000),
    "fastapi":  ("uvicorn main:app --host 0.0.0.0 --port 8000", 8000),
    "django":   ("python manage.py runserver 0.0.0.0:8000", 8000),
    "flask":    ("flask run --host 0.0.0.0 --port 5000", 5000),
    "python":   ("python main.py", 8000),
}

_RUNTIME_INSTALL: dict[str, str] = {
    "node":   "npm install",
    "python": "pip install -r requirements.txt",
}


def _node_fallback(framework: str, install_cmd: str = "", start_cmd: str = "") -> dict:
    """Return a fully-populated Node.js service dict (always production-safe)."""
    fw = (framework or "node").lower().strip()
    default_start, _ = _FRAMEWORK_COMMANDS.get(fw, _FRAMEWORK_COMMANDS["node"])

    # For Next.js: NEVER allow dev-server commands in containers
    # The Dockerfile handles build; the start command just needs 'npm run start'
    if fw == "nextjs":
        # Override any dev command from scanner
        if _safe(start_cmd) in ("npm run dev", "next dev", "npx next dev", "yarn dev", "pnpm dev"):
            start_cmd = "npm run start"
        default_start = "npm run start"

    return {
        "runtime": "node",
        "working_directory": ".",
        "install_command": _safe(install_cmd, "npm install"),
        "start_command": _safe(start_cmd, default_start),
    }


def _python_fallback(
    framework: str,
    entry_points: list,
    install_cmd: str = "",
    start_cmd: str = "",
) -> dict:
    """Return a fully-populated Python service dict."""
    fw = (framework or "python").lower().strip()
    default_start, _ = _FRAMEWORK_COMMANDS.get(fw, _FRAMEWORK_COMMANDS["python"])

    # Try to infer start command from entry points if no override
    if not _safe(start_cmd):
        if fw == "fastapi":
            for ep in entry_points:
                if ep.endswith(".py"):
                    mod = ep.replace("\\", "/").replace("/", ".").replace(".py", "")
                    default_start = f"uvicorn {mod}:app --host 0.0.0.0 --port 8000"
                    break
        elif fw == "flask":
            # Always prefer flask run for proper 0.0.0.0 binding
            default_start = "flask run --host 0.0.0.0 --port 5000"
        elif fw == "django":
            default_start = "python manage.py runserver 0.0.0.0:8000"

    return {
        "runtime": "python",
        "working_directory": ".",
        "install_command": _safe(install_cmd, "pip install -r requirements.txt"),
        "start_command": _safe(start_cmd, default_start),
    }


def _build_fallback_plan(
    runtime: str,
    framework: str,
    entry_points: list,
    install_cmd: str = "",
    start_cmd: str = "",
) -> dict:
    """
    Build a deterministic deployment plan from scan data.

    Always returns {"services": [<one fully-populated service dict>]}.
    Never returns an empty services list.
    Never contains None values.
    """
    rt = _safe(runtime, "node").lower()

    if rt in ("node", "nodejs"):
        svc = _node_fallback(framework, install_cmd, start_cmd)
    elif rt == "python":
        svc = _python_fallback(framework, entry_points, install_cmd, start_cmd)
    else:
        logger.warning("[Planner] Unknown runtime '%s' → defaulting to node", runtime)
        svc = _node_fallback(framework, install_cmd, start_cmd)

    logger.info("[Planner] Deterministic fallback: %s", svc)
    return {"services": [svc]}


# ── Normalization Helpers ──────────────────────────────────────────────────────

def _normalize_runtime(raw, detected: str) -> str:
    """
    Return a canonical runtime string: "node" or "python".
    Never returns None, never returns "nodejs".
    """
    r = _safe(raw, detected or "node").lower()
    if r in ("nodejs", "node.js"):
        return "node"
    if r in ("py", "python3", "python2"):
        return "python"
    if r not in ("node", "python"):
        logger.warning("[Planner] Unrecognized runtime '%s' → '%s'", r, detected or "node")
        return _safe(detected, "node").lower().replace("nodejs", "node")
    return r


def _normalize_working_dir(raw, project_root: Optional[str] = None) -> str:
    """
    Sanitize working_directory from planner output.

    Rules:
    - Absolute paths (Unix or Windows) → "."
    - Path traversal (..) → "."
    - Common LLM hallucinations (/root, /home, /app, etc.) → "."
    - Non-existent sub-dirs → "." (if project_root provided)
    - Empty / None → "."
    """
    wd = _safe(raw, ".")
    if wd == ".":
        return "."

    # Reject absolute paths
    if wd.startswith("/") or (len(wd) > 1 and wd[1] == ":"):
        logger.warning("[Planner] Rejected absolute working_directory '%s' → '.'", wd)
        return "."

    # Reject path traversal
    if ".." in wd:
        logger.warning("[Planner] Rejected traversal working_directory '%s' → '.'", wd)
        return "."

    # Reject common LLM hallucinations
    for bad in ("/root", "/home", "/var", "/usr", "/opt", "/app", "/srv",
                "root/", "home/", "app/workspace"):
        if wd.lower().startswith(bad.lower()):
            logger.warning("[Planner] Rejected hallucinated working_directory '%s' → '.'", wd)
            return "."

    # If project root provided, validate the directory exists
    if project_root:
        candidate = Path(project_root) / wd
        if not candidate.is_dir():
            logger.warning(
                "[Planner] working_directory '%s' not found under '%s' → '.'",
                wd, project_root
            )
            return "."

    return wd


def _strip_json_comments(text: str) -> str:
    """
    Strip // line comments from JSON text WITHOUT stripping URL content.

    Uses a character-level state machine to track string context.
    Only strips // that appear OUTSIDE double-quoted strings.
    """
    result_lines = []
    for line in text.splitlines():
        in_string = False
        escape_next = False
        stripped = line

        for i, ch in enumerate(line):
            if escape_next:
                escape_next = False
                continue
            if ch == "\\" and in_string:
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


def _extract_json_block(text: str) -> str:
    """
    Extract the first balanced JSON object from potentially noisy LLM output.

    Handles:
    - Markdown fences (```json ... ```)
    - Prose before/after the JSON
    - Trailing commas (light cleanup)
    """
    # Remove markdown fences
    text = re.sub(r"```(?:json)?", "", text, flags=re.IGNORECASE)
    text = text.strip()

    # Find the outermost { ... } block
    start = text.find("{")
    if start == -1:
        return text

    depth = 0
    for i, ch in enumerate(text[start:], start=start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]

    # Fallback: take everything from first { to last }
    end = text.rfind("}")
    if end != -1 and end > start:
        return text[start : end + 1]

    return text


def _normalize_service(svc: dict, detected_runtime: str, framework: str, entry_points: list) -> dict | None:
    """
    Normalize a single service dict from LLM output.

    Returns a fully-populated service dict, or None if the service is unusable.
    All string fields are guaranteed non-None.
    """
    if not isinstance(svc, dict):
        return None

    runtime = _normalize_runtime(svc.get("runtime"), detected_runtime)
    working_dir = _normalize_working_dir(svc.get("working_directory", "."))
    install_cmd = _safe(svc.get("install_command"), "")
    start_cmd = _safe(svc.get("start_command"), "")

    # ── Apply runtime-specific defaults ───────────────────────────────────────
    if runtime == "node":
        if not install_cmd:
            install_cmd = "npm install"
        # Reject --prefix-style installs (common LLM hallucination)
        if "--prefix" in install_cmd:
            install_cmd = "npm install"
        if not start_cmd:
            default_start, _ = _FRAMEWORK_COMMANDS.get(
                framework, _FRAMEWORK_COMMANDS["node"]
            )
            start_cmd = default_start

        # ── Production enforcement: Next.js NEVER runs in dev mode inside Docker ──
        if framework == "nextjs":
            _dev_cmds = {"npm run dev", "next dev", "npx next dev", "yarn dev", "pnpm dev",
                         "pnpm run dev", "yarn run dev"}
            if start_cmd.strip().lower() in _dev_cmds or "next dev" in start_cmd:
                logger.info("[Planner] Next.js: replacing dev command '%s' → 'npm run start'", start_cmd)
                start_cmd = "npm run start"

    elif runtime == "python":
        if not install_cmd:
            install_cmd = "pip install -r requirements.txt"
        if not start_cmd:
            default_start, _ = _FRAMEWORK_COMMANDS.get(
                framework, _FRAMEWORK_COMMANDS["python"]
            )
            # Try to infer from entry points for FastAPI
            if framework == "fastapi":
                for ep in entry_points:
                    if ep.endswith(".py"):
                        mod = ep.replace("\\", "/").replace("/", ".").replace(".py", "")
                        default_start = f"uvicorn {mod}:app --host 0.0.0.0 --port 8000"
                        break
            start_cmd = default_start
        # Remove --reload in production (causes issues in containers)
        if "--reload" in start_cmd and framework in ("fastapi",):
            start_cmd = start_cmd.replace(" --reload", "")
            logger.info("[Planner] Removed --reload from production FastAPI start command")

    else:
        # Unrecognized runtime — override with detected runtime defaults
        logger.warning("[Planner] Service has unknown runtime '%s' → using detected '%s'", runtime, detected_runtime)
        runtime = _safe(detected_runtime, "node").replace("nodejs", "node")
        install_cmd = _RUNTIME_INSTALL.get(runtime, "npm install")
        default_start, _ = _FRAMEWORK_COMMANDS.get(framework, _FRAMEWORK_COMMANDS.get(runtime, ("npm start", 3000)))
        start_cmd = default_start

    return {
        "runtime": runtime,
        "working_directory": working_dir,
        "install_command": install_cmd,
        "start_command": start_cmd,
    }


# ── Main Planner Class ─────────────────────────────────────────────────────────

class DeploymentPlanner:

    OLLAMA_URL = "http://localhost:11434/api/generate"
    MODEL = "phi3"
    OLLAMA_TIMEOUT = 90   # seconds; tuned for typical LLM response time

    @classmethod
    def plan(
        cls,
        manifests: list,
        runtime: str,
        framework: str,
        entry_points: list,
        project_root: Optional[str] = None,
        install_command: str = "",
        start_command: str = "",
    ) -> dict:
        """
        Generate a deployment plan from scan data.

        Guarantees:
        - Returns {"services": [<at least one fully-populated service>]}
        - No None/null values in any field
        - Never raises
        """
        logger.info(
            "[Planner] Starting — runtime=%s framework=%s manifests=%d entry_points=%s",
            runtime, framework, len(manifests), entry_points
        )

        # ── Build fallback BEFORE any try/except (UnboundLocalError prevention) ──
        fallback_plan = _build_fallback_plan(
            runtime, framework, entry_points,
            install_cmd=install_command,
            start_cmd=start_command,
        )

        try:
            plan = cls._call_ollama(
                manifests=manifests,
                runtime=runtime,
                framework=framework,
                entry_points=entry_points,
                fallback_plan=fallback_plan,
                project_root=project_root,
                install_command=install_command,
                start_command=start_command,
            )
            logger.info("[Planner] Final plan services=%d", len(plan.get("services", [])))
            return plan

        except Exception as exc:
            logger.error("[Planner] Unhandled exception → using fallback: %s", exc, exc_info=True)
            return fallback_plan

    @classmethod
    def _call_ollama(
        cls,
        manifests: list,
        runtime: str,
        framework: str,
        entry_points: list,
        fallback_plan: dict,
        project_root: Optional[str],
        install_command: str,
        start_command: str,
    ) -> dict:
        """
        Call Ollama and parse/validate/normalize the response.
        Returns fallback_plan on any Ollama error.
        """
        # ── Build manifest summary for prompt ─────────────────────────────────
        manifest_summary = []
        for m in manifests[:4]:  # limit to 4 manifests to keep prompt size manageable
            snippet = m.get("content", "")[:800]
            manifest_summary.append(f"--- {m['relative_path']} ---\n{snippet}")
        manifest_text = "\n\n".join(manifest_summary) if manifest_summary else "(no manifests found)"

        # ── Build the prompt ──────────────────────────────────────────────────
        prompt = f"""You are a deployment engine. Return ONLY valid JSON. No explanation, no markdown.

Output format (EXACTLY this shape):
{{
  "services": [
    {{
      "runtime": "node",
      "working_directory": ".",
      "install_command": "npm install",
      "start_command": "npm run dev"
    }}
  ]
}}

Rules:
- runtime: ONLY "node" or "python"
- working_directory: MUST be "." (relative, never absolute path)
- install_command: use "npm install", "pip install -r requirements.txt", etc
- start_command: must be a valid shell command
- services: array with at least 1 entry

Framework-specific start commands:
- Next.js:  npm run dev
- Vite:     npm run dev
- React CRA: npm start
- Express:  npm start
- FastAPI:  uvicorn main:app --host 0.0.0.0 --port 8000 --reload
- Flask:    flask run --host 0.0.0.0 --port 5000
- Django:   python manage.py runserver 0.0.0.0:8000

Detected info:
- Runtime: {runtime}
- Framework: {framework}
- Detected install command: {install_command or "unknown"}
- Detected start command: {start_command or "unknown"}
- Entry points: {json.dumps(entry_points)}

Project manifests:
{manifest_text}

Output ONLY the JSON object. Nothing else."""

        # ── Ollama HTTP call ───────────────────────────────────────────────────
        try:
            logger.info("[Planner] Calling Ollama model=%s timeout=%ds", cls.MODEL, cls.OLLAMA_TIMEOUT)
            resp = requests.post(
                cls.OLLAMA_URL,
                json={"model": cls.MODEL, "prompt": prompt, "stream": False},
                timeout=cls.OLLAMA_TIMEOUT,
            )
            resp.raise_for_status()
        except requests.exceptions.ConnectionError:
            logger.warning("[Planner] Ollama offline → using deterministic fallback")
            return fallback_plan
        except requests.exceptions.Timeout:
            logger.warning("[Planner] Ollama timed out (%ds) → using deterministic fallback", cls.OLLAMA_TIMEOUT)
            return fallback_plan
        except requests.exceptions.RequestException as exc:
            logger.warning("[Planner] Ollama error (%s) → using deterministic fallback", exc)
            return fallback_plan

        # ── Parse raw output ───────────────────────────────────────────────────
        raw_output = resp.json().get("response", "").strip()
        logger.info("[Planner] LLM raw output (%d chars): %.300s", len(raw_output), raw_output)

        if not raw_output:
            logger.warning("[Planner] Empty LLM response → using fallback")
            return fallback_plan

        # ── Clean and parse JSON ───────────────────────────────────────────────
        try:
            cleaned = _extract_json_block(raw_output)
            cleaned = _strip_json_comments(cleaned)
            logger.debug("[Planner] Cleaned JSON: %.400s", cleaned)

            parsed = json.loads(cleaned)

            # Handle array at top level
            if isinstance(parsed, list):
                parsed = {"services": parsed}

        except json.JSONDecodeError as exc:
            logger.warning("[Planner] JSON parse failed (%s) → using fallback", exc)
            return fallback_plan

        # ── Validate and normalize services ───────────────────────────────────
        raw_services = parsed.get("services", [])
        if not isinstance(raw_services, list):
            logger.warning("[Planner] 'services' is not a list → using fallback")
            return fallback_plan

        normalized: list[dict] = []
        for svc in raw_services:
            result = _normalize_service(svc, runtime, framework, entry_points)
            if result:
                normalized.append(result)

        if not normalized:
            logger.warning("[Planner] Normalization produced empty services list → using fallback")
            return fallback_plan

        final = {"services": normalized}
        logger.info("[Planner] Normalized plan: %s", json.dumps(final))
        return final