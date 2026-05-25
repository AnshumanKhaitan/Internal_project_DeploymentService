"""
Anti Gravity Deployments — Node.js Dependency Healer

Proactively patches package.json BEFORE Docker image build so that
`npm install` in the Docker layer already includes all required packages.

This is the correct fix for Next.js/Turbopack build failures caused by
missing dependencies (e.g. @tailwindcss/postcss, postcss, autoprefixer):

  CORRECT order (what this module ensures):
    1. Scan project source for missing deps
    2. Inject into package.json
    3. COPY package.json → npm install (includes everything)
    4. npm run build  ✓

  WRONG order (what retry-after-failure does):
    1. npm install (without missing deps)
    2. npm run build FAILS
    3. Install missing package in a later layer
    4. npm run build still fails (layer cache + stale node_modules)

Usage:
    from app.services.node_dependency_healer import heal_node_project
    result = heal_node_project(project_root, framework, deployment_id)
    # result.injected_deps  → list of what was added
    # result.modified       → bool
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ── Framework-aware dependency presets ────────────────────────────────────────
#
# These are the minimal devDependencies that MUST be present for each
# framework/toolchain combination to build correctly on Linux.
# If any of these are missing from package.json, we inject them.

_FRAMEWORK_REQUIRED_DEV_DEPS: dict[str, dict[str, str]] = {
    "nextjs": {
        # PostCSS / Tailwind toolchain — most common Next.js build failure
        "postcss":               "^8.4.0",
        "autoprefixer":          "^10.4.0",
        "@tailwindcss/postcss":  "^4.0.0",
    },
    "react": {
        "postcss":               "^8.4.0",
        "autoprefixer":          "^10.4.0",
    },
    "vite": {
        "postcss":               "^8.4.0",
        "autoprefixer":          "^10.4.0",
    },
}

# Packages that are commonly added to devDependencies but needed at build time
_ALWAYS_DEV: frozenset[str] = frozenset({
    "postcss",
    "autoprefixer",
    "@tailwindcss/postcss",
    "tailwindcss",
    "@types/node",
    "@types/react",
    "@types/react-dom",
    "typescript",
    "eslint",
})

# Signals that Tailwind CSS is being used in the project
_TAILWIND_SIGNALS: tuple[str, ...] = (
    "tailwindcss",
    "@tailwindcss",
    "tailwind.config",
    "tailwind.config.js",
    "tailwind.config.ts",
    "tailwind.config.mjs",
    "from 'tailwindcss'",
    'from "tailwindcss"',
    "@import 'tailwindcss'",
    '@import "tailwindcss"',
    "@apply ",          # Tailwind utility class directive
    "bg-",              # Tailwind className pattern (heuristic)
)

# Signals that PostCSS is configured
_POSTCSS_SIGNALS: tuple[str, ...] = (
    "postcss.config",
    "postcss.config.js",
    "postcss.config.ts",
    "postcss.config.mjs",
    "@tailwindcss/postcss",
    "postcss-import",
    "postcss-nesting",
)


@dataclass
class HealResult:
    """Result of healing a Node.js project's dependencies."""
    project_root:  Path
    modified:      bool               = False
    injected_deps: list[str]          = field(default_factory=list)
    removed_lock:  bool               = False
    backup_path:   Optional[Path]     = None
    summary:       str                = ""
    errors:        list[str]          = field(default_factory=list)


# ── File scanning helpers ──────────────────────────────────────────────────────

