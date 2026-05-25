"""
Anti Gravity Deployments — Execution Engine

Handles Dockerfile generation, Docker image builds, and log collection.

Dockerfile generation supports:
- Node: npm / yarn / pnpm
  - Next.js: production build (npm run build → npm run start)
  - React/Vite: build → static serve with `serve`
  - Express/generic Node: direct server
- Python: full system-deps + Windows-package sanitization + smart pip fallback
  - FastAPI / Flask / Django / Gunicorn
  - Supports requirements.txt, pyproject.toml, Pipfile, uv.lock
- Safe alpine/slim base images, proper EXPOSE, production ENV

Key features:
- Proactive Node dependency healing (package.json patched BEFORE Docker build)
- Automatic PostgreSQL driver injection for Python projects
- Windows-package sanitization for cross-platform Python projects
- .dockerignore auto-management (node_modules excluded from build context)
- npm build-error recovery (parse → patch → retry)
"""

from __future__ import annotations

import logging
import re as _re
from pathlib import Path

import docker

from app.services.dependency_sanitizer import (
    normalize_python_dependencies,
    sanitize_requirements,
    inject_missing_python_deps,
    SanitizationResult,
)
from app.services.node_dependency_healer import (
    heal_node_project,
    build_nextjs_dockerfile_healed,
)

logger = logging.getLogger(__name__)

# Shared in-memory log store {deployment_id: [lines]}
DEPLOYMENT_LOGS: dict[str, list[str]] = {}


def _append_log(deployment_id: str, message: str) -> None:
    """Thread-safe log append."""
    if deployment_id not in DEPLOYMENT_LOGS:
        DEPLOYMENT_LOGS[deployment_id] = []
    DEPLOYMENT_LOGS[deployment_id].append(message)


# ── Port detection ─────────────────────────────────────────────────────────────

def _detect_port_from_command(start_command: str) -> int | None:
    """Extract port from '--port 8000' or ':8000' or '--bind 0.0.0.0:8000'."""
    match = _re.search(r"(?:--port[=\s]+|--bind[=\s]+\S*:|:)(\d{4,5})\b", start_command)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            pass
    return None


# ── Framework config tables ────────────────────────────────────────────────────

_NODE_FRAMEWORK_CONFIG: dict[str, tuple[str, int, str]] = {
    "nextjs":  ("node:20-alpine", 3000, "ENV HOSTNAME=0.0.0.0\nENV PORT=3000\nENV NODE_ENV=production"),
    "react":   ("node:20-alpine", 3000, "ENV PORT=3000\nENV HOST=0.0.0.0"),
    "vite":    ("node:20-alpine", 4173, "ENV PORT=4173\nENV HOST=0.0.0.0"),
    "vue":     ("node:20-alpine", 4173, "ENV PORT=4173\nENV HOST=0.0.0.0"),
    "angular": ("node:20-alpine", 4200, "ENV PORT=4200\nENV HOST=0.0.0.0"),
    "express": ("node:20-alpine", 3000, "ENV PORT=3000\nENV HOST=0.0.0.0\nENV NODE_ENV=production"),
    "node":    ("node:20-alpine", 3000, "ENV PORT=3000\nENV HOST=0.0.0.0"),
}

_PYTHON_FRAMEWORK_CONFIG: dict[str, tuple[str, int, str]] = {
    "fastapi": ("python:3.11-slim", 8000, "ENV PYTHONUNBUFFERED=1\nENV PYTHONDONTWRITEBYTECODE=1"),
    "flask":   ("python:3.11-slim", 5000, "ENV FLASK_ENV=production\nENV PYTHONUNBUFFERED=1\nENV PYTHONDONTWRITEBYTECODE=1"),
    "django":  ("python:3.11-slim", 8000, "ENV PYTHONUNBUFFERED=1\nENV PYTHONDONTWRITEBYTECODE=1"),
    "python":  ("python:3.11-slim", 8000, "ENV PYTHONUNBUFFERED=1\nENV PYTHONDONTWRITEBYTECODE=1"),
}


# ── Module-level helper: .dockerignore management ─────────────────────────────
# NOTE: This MUST remain at module level (not inside any class or function)
# so that save_dockerfile() can call it cleanly.

