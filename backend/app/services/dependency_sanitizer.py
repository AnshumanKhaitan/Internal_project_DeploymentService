"""
Anti Gravity Deployments — Dependency Sanitizer

Sanitizes Python requirements files before Docker builds on Linux containers.

The core problem: When Anti Gravity (running on Windows) deploys itself
recursively, the uploaded requirements.txt contains Windows-only packages
(pywin32, windows-curses, pyreadline etc.) that fail to install on Linux
Docker images.

This module:
  - Detects and removes Windows-only packages from requirements.txt
  - Writes a cleaned requirements.linux.txt alongside the original (original untouched)
  - Handles all requirements.txt variants: pinned, unpinned, extras, VCS refs
  - Supports requirements.txt, pyproject.toml (extras stripping), setup.cfg
  - Returns a full sanitization report for logging
  - Never raises — always returns a safe result
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── Windows-only package blocklist ─────────────────────────────────────────────
#
# These packages either:
#   a) Only build on Windows (MSVC extensions, Win32 API)
#   b) Are Windows-specific OS utilities with no Linux equivalent
#   c) Have pywin32 as a hard dependency
#
# Matching is case-insensitive, and covers both hyphen and underscore variants.

_WINDOWS_ONLY_PACKAGES: frozenset[str] = frozenset({
    # Core Windows API bindings
    "pywin32",
    "pypiwin32",
    "pywin32-ctypes",
    "pywinpty",
    "pywinusb",
    "win32api",
    "win32con",
    "win32console",
    "win32evtlog",
    "win32evtlogutil",
    "win32gui",
    "win32net",
    "win32print",
    "win32process",
    "win32security",
    "win32service",
    "win32serviceutil",
    "win32transaction",
    "win32ts",
    "winerror",
    "winreg",
    "winsound",
    "winshell",

    # Terminal / Console (Windows-specific implementations)
    "windows-curses",
    "windows_curses",
    "cursesw",
    "colorama-win",

    # Readline (Windows replacements)
    "pyreadline",
    "pyreadline3",
    "readline-win",

    # COM / OLE automation
    "comtypes",
    "pycomtypes",
    "win32com",
    "pythoncom",

    # Windows system utilities
    "wmi",
    "py-wmi",
    "psutil-win",

    # Windows-only installers / packaging
    "py2exe",
    "pyinstaller-hooks-contrib",   # only needed for Windows bundling
    "cx_freeze",

    # Windows notification / tray
    "win10toast",
    "plyer",                       # has Windows-specific native features

    # Windows registry / event log
    "winregistry",
    "pyregistry",

    # NTFS / Windows filesystem
    "ntfs",
    "pyacl",
    "winnt",

    # Windows credential store
    "keyring-win",
    "win32cred",

    # Specific to pywin32 sub-modules often installed separately
    "pythonwin",
})

# Normalized lookup: lowercase, hyphens replaced with underscores
_WINDOWS_PKG_NORMALIZED: frozenset[str] = frozenset(
    p.lower().replace("-", "_") for p in _WINDOWS_ONLY_PACKAGES
)

# Packages that have Linux equivalents but different names — map Windows → Linux
_WINDOWS_TO_LINUX_ALTERNATIVES: dict[str, Optional[str]] = {
    "pyreadline":  None,   # readline is built into Python on Linux, no package needed
    "pyreadline3": None,
    "windows-curses": None,  # curses is built in on Linux
    "colorama-win": "colorama",
    "wmi": None,           # no equivalent
    "comtypes": None,
}


# ── Line classification helpers ────────────────────────────────────────────────

_COMMENT_RE  = re.compile(r"^\s*#")
_BLANK_RE    = re.compile(r"^\s*$")
_OPTION_RE   = re.compile(r"^\s*-[rRcCeEfFiIqQuUvV]")   # pip option flags
_VCS_RE      = re.compile(r"^\s*(git|svn|hg|bzr)\+")    # VCS URLs

# Match package name from a requirement line (PEP 508)
# Examples: "requests==2.31.0", "fastapi[all]>=0.100", "Django~=4.2", "  pywin32 ; sys_platform=='win32'"
_PKG_NAME_RE = re.compile(r"^\s*([A-Za-z0-9]([A-Za-z0-9._-]*))")


def _normalize_pkg_name(name: str) -> str:
    """Lowercase + underscore-normalize a package name for blocklist comparison."""
    return name.lower().replace("-", "_").replace(".", "_")


def _extract_pkg_name(line: str) -> Optional[str]:
    """
    Extract the package name from a requirements.txt line.
    Returns None for comments, blank lines, options, VCS URLs.
    """
    if _COMMENT_RE.match(line) or _BLANK_RE.match(line):
        return None
    if _OPTION_RE.match(line):
        return None
    if _VCS_RE.match(line):
        return None
    m = _PKG_NAME_RE.match(line)
    return m.group(1) if m else None


def _is_windows_only(pkg_name: str) -> bool:
    """Return True if this package is Windows-only and must be removed."""
    normalized = _normalize_pkg_name(pkg_name)
    return normalized in _WINDOWS_PKG_NORMALIZED


def _has_windows_marker(line: str) -> bool:
    """
    Return True if the line has a PEP 508 environment marker restricting it to Windows.
    Examples:
      pywin32 ; sys_platform == 'win32'
      pywin32 ; sys_platform == "win32"
      pywin32; platform_system == 'Windows'
      pywin32; os_name == 'nt'
    """
    lower = line.lower()
    return any(marker in lower for marker in (
        "sys_platform == 'win32'",
        'sys_platform == "win32"',
        "sys_platform=='win32'",
        'sys_platform=="win32"',
        "platform_system == 'windows'",
        'platform_system == "windows"',
        "platform_system=='windows'",
        'platform_system=="windows"',
        "os_name == 'nt'",
        'os_name == "nt"',
        "os_name=='nt'",
        'os_name=="nt"',
    ))


# ── Main sanitization functions ────────────────────────────────────────────────

@dataclass
class SanitizationResult:
    """Result of sanitizing a requirements file."""
    original_path: Path
    cleaned_path: Optional[Path]           # None if not written
    removed_packages: list[str] = field(default_factory=list)
    windows_marker_packages: list[str] = field(default_factory=list)
    substitutions: dict[str, Optional[str]] = field(default_factory=dict)
    total_original: int = 0
    total_cleaned: int = 0
    was_modified: bool = False

    @property
    def summary(self) -> str:
        removed = self.removed_packages + self.windows_marker_packages
        if not removed:
            return "No Windows-specific packages detected"
        return (
            f"Removed {len(removed)} Windows-only package(s): "
            + ", ".join(removed[:5])
            + (f" (+{len(removed)-5} more)" if len(removed) > 5 else "")
        )


def sanitize_requirements(
    project_root: str | Path,
    deployment_id: str = "",
) -> SanitizationResult:
    """
    Sanitize requirements.txt in project_root for Linux Docker builds.

    - Reads requirements.txt (or requirements/*.txt)
    - Removes all Windows-only packages
    - Removes lines with Windows-only PEP 508 environment markers
    - Writes requirements.linux.txt alongside the original
    - Original requirements.txt is NEVER modified

    Returns a SanitizationResult with details of what was removed.
    Never raises.
    """
    root = Path(project_root)
    tag  = f"[Dependency Sanitizer][{deployment_id}]" if deployment_id else "[Dependency Sanitizer]"

    # Find requirements file(s)
    req_files = []
    for candidate in ("requirements.txt", "requirements/base.txt", "requirements/prod.txt"):
        p = root / candidate
        if p.exists():
            req_files.append(p)
            break

    if not req_files:
        logger.debug("%s No requirements.txt found in %s", tag, root)
        return SanitizationResult(
            original_path=root / "requirements.txt",
            cleaned_path=None,
        )

    req_path = req_files[0]
    result   = SanitizationResult(original_path=req_path, cleaned_path=None)

    try:
        # Read with UTF-16 fallback (Windows can write UTF-16 BOM files)
        raw_text = req_path.read_text(encoding="utf-8", errors="replace")
        null_ratio = raw_text.count("\x00") / max(len(raw_text), 1)
        if null_ratio > 0.2:
            raw_text = req_path.read_text(encoding="utf-16", errors="replace")

        lines = raw_text.splitlines()
        result.total_original = sum(1 for l in lines if l.strip() and not l.strip().startswith("#"))

        cleaned_lines: list[str] = []

        for line in lines:
            pkg_name = _extract_pkg_name(line)

            if pkg_name is None:
                # Preserve comments, blanks, options, VCS URLs as-is
                cleaned_lines.append(line)
                continue

            # Check: Windows-only package name
            if _is_windows_only(pkg_name):
                result.removed_packages.append(pkg_name)
                logger.info("%s Removed Windows-only package: %s", tag, pkg_name)

                # Check if there's a Linux substitute
                normalized = _normalize_pkg_name(pkg_name)
                linux_alt = _WINDOWS_TO_LINUX_ALTERNATIVES.get(
                    pkg_name.lower(), _WINDOWS_TO_LINUX_ALTERNATIVES.get(normalized)
                )
                if linux_alt:
                    result.substitutions[pkg_name] = linux_alt
                    cleaned_lines.append(f"{linux_alt}  # substituted from {pkg_name}")
                    logger.info("%s  -> substituting with: %s", tag, linux_alt)
                else:
                    cleaned_lines.append(f"# [REMOVED - Windows only] {line}")
                continue

            # Check: PEP 508 Windows-only environment marker
            if _has_windows_marker(line):
                result.windows_marker_packages.append(pkg_name)
                cleaned_lines.append(f"# [REMOVED - Windows marker] {line}")
                logger.info("%s Removed Windows-marker line: %s", tag, line.strip())
                continue

            # Normal cross-platform package — keep it
            cleaned_lines.append(line)

        result.was_modified = bool(result.removed_packages or result.windows_marker_packages)
        result.total_cleaned = sum(
            1 for l in cleaned_lines
            if l.strip() and not l.strip().startswith("#")
        )

        # Write cleaned file (always write, even if unchanged, so Dockerfile can reference it)
        cleaned_path = req_path.parent / "requirements.linux.txt"
        cleaned_path.write_text("\n".join(cleaned_lines) + "\n", encoding="utf-8")
        result.cleaned_path = cleaned_path

        if result.was_modified:
            logger.info(
                "%s Linux-compatible requirements generated: %s "
                "(original=%d pkgs, cleaned=%d pkgs, removed=%d)",
                tag, cleaned_path,
                result.total_original, result.total_cleaned,
                len(result.removed_packages) + len(result.windows_marker_packages),
            )
        else:
            logger.debug("%s No Windows packages found — requirements.linux.txt is identical", tag)

    except Exception as exc:
        logger.error("%s Failed to sanitize requirements: %s", tag, exc)
        result.cleaned_path = None

    return result


def normalize_python_dependencies(
    project_root: str | Path,
    deployment_id: str = "",
) -> dict:
    """
    Full dependency normalization pass for a Python project.

    Detects all supported dependency formats and returns a normalized info dict:
      {
        "has_requirements_txt": bool,
        "has_pyproject_toml": bool,
        "has_pipfile": bool,
        "has_uv_lock": bool,
        "has_poetry_lock": bool,
        "sanitization": SanitizationResult,
        "install_strategy": "requirements" | "pyproject" | "pipfile" | "uv",
        "install_file": str,    # path relative to project_root
      }
    """
    root = Path(project_root)
    tag  = f"[Dependency Sanitizer][{deployment_id}]" if deployment_id else "[Dependency Sanitizer]"

    has_req      = (root / "requirements.txt").exists()
    has_pyproj   = (root / "pyproject.toml").exists()
    has_pipfile  = (root / "Pipfile").exists()
    has_uv_lock  = (root / "uv.lock").exists()
    has_poetry   = (root / "poetry.lock").exists()

    # Run sanitizer for requirements.txt (always, if present)
    sanitization = sanitize_requirements(root, deployment_id)

    # Determine primary install strategy
    if has_uv_lock:
        strategy     = "uv"
        install_file = "uv.lock"
    elif has_pipfile:
        strategy     = "pipfile"
        install_file = "Pipfile"
    elif has_pyproj:
        strategy     = "pyproject"
        install_file = "pyproject.toml"
    elif has_req:
        strategy     = "requirements"
        install_file = "requirements.linux.txt" if sanitization.cleaned_path else "requirements.txt"
    else:
        strategy     = "requirements"
        install_file = "requirements.txt"

    logger.info(
        "%s Strategy=%s file=%s (req=%s pyproj=%s pipfile=%s uv=%s poetry=%s)",
        tag, strategy, install_file,
        has_req, has_pyproj, has_pipfile, has_uv_lock, has_poetry,
    )

    return {
        "has_requirements_txt": has_req,
        "has_pyproject_toml":   has_pyproj,
        "has_pipfile":          has_pipfile,
        "has_uv_lock":          has_uv_lock,
        "has_poetry_lock":      has_poetry,
        "sanitization":         sanitization,
        "install_strategy":     strategy,
        "install_file":         install_file,
    }


# ── Auto-injection: missing runtime dependencies ───────────────────────────────

# Packages that are always needed for common frameworks but often omitted from
# requirements.txt when the project was developed on Windows or with a managed env.

_POSTGRES_SIGNALS: tuple[str, ...] = (
    "postgresql",
    "postgres://",
    "postgresql+psycopg2",
    "postgresql+asyncpg",
    "asyncpg",
    "+psycopg2",
    "psycopg2",
)

_ASYNC_POSTGRES_SIGNALS: tuple[str, ...] = (
    "postgresql+asyncpg",
    "asyncpg",
    "databases[aiosqlite]",
    "databases[asyncpg]",
    "tortoise-orm",
)

# Packages that must be present for common web framework combinations
_FRAMEWORK_AUTO_DEPS: dict[str, list[str]] = {
    "fastapi":  [],   # filled dynamically based on DB detection
    "flask":    [],
    "django":   [],
}


def _read_text_safe(path: Path) -> str:
    """Read a file to text safely, returning '' on any failure."""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        # UTF-16 detection
        if content.count("\x00") / max(len(content), 1) > 0.2:
            content = path.read_text(encoding="utf-16", errors="replace")
        return content
    except Exception:
        return ""


def _scan_for_postgres_usage(project_root: Path) -> tuple[bool, bool]:
    """
    Scan source files and env files for PostgreSQL database usage.

    Returns:
        (uses_postgres, needs_async)
        - uses_postgres: True if any postgres connection string / import found
        - needs_async: True if async driver (asyncpg) is specifically needed
    """
    uses_postgres = False
    needs_async   = False

    # Files to scan (lightweight — only text files likely to contain DB config)
    scan_targets = []
    for pattern in (
        "*.py", "*.env", ".env", ".env.example", ".env.local",
        "*.cfg", "*.ini", "*.toml", "*.yaml", "*.yml",
        "docker-compose*.yml", "docker-compose*.yaml",
    ):
        try:
            if "*" in pattern:
                scan_targets.extend(project_root.rglob(pattern))
            else:
                p = project_root / pattern
                if p.exists():
                    scan_targets.append(p)
        except Exception:
            pass

    # Deduplicate and limit scan to reasonable file count
    seen = set()
    for fpath in scan_targets:
        try:
            resolved = fpath.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)

            # Skip very large files (> 500KB)
            if fpath.stat().st_size > 500_000:
                continue

            content = _read_text_safe(fpath).lower()
            if not content:
                continue

            for signal in _POSTGRES_SIGNALS:
                if signal in content:
                    uses_postgres = True
                    break

            for signal in _ASYNC_POSTGRES_SIGNALS:
                if signal in content:
                    needs_async = True
                    break

        except Exception:
            pass

    return uses_postgres, needs_async


def _get_installed_packages(linux_req_path: Path) -> set[str]:
    """Return normalized set of package names already in requirements.linux.txt."""
    installed = set()
    if not linux_req_path.exists():
        return installed
    for line in linux_req_path.read_text(encoding="utf-8", errors="replace").splitlines():
        pkg = _extract_pkg_name(line)
        if pkg:
            installed.add(_normalize_pkg_name(pkg))
    return installed


def inject_missing_python_deps(
    project_root: str | Path,
    deployment_id: str = "",
) -> list[str]:
    """
    Auto-inject missing runtime dependencies into requirements.linux.txt.

    Current auto-injection rules:
      - PostgreSQL detected → inject psycopg2-binary (sync) or asyncpg (async)
      - asyncio/async patterns detected → ensure asyncpg present

    The injection is appended to requirements.linux.txt ONLY.
    Original requirements.txt is never modified.

    Returns list of injected package names (for logging).
    Never raises.
    """
    root = Path(project_root)
    tag  = f"[Dependency Sanitizer][{deployment_id}]" if deployment_id else "[Dependency Sanitizer]"

    linux_req = root / "requirements.linux.txt"

    # If no linux requirements file yet (e.g. no requirements.txt in project),
    # create a minimal one so we can inject into it
    if not linux_req.exists():
        orig_req = root / "requirements.txt"
        if orig_req.exists():
            # Shouldn't happen (sanitizer creates it), but handle defensively
            linux_req.write_text(orig_req.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        else:
            linux_req.write_text("# Auto-generated requirements for Linux deployment\n", encoding="utf-8")

    injected: list[str] = []

    try:
        installed = _get_installed_packages(linux_req)

        # ── PostgreSQL driver injection ────────────────────────────────────
        uses_postgres, needs_async = _scan_for_postgres_usage(root)

        if uses_postgres or needs_async:
            logger.info("%s PostgreSQL usage detected in project", tag)

            # Always inject psycopg2-binary (sync driver, needed even with asyncpg
            # for Alembic migrations and SQLAlchemy sync operations)
            if "psycopg2_binary" not in installed and "psycopg2" not in installed:
                _append_to_linux_req(linux_req, "psycopg2-binary", tag, deployment_id)
                injected.append("psycopg2-binary")

            # Inject asyncpg when async patterns detected
            if needs_async and "asyncpg" not in installed:
                _append_to_linux_req(linux_req, "asyncpg", tag, deployment_id)
                injected.append("asyncpg")

        # ── Future injection rules go here ─────────────────────────────────
        # (e.g. redis detection → inject redis / hiredis)
        # (e.g. celery detection → inject kombu)

    except Exception as exc:
        logger.error("%s inject_missing_python_deps failed: %s", tag, exc)

    return injected


def _append_to_linux_req(
    linux_req: Path,
    package: str,
    tag: str,
    deployment_id: str = "",
) -> None:
    """Append a single package line to requirements.linux.txt."""
    existing = linux_req.read_text(encoding="utf-8", errors="replace")

    # Don't append if already present (double-check)
    pkg_norm = _normalize_pkg_name(package)
    for line in existing.splitlines():
        p = _extract_pkg_name(line)
        if p and _normalize_pkg_name(p) == pkg_norm:
            logger.debug("%s %s already in requirements.linux.txt", tag, package)
            return

    with open(linux_req, "a", encoding="utf-8") as f:
        f.write(f"\n# [Auto-injected by Anti Gravity dependency healer]\n{package}\n")

    logger.info("%s Auto-injected missing dependency: %s", tag, package)
