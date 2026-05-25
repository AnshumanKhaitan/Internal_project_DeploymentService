"""
Anti Gravity Deployments — Manifest Scanner

Scans project directories to detect:
- Runtime (node / python)
- Framework (nextjs / react / vite / express / fastapi / flask / django)
- Entry points (filtered by runtime, no cross-contamination)
- Package manager (npm / yarn / pnpm)
- Monorepo / workspace structure (frontend/, backend/, apps/*, services/*)
- Python entry point selection (main.py, app.py, manage.py, wsgi.py, asgi.py)
"""

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


# ── Constants ──────────────────────────────────────────────────────────────────

EXCLUDED_DIRS = {
    "node_modules", ".git", ".venv", "venv", "__pycache__",
    "dist", "build", ".next", ".nuxt", ".output", ".turbo",
    ".cache", "coverage", ".pytest_cache", ".mypy_cache",
    ".tox", "env", ".env", "eggs", "*.egg-info",
}

NODE_ENTRYPOINTS = {
    "index.js", "index.ts", "server.js", "server.ts",
    "app.js", "app.ts", "main.js", "main.ts",
}

PYTHON_ENTRYPOINTS = {
    "main.py", "app.py", "manage.py", "wsgi.py", "asgi.py",
    "run.py", "server.py", "application.py",
}

PYTHON_MANIFEST_FILES = {"requirements.txt", "pyproject.toml", "setup.py", "setup.cfg", "Pipfile"}
NODE_MANIFEST_FILES = {"package.json"}

# Monorepo workspace directory patterns (in priority order)
MONOREPO_WORKSPACE_DIRS = [
    "frontend", "backend", "api", "web", "client", "server",
    "app", "apps", "services", "packages",
]


def _excluded(path: Path) -> bool:
    """Return True if any component of this path is in the exclusion set."""
    return any(part in EXCLUDED_DIRS for part in path.parts)


def _read_json(path: Path) -> dict:
    """Read and parse a JSON file, returning {} on failure."""
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return {}


def _read_text(path: Path) -> str:
    """
    Read a text file, trying UTF-8 first then UTF-16 (common on Windows).
    Returns '' on failure.
    """
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        # Detect UTF-16: if >20% chars are null bytes, re-read as UTF-16
        null_ratio = content.count("\x00") / max(len(content), 1)
        if null_ratio > 0.2:
            try:
                content = path.read_text(encoding="utf-16", errors="replace")
            except Exception:
                pass
        return content
    except Exception:
        return ""


# ── Package Manager Detection ──────────────────────────────────────────────────

def _detect_package_manager(root: Path) -> str:
    """Detect the package manager: npm / yarn / pnpm."""
    if (root / "pnpm-lock.yaml").exists() or (root / "pnpm-workspace.yaml").exists():
        return "pnpm"
    if (root / "yarn.lock").exists():
        return "yarn"
    return "npm"


def _install_command(root: Path) -> str:
    """Return the correct install command for this Node project."""
    pm = _detect_package_manager(root)
    if pm == "pnpm":
        return "pnpm install"
    if pm == "yarn":
        return "yarn install"
    return "npm install"


# ── Node.js Framework Detection ────────────────────────────────────────────────