def _read_safe(path: Path) -> str:
    """Read file content safely. Returns '' on any failure."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _scan_for_tailwind(project_root: Path) -> bool:
    """Return True if the project uses Tailwind CSS."""
    # Fast check: tailwind.config.* file exists
    for name in ("tailwind.config.js", "tailwind.config.ts",
                 "tailwind.config.mjs", "tailwind.config.cjs"):
        if (project_root / name).exists():
            logger.debug("[NodeHealer] Found %s → Tailwind detected", name)
            return True

    # Check postcss.config.* for @tailwindcss/postcss reference
    for name in ("postcss.config.js", "postcss.config.ts",
                 "postcss.config.mjs", "postcss.config.cjs"):
        p = project_root / name
        if p.exists() and "@tailwindcss" in _read_safe(p):
            return True

    # Light scan of CSS / global files
    css_files = list(project_root.glob("**/*.css"))[:30]
    for css_file in css_files:
        try:
            if css_file.stat().st_size > 200_000:
                continue
            content = _read_safe(css_file).lower()
            for signal in ("@tailwind ", "@apply ", "@import 'tailwindcss", '@import "tailwindcss'):
                if signal in content:
                    logger.debug("[NodeHealer] Tailwind directive in %s", css_file.name)
                    return True
        except Exception:
            pass

    return False


def _scan_for_postcss(project_root: Path) -> bool:
    """Return True if the project has PostCSS config."""
    for name in ("postcss.config.js", "postcss.config.ts",
                 "postcss.config.mjs", "postcss.config.cjs",
                 ".postcssrc", ".postcssrc.js", ".postcssrc.json"):
        if (project_root / name).exists():
            return True
    return False


def _get_all_package_deps(pkg: dict) -> set[str]:
    """Return all declared deps (deps + devDeps + peerDeps) normalized."""
    all_deps: set[str] = set()
    for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        for name in pkg.get(key, {}):
            all_deps.add(name.lower().replace("_", "-"))
    return all_deps


# ── Main healing function ──────────────────────────────────────────────────────

def heal_node_project(
    project_root: str | Path,
    framework: str = "",
    deployment_id: str = "",
) -> HealResult:
    """
    Proactively heal a Node.js project's package.json before Docker build.

    Steps:
      1. Read package.json
      2. Detect framework-specific missing dependencies
      3. Detect Tailwind / PostCSS usage
      4. Inject all missing deps into devDependencies
      5. Write patched package.json (original backed up as package.json.orig)
      6. Remove package-lock.json if it would conflict with injected deps

    The Dockerfile's `npm install` step will then install the complete
    dependency set in a single clean layer.

    Never raises. Returns HealResult.
    """
    root   = Path(project_root)
    fw     = framework.lower().strip()
    tag    = f"[NodeHealer][{deployment_id}]" if deployment_id else "[NodeHealer]"
    result = HealResult(project_root=root)

    pkg_path = root / "package.json"
    if not pkg_path.exists():
        logger.debug("%s No package.json found — skipping", tag)
        result.summary = "No package.json found"
        return result

    # ── Read package.json ──────────────────────────────────────────────────
    try:
        pkg_raw  = pkg_path.read_text(encoding="utf-8")
        pkg_data = json.loads(pkg_raw)
    except Exception as exc:
        result.errors.append(f"Cannot parse package.json: {exc}")
        result.summary = f"Parse error: {exc}"
        logger.warning("%s Cannot parse package.json: %s", tag, exc)
        return result

    # All currently declared deps (normalized)
    declared = _get_all_package_deps(pkg_data)
    to_inject: dict[str, str] = {}   # name → version

    # ── 1. Framework preset injection ─────────────────────────────────────
    if fw in _FRAMEWORK_REQUIRED_DEV_DEPS:
        for pkg_name, version in _FRAMEWORK_REQUIRED_DEV_DEPS[fw].items():
            norm = pkg_name.lower().replace("_", "-")
            if norm not in declared:
                to_inject[pkg_name] = version
                logger.info("%s [Preset] Missing %s dep: %s", tag, fw, pkg_name)

    # ── 2. Tailwind detection → inject postcss toolchain ──────────────────
    uses_tailwind = _scan_for_tailwind(root)
    uses_postcss  = uses_tailwind or _scan_for_postcss(root)

    if uses_tailwind:
        logger.info("%s Tailwind CSS detected", tag)
        for pkg_name, version in {
            "tailwindcss":          "^3.4.0",
            "postcss":              "^8.4.0",
            "autoprefixer":         "^10.4.0",
            "@tailwindcss/postcss": "^4.0.0",
        }.items():
            norm = pkg_name.lower().replace("_", "-")
            if norm not in declared:
                to_inject[pkg_name] = version

    elif uses_postcss:
        logger.info("%s PostCSS detected (no Tailwind)", tag)
        for pkg_name, version in {
            "postcss":     "^8.4.0",
            "autoprefixer": "^10.4.0",
        }.items():
            norm = pkg_name.lower().replace("_", "-")
            if norm not in declared:
                to_inject[pkg_name] = version

    # ── 3. Anti Gravity self-detection (recursive deployment) ─────────────
    # When deploying Anti Gravity's own frontend (Next.js + Tailwind v4):
    # Inject the exact packages needed for @tailwindcss/postcss v4 build
    if fw == "nextjs" and uses_tailwind:
        tw4_pkgs = {
            "@tailwindcss/postcss": "^4.0.0",
            "tailwindcss":          "^4.0.0",
            "postcss":              "^8.4.0",
            "autoprefixer":         "^10.4.0",
        }
        for pkg_name, version in tw4_pkgs.items():
            norm = pkg_name.lower().replace("_", "-")
            if norm not in declared:
                to_inject[pkg_name] = version

    if not to_inject:
        logger.info("%s No missing deps detected — package.json is complete", tag)
        result.summary = "No missing dependencies detected"
        return result

    # ── 4. Backup original package.json ───────────────────────────────────
    try:
        backup = root / "package.json.orig"
        shutil.copy2(pkg_path, backup)
        result.backup_path = backup
        logger.info("%s Backed up package.json → package.json.orig", tag)
    except Exception as exc:
        logger.warning("%s Could not backup package.json: %s", tag, exc)

    # ── 5. Inject into devDependencies ────────────────────────────────────
    if "devDependencies" not in pkg_data:
        pkg_data["devDependencies"] = {}

    for pkg_name, version in to_inject.items():
        pkg_data["devDependencies"][pkg_name] = version
        result.injected_deps.append(pkg_name)
        logger.info("%s Injected: %s@%s", tag, pkg_name, version)

    # ── 6. Write patched package.json ─────────────────────────────────────
    try:
        patched_json = json.dumps(pkg_data, indent=2, ensure_ascii=False)
        pkg_path.write_text(patched_json + "\n", encoding="utf-8")
        result.modified = True
        logger.info(
            "%s Wrote patched package.json with %d new deps: %s",
            tag, len(to_inject), ", ".join(to_inject.keys()),
        )
    except Exception as exc:
        result.errors.append(f"Write failed: {exc}")
        logger.error("%s Failed to write package.json: %s", tag, exc)
        # Restore backup
        if result.backup_path and result.backup_path.exists():
            try:
                shutil.copy2(result.backup_path, pkg_path)
                logger.info("%s Restored package.json from backup", tag)
            except Exception:
                pass
        result.summary = f"Write error: {exc}"
        return result

    # ── 7. Remove package-lock.json to force clean install ────────────────
    # package-lock.json pins exact versions; if it doesn't include our
    # newly injected packages, npm ci will fail and npm install may skip them.
    lock_path = root / "package-lock.json"
    if lock_path.exists():
        try:
            lock_path.unlink()
            result.removed_lock = True
            logger.info(
                "%s Removed package-lock.json (force clean install for injected deps)", tag
            )
        except Exception as exc:
            logger.warning("%s Could not remove package-lock.json: %s", tag, exc)

    # Also remove yarn.lock if present and we're using npm
    yarn_lock = root / "yarn.lock"
    if yarn_lock.exists() and not _has_yarn(pkg_data):
        try:
            yarn_lock.unlink()
            logger.debug("%s Removed stale yarn.lock", tag)
        except Exception:
            pass

    result.summary = (
        f"Injected {len(result.injected_deps)} dep(s) into package.json: "
        + ", ".join(result.injected_deps)
        + (" | Removed package-lock.json for clean install" if result.removed_lock else "")
    )
    return result


def _has_yarn(pkg_data: dict) -> bool:
    """Check if package.json has a yarn packageManager field."""
    pm = pkg_data.get("packageManager", "")
    return "yarn" in str(pm).lower()


# ── Dockerfile generator for healed projects ──────────────────────────────────

def build_nextjs_dockerfile_healed(
    install_command: str,
    use_pnpm: bool = False,
    use_yarn: bool = False,
    extra_packages: list[str] | None = None,
) -> str:
    """
    Generate a Next.js production Dockerfile that:
    1. COPYs the already-patched package.json (from heal_node_project)
    2. Runs a clean npm install (no lockfile → installs all deps fresh)
    3. Runs npm run build
    4. Starts with npm run start

    The key difference from _nextjs_dockerfile_simple is:
    - Uses `npm install` (not `npm ci`) so it reads patched package.json
    - Does NOT use --legacy-peer-deps which can mask resolution failures
    - Clears node_modules if they happen to be in build context
    """
    extra = extra_packages or []
    extra_install = ""
    if extra:
        pkg_str = " ".join(extra)
        extra_install = f"RUN npm install {pkg_str} --save-dev 2>/dev/null || true"

    if use_pnpm:
        return f"""FROM node:20-alpine

WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV HOSTNAME=0.0.0.0
ENV PORT=3000

# Install pnpm
RUN npm install -g pnpm

# Install deps from patched package.json (no lockfile → always fresh)
COPY package.json ./
RUN rm -rf node_modules && pnpm install --no-frozen-lockfile

{extra_install}

COPY . .

RUN pnpm run build

EXPOSE 3000

CMD ["sh", "-c", "pnpm run start"]
"""

    if use_yarn:
        return f"""FROM node:20-alpine

WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV HOSTNAME=0.0.0.0
ENV PORT=3000

# Install deps from patched package.json (no lockfile → always fresh)
COPY package.json ./
RUN rm -rf node_modules && yarn install --no-immutable 2>/dev/null || yarn install

{extra_install}

COPY . .

RUN yarn build

EXPOSE 3000

CMD ["sh", "-c", "yarn start"]
"""

    # npm (default)
    return f"""FROM node:20-alpine

WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV HOSTNAME=0.0.0.0
ENV PORT=3000

# Install deps from patched package.json (no lockfile → always fresh)
# NOTE: package.json has been pre-patched by Anti Gravity dependency healer
COPY package.json ./
RUN rm -rf node_modules && npm install --include=dev

{extra_install}

COPY . .

# Build Next.js production bundle
RUN npm run build

EXPOSE 3000

CMD ["sh", "-c", "npm run start"]
"""