def _ensure_dockerignore(root: Path) -> None:
    """
    Write or update .dockerignore to exclude ephemeral directories from the
    Docker build context. node_modules must be excluded so a stale local
    install never overwrites the clean `npm install` Docker layer.
    Never raises.
    """
    ignore_path = root / ".dockerignore"

    _required = [
        "node_modules",
        ".next",
        ".git",
        "__pycache__",
        "*.pyc",
        ".env.local",
        "*.orig",   # package.json.orig backup files
    ]

    try:
        existing: set[str] = set()
        if ignore_path.exists():
            existing = {
                line.strip()
                for line in ignore_path.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.startswith("#")
            }

        missing = [e for e in _required if e not in existing]
        if not missing:
            return

        with open(ignore_path, "a", encoding="utf-8") as f:
            f.write("\n# Added by Anti Gravity deployment engine\n")
            for entry in missing:
                f.write(f"{entry}\n")

        logger.info("[Dockerfile] .dockerignore updated: added %s", missing)

    except Exception as exc:
        logger.warning("[Dockerfile] Could not update .dockerignore: %s", exc)


# ── Execution Engine ───────────────────────────────────────────────────────────

class ExecutionEngine:

    @classmethod
    def append_log(cls, deployment_id: str, message: str) -> None:
        _append_log(deployment_id, message)
        logger.debug("[Logs][%s] %s", deployment_id, message)

    # ── Dockerfile Generation ─────────────────────────────────────────────────

    @staticmethod
    def generate_dockerfile(service: dict, project_root: str = "") -> str:
        """
        Generate a production-grade Dockerfile for the given service descriptor.
        Never raises — falls back to node:20-alpine for unknown runtimes.

        project_root: used to run proactive dependency healing before generation.
        """
        runtime = str(service.get("runtime", "node")).lower().strip()
        if runtime in ("nodejs", "node.js"):
            runtime = "node"

        install_command = str(service.get("install_command", "")).strip()
        start_command   = str(service.get("start_command", "")).strip()
        framework       = str(service.get("framework", "")).lower().strip()

        if runtime == "node":
            # Proactively heal package.json BEFORE generating Dockerfile
            # so the npm install Docker layer already includes all required deps
            if project_root and framework == "nextjs":
                try:
                    heal_result = heal_node_project(project_root, framework=framework)
                    if heal_result.modified:
                        logger.info(
                            "[Dockerfile][Node] Healed package.json: %s",
                            heal_result.summary,
                        )
                except Exception as exc:
                    logger.warning("[Dockerfile][Node] Heal probe failed (non-fatal): %s", exc)
            return ExecutionEngine._node_dockerfile(
                framework, install_command, start_command, project_root=project_root
            )

        elif runtime == "python":
            return ExecutionEngine._python_dockerfile(
                framework, install_command, start_command, project_root=project_root
            )

        else:
            logger.warning("[Dockerfile] Unknown runtime '%s' → node:20-alpine fallback", runtime)
            return ExecutionEngine._node_dockerfile("node", "npm install", "npm start")

    # ── Next.js Dockerfile (healed) ───────────────────────────────────────────

    @staticmethod
    def _nextjs_dockerfile_simple(install_command: str, start_command: str) -> str:
        """
        Legacy helper kept for compatibility. Delegates to the healed variant.
        The healed variant uses rm -rf node_modules + npm install --include=dev
        to guarantee a clean install of the patched package.json.
        """
        use_pnpm = "pnpm" in install_command
        use_yarn = "yarn" in install_command
        return build_nextjs_dockerfile_healed(
            install_command, use_pnpm=use_pnpm, use_yarn=use_yarn
        )

    # ── Generic Node Dockerfile ────────────────────────────────────────────────

    @staticmethod
    def _node_dockerfile(
        framework: str,
        install_command: str,
        start_command: str,
        project_root: str = "",
    ) -> str:
        """Generate a Node.js Dockerfile. Next.js always gets the healed variant."""

        # Next.js: use healed Dockerfile (rm node_modules + npm install --include=dev)
        if framework == "nextjs":
            use_pnpm = "pnpm" in install_command
            use_yarn = "yarn" in install_command
            return build_nextjs_dockerfile_healed(
                install_command, use_pnpm=use_pnpm, use_yarn=use_yarn
            )

        # React / Vite / Vue: build then serve static dist/
        if framework in ("react", "vite", "vue"):
            if "pnpm" in install_command:
                pm_setup    = "RUN npm install -g pnpm"
                install_cmd = "pnpm install --no-frozen-lockfile || pnpm install"
                build_cmd   = "pnpm run build"
            elif "yarn" in install_command:
                pm_setup    = ""
                install_cmd = "yarn install || yarn install --ignore-engines"
                build_cmd   = "yarn build"
            else:
                pm_setup    = ""
                install_cmd = "npm install --legacy-peer-deps"
                build_cmd   = "npm run build"

            port = 4173 if framework in ("vite", "vue") else 3000

            return f"""FROM node:20-alpine

WORKDIR /app

ENV NODE_ENV=production
ENV HOST=0.0.0.0
ENV PORT={port}

COPY package*.json ./
{pm_setup}
RUN {install_cmd}

COPY . .
RUN {build_cmd}

RUN npm install -g serve

EXPOSE {port}

CMD ["serve", "-s", "dist", "-l", "{port}"]
"""

        # Angular
        if framework == "angular":
            return """FROM node:20-alpine

WORKDIR /app

ENV NODE_ENV=production

COPY package*.json ./
RUN npm install --legacy-peer-deps

COPY . .
RUN npm run build -- --configuration=production || npm run build

RUN npm install -g serve

EXPOSE 4200

CMD ["serve", "-s", "dist", "-l", "4200"]
"""

        # Express / generic Node
        fw_config = _NODE_FRAMEWORK_CONFIG.get(framework, _NODE_FRAMEWORK_CONFIG["node"])
        base_image, port, env_block = fw_config

        if not install_command:
            install_command = "npm install"
        if not start_command:
            start_command = "npm start"

        detected_port = _detect_port_from_command(start_command)
        if detected_port:
            port = detected_port

        if "pnpm" in install_command:
            pm_setup    = "RUN npm install -g pnpm\n"
            install_cmd = install_command
        elif "yarn" in install_command:
            pm_setup    = ""
            install_cmd = install_command
        else:
            pm_setup    = ""
            install_cmd = f"{install_command} --legacy-peer-deps || {install_command}"

        return f"""FROM {base_image}

WORKDIR /app

{env_block}

COPY package*.json ./
{pm_setup}RUN {install_cmd}

COPY . .

EXPOSE {port}

CMD {ExecutionEngine._to_cmd(start_command)}
"""

    # ── Python Dockerfile ──────────────────────────────────────────────────────

    @staticmethod
    def _python_dockerfile(
        framework: str,
        install_command: str,
        start_command: str,
        project_root: str = "",
    ) -> str:
        """
        Production Python Dockerfile with:
        1. Full system dependency layer (gcc, build-essential, libpq-dev, etc.)
        2. Automatic Windows-package sanitization → requirements.linux.txt
        3. PostgreSQL driver auto-injection (psycopg2-binary, asyncpg)
        4. 4-tier pip install fallback chain
        """
        fw_config = _PYTHON_FRAMEWORK_CONFIG.get(framework, _PYTHON_FRAMEWORK_CONFIG["python"])
        base_image, port, env_block = fw_config

        if not install_command:
            install_command = "pip install -r requirements.txt"
        if not start_command:
            start_command = "python main.py"

        detected_port = _detect_port_from_command(start_command)
        if detected_port:
            port = detected_port

        # Run dependency normalization + injection if project_root known
        dep_info:     dict                     = {}
        sanitization: SanitizationResult | None = None
        use_linux_req  = False
        removed_comment = ""

        if project_root:
            try:
                dep_info     = normalize_python_dependencies(project_root)
                sanitization = dep_info.get("sanitization")

                if sanitization and sanitization.cleaned_path and sanitization.cleaned_path.exists():
                    use_linux_req = True
                    removed = sanitization.removed_packages + sanitization.windows_marker_packages
                    if removed:
                        removed_comment = (
                            f"# [Dependency Sanitizer] Removed {len(removed)} Windows-only pkg(s): "
                            + ", ".join(removed[:8])
                        )
                        logger.info(
                            "[Dockerfile][Python] Using requirements.linux.txt "
                            "(removed %d Windows pkg(s): %s)",
                            len(removed), ", ".join(removed),
                        )
                    else:
                        logger.debug("[Dockerfile][Python] requirements.linux.txt written (no removals)")

                # Auto-inject missing runtime deps (psycopg2-binary etc.)
                injected = inject_missing_python_deps(project_root)
                if injected:
                    logger.info(
                        "[Dockerfile][Python] Auto-injected %d dep(s): %s",
                        len(injected), ", ".join(injected),
                    )

            except Exception as exc:
                logger.warning("[Dockerfile][Python] Sanitization probe failed: %s", exc)

        # Determine install strategy
        has_pipfile = dep_info.get("has_pipfile", "pipenv" in install_command.lower())
        has_pyproj  = dep_info.get("has_pyproject_toml", "pyproject" in install_command)
        has_uv      = dep_info.get("has_uv_lock", False)

        if has_uv:
            copy_deps    = "COPY uv.lock pyproject.toml* requirements*.txt* ./"
            install_step = """\
RUN pip install --upgrade pip uv && \\
    uv pip install -r requirements.linux.txt --system 2>/dev/null || \\
    uv pip install -r requirements.txt --system 2>/dev/null || \\
    pip install -r requirements.linux.txt --no-cache-dir 2>/dev/null || \\
    pip install -r requirements.txt --no-cache-dir"""

        elif has_pipfile:
            copy_deps    = "COPY Pipfile* requirements*.txt* ./"
            install_step = """\
RUN pip install --upgrade pip pipenv && \\
    pipenv install --system --deploy --ignore-pipfile 2>/dev/null || \\
    pipenv install --system --ignore-pipfile 2>/dev/null || \\
    pip install -r requirements.linux.txt --no-cache-dir 2>/dev/null || \\
    pip install -r requirements.txt --no-cache-dir"""

        elif has_pyproj:
            copy_deps    = "COPY pyproject.toml* setup.* README* requirements*.txt* ./"
            install_step = """\
RUN pip install --upgrade pip setuptools wheel && \\
    pip install . --no-cache-dir 2>/dev/null || \\
    pip install -r requirements.linux.txt --no-cache-dir 2>/dev/null || \\
    pip install -r requirements.txt --no-cache-dir 2>/dev/null || \\
    pip install -e . --no-cache-dir"""

        else:
            req_file  = "requirements.linux.txt" if use_linux_req else "requirements.txt"
            copy_deps = "COPY requirements*.txt ./"
            install_step = f"""\
{removed_comment}
RUN pip install --upgrade pip setuptools wheel && \\
    pip install -r {req_file} --no-cache-dir || \\
    pip install -r {req_file} || \\
    pip install -r requirements.txt --no-cache-dir || \\
    (pip install --no-build-isolation -r {req_file} --no-cache-dir)""".strip()

        return f"""FROM {base_image}

WORKDIR /app

{env_block}

# System build dependencies (covers native extensions)
RUN apt-get update && apt-get install -y --no-install-recommends \\
    gcc g++ make \\
    build-essential \\
    libpq-dev \\
    libffi-dev \\
    libssl-dev \\
    curl \\
    git \\
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
{copy_deps}
{install_step}

# Copy application source
COPY . .

EXPOSE {port}

CMD {ExecutionEngine._to_cmd(start_command)}
"""

    # ── Shared helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _to_cmd(command: str) -> str:
        """Convert a shell command string to JSON-array Docker CMD (sh -c wrapper)."""
        if not command:
            return '["sh", "-c", "echo \'No start command defined\'"]'
        safe = command.replace("'", "'\\''")
        return f'["sh", "-c", "{safe}"]'

    @staticmethod
    def save_dockerfile(project_root: str, dockerfile_content: str) -> Path:
        """
        Write Dockerfile to the project root directory.
        Also ensures .dockerignore excludes node_modules/.next so stale local
        dependencies never pollute the Docker build layer.
        """
        root            = Path(project_root)
        dockerfile_path = root / "Dockerfile"
        dockerfile_path.write_text(dockerfile_content, encoding="utf-8")
        logger.info("[Dockerfile] Saved to %s", dockerfile_path)

        # Ensure node_modules is excluded from build context
        _ensure_dockerignore(root)

        return dockerfile_path

    # ── npm build-error recovery helpers ──────────────────────────────────────

    @staticmethod
    def _parse_missing_npm_packages(build_log_lines: list[str]) -> list[str]:
        """
        Parse Docker build log lines for missing npm module errors.

        Detects:
          - "Cannot find module 'X'"  (MODULE_NOT_FOUND)
          - "Module not found: Can't resolve 'X'"
          - "peer dep missing: X"
          - "npm ERR! missing: X"

        Returns deduplicated list of installable package names. Never raises.
        """
        missing: list[str] = []
        seen: set[str] = set()

        patterns = [
            _re.compile(r"Cannot find module ['\"](@?[a-zA-Z0-9@/._-]+)['\"]"),
            _re.compile(r"Module not found[^'\"]*['\"](@?[a-zA-Z0-9@/._-]+)['\"]"),
            _re.compile(r"Cannot resolve[^'\"]*['\"](@?[a-zA-Z0-9@/._-]+)['\"]"),
            _re.compile(r"Can't resolve ['\"](@?[a-zA-Z0-9@/._-]+)['\"]"),
            _re.compile(r"peer dep missing: (@?[a-zA-Z0-9@/._-]+)"),
            _re.compile(r"npm ERR! missing: (@?[a-zA-Z0-9@/._-]+)"),
            _re.compile(r"error TS2307: Cannot find module ['\"](@?[a-zA-Z0-9@/._-]+)['\"]"),
        ]

        # Built-in Node modules — not installable
        _skip = {".", "..", "/", "fs", "path", "http", "https", "os", "url",
                 "stream", "events", "util", "crypto", "buffer", "child_process",
                 "process", "module", "vm"}

        for line in build_log_lines:
            for pat in patterns:
                m = pat.search(line)
                if m:
                    pkg_raw = m.group(1)
                    if pkg_raw.startswith("@"):
                        parts = pkg_raw.split("/")
                        pkg   = "/".join(parts[:2])
                    else:
                        pkg = pkg_raw.split("/")[0]

                    if pkg and pkg not in _skip and pkg not in seen:
                        seen.add(pkg)
                        missing.append(pkg)
                    break

        return missing

    @staticmethod
    def _patch_dockerfile_with_packages(
        dockerfile_path: Path,
        packages: list[str],
        deployment_id: str,
    ) -> bool:
        """
        Patch Dockerfile to pre-install missing npm packages BEFORE `npm run build`.
        Returns True if patched, False if no build step found. Never raises.
        """
        try:
            content = dockerfile_path.read_text(encoding="utf-8")
            pkg_str = " ".join(packages)
            inject_line = (
                f"RUN npm install --save-dev {pkg_str} 2>/dev/null || npm install {pkg_str}"
            )

            build_triggers = (
                "RUN npm run build", "RUN pnpm run build",
                "RUN yarn build",    "RUN yarn run build",
            )
            lines = content.splitlines()
            for i, line in enumerate(lines):
                stripped = line.strip()
                if any(stripped.startswith(t) for t in build_triggers):
                    lines.insert(i, f"\n# [Auto-heal] Installing missing packages: {pkg_str}")
                    lines.insert(i + 1, inject_line)
                    dockerfile_path.write_text("\n".join(lines), encoding="utf-8")
                    _append_log(deployment_id, f"[Auto-heal] Patched Dockerfile: {pkg_str}")
                    logger.info("[Auto-heal] Patched Dockerfile with: %s", pkg_str)
                    return True
        except Exception as exc:
            logger.warning("[Auto-heal] Dockerfile patch failed: %s", exc)
        return False

    # ── Image Build ───────────────────────────────────────────────────────────

    @staticmethod
    def build_image(project_root: str, deployment_id: str) -> str:
        """
        Build a Docker image with automatic dependency healing.

        Step 1: Dependency healing
                - Node: heal_node_project() patches package.json + removes lockfile
                - Python: sanitize Windows packages + inject psycopg2-binary etc.
        Step 2: Primary Docker build (streams all output to DEPLOYMENT_LOGS)
        Step 3: Recovery — if BuildError, parse for MODULE_NOT_FOUND, patch
                Dockerfile, retry once with nocache=True

        Returns image_tag on success.
        Raises docker.errors.BuildError if all attempts fail.
        """
        client    = docker.from_env()
        image_tag = f"anti-gravity-{deployment_id}"
        root      = Path(project_root)

        logger.info("[Build] Starting image tag=%s root=%s", image_tag, project_root)
        _append_log(deployment_id, f"[Build] Building image: {image_tag}")

        # ── Step 1: Dependency healing ─────────────────────────────────────────
        try:
            has_package_json = (root / "package.json").exists()
            has_requirements = (
                (root / "requirements.txt").exists()
                or (root / "requirements.linux.txt").exists()
            )

            if has_package_json:
                heal = heal_node_project(project_root, deployment_id=deployment_id)
                if heal.modified:
                    _append_log(deployment_id, f"[Dependency Healer] {heal.summary}")
                    for pkg in heal.injected_deps:
                        _append_log(
                            deployment_id,
                            f"[Dependency Healer] Pre-injected into package.json: {pkg}",
                        )
                    if heal.removed_lock:
                        _append_log(
                            deployment_id,
                            "[Dependency Healer] Removed package-lock.json"
                            " → forcing clean npm install",
                        )
                elif not heal.errors:
                    _append_log(
                        deployment_id,
                        "[Dependency Healer] package.json is complete (no missing deps)",
                    )
                for err in heal.errors:
                    logger.warning("[Build][NodeHealer] %s", err)

            if has_requirements:
                san = sanitize_requirements(project_root, deployment_id)
                if san.was_modified:
                    removed = san.removed_packages + san.windows_marker_packages
                    _append_log(deployment_id, f"[Dependency Sanitizer] {san.summary}")
                    for pkg in removed:
                        _append_log(
                            deployment_id,
                            f"[Dependency Sanitizer] Removed Windows-only: {pkg}",
                        )
                    _append_log(
                        deployment_id,
                        "[Dependency Sanitizer] Linux-compatible requirements"
                        " generated → requirements.linux.txt",
                    )
                elif san.cleaned_path:
                    _append_log(
                        deployment_id,
                        "[Dependency Sanitizer] No Windows packages detected",
                    )

                injected = inject_missing_python_deps(project_root, deployment_id)
                for pkg in injected:
                    _append_log(
                        deployment_id,
                        f"[Dependency Healer] Auto-injected Python dep: {pkg}",
                    )
                if injected:
                    _append_log(
                        deployment_id,
                        f"[Dependency Healer] Injected {len(injected)} Python dep(s): "
                        + ", ".join(injected),
                    )

        except Exception as exc:
            logger.warning("[Build] Dependency healing error (non-fatal): %s", exc)
            _append_log(deployment_id, f"[Dependency Healer] Warning: {exc}")

        # ── Step 2: Primary Docker build ───────────────────────────────────────
        build_error_lines: list[str] = []

        def _run_build(nocache: bool = False) -> str:
            """Inner helper — streams build output; raises BuildError on failure."""
            nonlocal build_error_lines
            build_error_lines = []

            try:
                _image, log_stream = client.images.build(
                    path=project_root,
                    tag=image_tag,
                    rm=True,
                    forcerm=True,
                    nocache=nocache,
                )
            except docker.errors.BuildError as exc:
                for entry in exc.build_log:
                    for key in ("stream", "error"):
                        line = entry.get(key, "").strip()
                        if line:
                            build_error_lines.append(line)
                            prefix = "[Build][ERROR]" if key == "error" else "[Build]"
                            _append_log(deployment_id, f"{prefix} {line}")
                            logger.error("[Build][%s] %s: %s", image_tag, key, line)
                raise

            for entry in log_stream:
                for key in ("stream", "error"):
                    line = entry.get(key, "").strip()
                    if line:
                        prefix = "[Build][ERROR]" if key == "error" else "[Build]"
                        _append_log(deployment_id, f"{prefix} {line}")
                        if key == "error":
                            logger.error("[Build][%s] %s", image_tag, line)
                        else:
                            logger.debug("[Build][%s] %s", image_tag, line)
                detail = entry.get("errorDetail", {})
                if isinstance(detail, dict):
                    msg = detail.get("message", "").strip()
                    if msg:
                        _append_log(deployment_id, f"[Build][ERROR] {msg}")
                        logger.error("[Build][%s] errorDetail: %s", image_tag, msg)

            logger.info("[Build] Image %s built successfully", image_tag)
            return image_tag

        try:
            return _run_build(nocache=False)

        except docker.errors.BuildError:
            # ── Step 3: npm MODULE_NOT_FOUND recovery ──────────────────────────
            missing_pkgs = ExecutionEngine._parse_missing_npm_packages(build_error_lines)

            if not missing_pkgs:
                logger.error("[Build] No auto-recoverable npm packages found — raising")
                raise

            _append_log(
                deployment_id,
                f"[Auto-heal] Build failed — detected {len(missing_pkgs)} missing "
                "npm package(s): " + ", ".join(missing_pkgs),
            )
            logger.info("[Auto-heal] Attempting recovery: %s", missing_pkgs)

            dockerfile_path = root / "Dockerfile"
            patched = ExecutionEngine._patch_dockerfile_with_packages(
                dockerfile_path, missing_pkgs, deployment_id
            )
            if not patched:
                _append_log(
                    deployment_id,
                    "[Auto-heal] Could not patch Dockerfile — raising original error",
                )
                raise

            _append_log(deployment_id, "[Auto-heal] Retrying build (nocache)...")
            logger.info("[Auto-heal] Retrying build after Dockerfile patch")

            try:
                return _run_build(nocache=True)
            except docker.errors.BuildError as retry_exc:
                _append_log(
                    deployment_id,
                    "[Auto-heal] Retry build also failed — deployment error",
                )
                logger.error("[Auto-heal] Retry failed: %s", retry_exc)
                raise

    # ── Container Run ─────────────────────────────────────────────────────────

    @classmethod
    def run_container(
        cls,
        image_tag: str,
        container_name: str,
        service: dict,
    ) -> dict:
        """
        Run a container from the given image.
        Returns {"container": <Container>, "host_port": <str>}.
        Raises on failure — caller wraps in try/except.
        """
        from app.services.container_lifecycle import ContainerLifecycleService

        client        = docker.from_env()
        runtime       = str(service.get("runtime", "node")).lower()
        start_cmd     = str(service.get("start_command", ""))
        framework     = str(service.get("framework", "")).lower()

        # Port priority: command → framework table → runtime default
        container_port = _detect_port_from_command(start_cmd)
        if not container_port:
            if runtime == "python":
                container_port = _PYTHON_FRAMEWORK_CONFIG.get(
                    framework, _PYTHON_FRAMEWORK_CONFIG["python"]
                )[1]
            else:
                container_port = _NODE_FRAMEWORK_CONFIG.get(
                    framework, _NODE_FRAMEWORK_CONFIG["node"]
                )[1]

        logger.info(
            "[Container] Running %s from image %s (port=%d)",
            container_name, image_tag, container_port,
        )

        container = client.containers.run(
            image=image_tag,
            detach=True,
            ports={f"{container_port}/tcp": None},
            name=f"container-{container_name}",
        )

        container.reload()
        ContainerLifecycleService.stream_container_logs(container, container_name)

        ports     = container.attrs["NetworkSettings"]["Ports"]
        port_data = ports.get(f"{container_port}/tcp")

        if not port_data:
            try:
                last_logs = container.logs(tail=30).decode("utf-8", errors="ignore")
                _append_log(
                    container_name,
                    f"[Error] Container exited. Last output:\n{last_logs}",
                )
                logger.error(
                    "[Container] %s exited immediately. Logs:\n%s",
                    container_name, last_logs,
                )
            except Exception:
                pass
            raise RuntimeError(
                f"No port mapping for container-{container_name} on "
                f"{container_port}/tcp — container may have exited."
            )

        host_port = port_data[0]["HostPort"]
        logger.info(
            "[Container] %s started: id=%s host_port=%s",
            container_name, container.id[:12], host_port,
        )

        return {"container": container, "host_port": host_port}