def _detect_node_framework(root: Path, pkg: dict) -> tuple[str, int, str]:
    """
    Return (framework, port, start_command) for a Node project.
    Reads package.json deps and file-system markers.
    """
    all_deps: dict = {
        **pkg.get("dependencies", {}),
        **pkg.get("devDependencies", {}),
    }
    dep_names = {k.lower() for k in all_deps}
    scripts = pkg.get("scripts", {})

    # ── Next.js ──────────────────────────────────────────────────────────────
    if "next" in dep_names:
        # ALWAYS use production server — Dockerfile builds first with 'npm run build'
        # Never use 'npm run dev' for containerized deployments
        start_cmd = "npm run start"
        return ("nextjs", 3000, start_cmd)

    # ── Angular ───────────────────────────────────────────────────────────────
    if "@angular/core" in dep_names or (root / "angular.json").exists():
        start_cmd = "npm run build && npx http-server dist -p 4200 -a 0.0.0.0"
        return ("angular", 4200, start_cmd)

    # ── Vite (check before react because Vite apps often have react too) ──────
    if "vite" in dep_names:
        # Production: build then serve static dist/
        start_cmd = "npx serve -s dist -l 4173"

        # Detect framework used WITH Vite
        if "react" in dep_names:
            return ("react", 4173, start_cmd)
        if "vue" in dep_names:
            return ("vue", 4173, start_cmd)
        return ("vite", 4173, start_cmd)

    # ── React CRA ─────────────────────────────────────────────────────────────
    if "react" in dep_names:
        if "react-scripts" in dep_names:
            if "start" in scripts:
                return ("react", 3000, "npm start")
        if "start" in scripts:
            return ("react", 3000, "npm start")
        if "dev" in scripts:
            return ("react", 3000, "npm run dev")
        return ("react", 3000, "npm start")

    # ── Vue ───────────────────────────────────────────────────────────────────
    if "vue" in dep_names:
        start_cmd = "npx serve -s dist -l 4173"
        return ("vue", 4173, start_cmd)

    # ── Express ───────────────────────────────────────────────────────────────
    if "express" in dep_names:
        if "start" in scripts:
            return ("express", 3000, "npm start")
        return ("express", 3000, "node index.js")

    # ── Fastify / Hapi / Koa (generic Node server) ────────────────────────────
    for server_fw in ("fastify", "hapi", "koa", "restify"):
        if server_fw in dep_names:
            start_cmd = "npm start" if "start" in scripts else "node index.js"
            return (server_fw, 3000, start_cmd)

    # ── Generic Node ──────────────────────────────────────────────────────────
    if "start" in scripts:
        return ("node", 3000, "npm start")
    if "dev" in scripts:
        return ("node", 3000, "npm run dev")

    return ("node", 3000, "npm start")


# ── Python Framework Detection ─────────────────────────────────────────────────

def _detect_python_framework(root: Path) -> tuple[str, int, str]:
    """
    Return (framework, port, start_command) for a Python project.
    Reads requirements.txt, pyproject.toml, and known entry point files.
    """
    # Read requirements for framework detection
    deps_lower: set[str] = set()

    req_path = root / "requirements.txt"
    if req_path.exists():
        for line in _read_text(req_path).splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            name = re.split(r"[>=<!~\[\s]", line)[0].lower().strip()
            if name:
                deps_lower.add(name)

    pyproject_path = root / "pyproject.toml"
    if pyproject_path.exists():
        raw = _read_text(pyproject_path)
        for match in re.finditer(r'"([a-z][a-z0-9_-]*)"', raw):
            deps_lower.add(match.group(1).lower())

    # ── FastAPI ───────────────────────────────────────────────────────────────
    if "fastapi" in deps_lower:
        # Find best entry: app/main.py > main.py > app.py
        if (root / "app" / "main.py").exists():
            return ("fastapi", 8000, "uvicorn app.main:app --host 0.0.0.0 --port 8000")
        if (root / "main.py").exists():
            return ("fastapi", 8000, "uvicorn main:app --host 0.0.0.0 --port 8000")
        if (root / "app.py").exists():
            return ("fastapi", 8000, "uvicorn app:app --host 0.0.0.0 --port 8000")
        # Look for any module that contains FastAPI()
        for py_file in sorted(root.rglob("*.py")):
            if _excluded(py_file):
                continue
            content = _read_text(py_file)
            if "FastAPI()" in content or "FastAPI(" in content:
                module = py_file.relative_to(root)
                mod_str = str(module).replace("\\", "/").replace("/", ".").replace(".py", "")
                return ("fastapi", 8000, f"uvicorn {mod_str}:app --host 0.0.0.0 --port 8000")
        return ("fastapi", 8000, "uvicorn main:app --host 0.0.0.0 --port 8000")

    # ── Django ────────────────────────────────────────────────────────────────
    if "django" in deps_lower:
        if (root / "manage.py").exists():
            return ("django", 8000, "python manage.py runserver 0.0.0.0:8000")
        return ("django", 8000, "python manage.py runserver 0.0.0.0:8000")

    # ── Flask ─────────────────────────────────────────────────────────────────
    if "flask" in deps_lower:
        if (root / "app.py").exists():
            return ("flask", 5000, "flask run --host 0.0.0.0 --port 5000")
        if (root / "main.py").exists():
            return ("flask", 5000, "python main.py")
        # Find flask app
        for py_file in sorted(root.rglob("*.py")):
            if _excluded(py_file):
                continue
            content = _read_text(py_file)
            if "Flask(__name__)" in content or "Flask(" in content:
                module = py_file.relative_to(root)
                return ("flask", 5000, f"python {str(module).replace(chr(92), '/')}")
        return ("flask", 5000, "flask run --host 0.0.0.0 --port 5000")

    # ── Gunicorn / WSGI ───────────────────────────────────────────────────────
    if "gunicorn" in deps_lower:
        if (root / "wsgi.py").exists():
            return ("python", 8000, "gunicorn wsgi:application --bind 0.0.0.0:8000")
        return ("python", 8000, "gunicorn app:app --bind 0.0.0.0:8000")

    # ── Generic Python ────────────────────────────────────────────────────────
    for ep in ("main.py", "app.py", "run.py", "server.py", "application.py"):
        if (root / ep).exists():
            return ("python", 8000, f"python {ep}")

    return ("python", 8000, "python main.py")


# ── Monorepo Detection ─────────────────────────────────────────────────────────

def _find_workspace_root(root: Path) -> Path | None:
    """
    Look for a monorepo-style sub-directory that is the actual service root.

    Checks common patterns:
    - root/frontend/ has package.json
    - root/backend/ has requirements.txt or package.json
    - root/apps/web/
    - root/packages/api/
    etc.

    Returns the most-likely single-service root, or None if this looks like a
    single-service project (package.json / requirements.txt at root).
    """
    # If root already has a direct manifest, this isn't a monorepo
    if (root / "package.json").exists() or (root / "requirements.txt").exists():
        return None

    # Try common workspace directories
    for dirname in MONOREPO_WORKSPACE_DIRS:
        candidate = root / dirname
        if candidate.is_dir():
            if (candidate / "package.json").exists() or (candidate / "requirements.txt").exists():
                logger.info("[Scanner] Monorepo: service root detected at %s", candidate)
                return candidate

    # Try apps/* and services/* with sub-directories
    for top_dir in ("apps", "services", "packages"):
        top = root / top_dir
        if top.is_dir():
            for child in sorted(top.iterdir()):
                if child.is_dir() and not child.name.startswith("."):
                    if (child / "package.json").exists() or (child / "requirements.txt").exists():
                        logger.info("[Scanner] Monorepo: nested service root at %s", child)
                        return child

    return None


# ── Main Scanner ───────────────────────────────────────────────────────────────

class ManifestScanner:
    """
    Full project scanner for deployment planning.

    Returns a scan_result dict:
    {
        "runtime": "node" | "python" | "unknown",
        "framework": "nextjs" | "react" | "fastapi" | ...,
        "start_command": str,
        "install_command": str,
        "detected_port": int,
        "entry_points": [str, ...],
        "manifests": [{"file_name": str, "relative_path": str, "content": str}, ...],
        "package_manager": "npm" | "yarn" | "pnpm",
        "workspace_root": str | None,     # relative subdir if monorepo
        "is_monorepo": bool,
    }
    """

    @classmethod
    def scan(cls, root_path: str) -> dict:
        root = Path(root_path)
        logger.info("[Scanner] Scanning %s", root)

        # ── Monorepo detection ────────────────────────────────────────────────
        workspace_root = _find_workspace_root(root)
        is_monorepo = workspace_root is not None
        scan_root = workspace_root if workspace_root else root
        workspace_rel = str(workspace_root.relative_to(root)) if workspace_root else None

        logger.info(
            "[Scanner] scan_root=%s monorepo=%s workspace=%s",
            scan_root, is_monorepo, workspace_rel
        )

        # ── Determine runtime ─────────────────────────────────────────────────
        has_node = (scan_root / "package.json").exists()
        has_python = any((scan_root / f).exists() for f in PYTHON_MANIFEST_FILES)

        # Fallback: deep search if root manifest missing
        if not has_node and not has_python:
            for path in scan_root.rglob("package.json"):
                if not _excluded(path):
                    has_node = True
                    break
            if not has_node:
                for name in PYTHON_MANIFEST_FILES:
                    for path in scan_root.rglob(name):
                        if not _excluded(path):
                            has_python = True
                            break

        # ── Collect manifests ─────────────────────────────────────────────────
        manifests: list[dict] = []
        manifest_file_names = NODE_MANIFEST_FILES | PYTHON_MANIFEST_FILES

        for path in sorted(scan_root.rglob("*")):
            if _excluded(path):
                continue
            if not path.is_file():
                continue
            if path.name not in manifest_file_names:
                continue

            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
                rel = str(path.relative_to(scan_root))
                manifests.append({
                    "file_name": path.name,
                    "relative_path": rel,
                    "content": content[:2000],  # truncate for LLM prompt
                })
                logger.debug("[Scanner] Manifest: %s", rel)
            except Exception as exc:
                logger.warning("[Scanner] Could not read %s: %s", path, exc)

        # ── Collect entry points (runtime-filtered) ───────────────────────────
        entry_points: list[str] = []
        allowed_eps = NODE_ENTRYPOINTS if has_node else PYTHON_ENTRYPOINTS if has_python else set()

        for path in sorted(scan_root.rglob("*")):
            if _excluded(path):
                continue
            if path.is_file() and path.name in allowed_eps:
                try:
                    ep = str(path.relative_to(scan_root))
                    entry_points.append(ep)
                except ValueError:
                    pass

        logger.info("[Scanner] entry_points=%s", entry_points)

        # ── Framework + command detection ─────────────────────────────────────
        if has_node:
            runtime = "node"
            pkg = _read_json(scan_root / "package.json") if (scan_root / "package.json").exists() else {}
            package_manager = _detect_package_manager(scan_root)
            install_cmd = _install_command(scan_root)

            framework, detected_port, start_cmd = _detect_node_framework(scan_root, pkg)

            # Override install command based on PM
            if package_manager == "pnpm":
                install_cmd = "pnpm install"
            elif package_manager == "yarn":
                install_cmd = "yarn install"

        elif has_python:
            runtime = "python"
            package_manager = "pip"
            req = scan_root / "requirements.txt"
            install_cmd = "pip install -r requirements.txt" if req.exists() else "pip install ."

            framework, detected_port, start_cmd = _detect_python_framework(scan_root)

        else:
            # Unknown — default to Node
            logger.warning("[Scanner] Could not detect runtime in %s — defaulting to node", scan_root)
            runtime = "node"
            package_manager = "npm"
            install_cmd = "npm install"
            framework = "unknown"
            detected_port = 3000
            start_cmd = "npm start"

        logger.info(
            "[Scanner] Result — runtime=%s framework=%s port=%d start='%s' install='%s'",
            runtime, framework, detected_port, start_cmd, install_cmd
        )

        return {
            "runtime": runtime,
            "framework": framework,
            "start_command": start_cmd,
            "install_command": install_cmd,
            "detected_port": detected_port,
            "entry_points": entry_points,
            "manifests": manifests,
            "package_manager": package_manager,
            "workspace_root": workspace_rel,
            "is_monorepo": is_monorepo,
            "scan_root": str(scan_root),
        }
