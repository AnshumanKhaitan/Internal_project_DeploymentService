"""
Anti Gravity Deployments - Utility Helpers

Common utility functions used across the application including
safe ZIP extraction with path traversal protection.
"""

import os
import re
import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Optional


def get_upload_dir() -> Path:
    """Get the upload directory path, creating it if needed."""
    upload_dir = Path(os.getenv("UPLOAD_DIR", "/tmp/ag-uploads"))
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir


def get_deployments_dir() -> Path:
    """Get the deployments base directory, creating it if needed."""
    deployments_dir = get_upload_dir() / "deployments"
    deployments_dir.mkdir(parents=True, exist_ok=True)
    return deployments_dir


def create_deployment_workspace(project_name: str) -> tuple[str, Path]:
    """
    Create a unique deployment workspace directory.

    Returns:
        Tuple of (deployment_id, workspace_path)
        e.g. ("a1b2c3d4", Path("/tmp/ag-uploads/deployments/my-project/a1b2c3d4"))
    """
    deployment_id = uuid.uuid4().hex[:8]
    safe_name = sanitize_container_name(project_name)
    workspace = get_deployments_dir() / safe_name / deployment_id
    workspace.mkdir(parents=True, exist_ok=True)
    return deployment_id, workspace


def validate_zip_file(file_path: Path) -> tuple[bool, Optional[str]]:
    """
    Validate that a file is a valid ZIP archive.

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not file_path.exists():
        return False, "File does not exist"

    if not file_path.suffix.lower() == ".zip":
        return False, "File is not a ZIP archive"

    # Check file size (max 500MB)
    max_size = 500 * 1024 * 1024  # 500 MB
    try:
        file_size = file_path.stat().st_size
        if file_size > max_size:
            return False, f"ZIP file too large ({format_file_size(file_size)}). Max: 500MB"
        if file_size == 0:
            return False, "ZIP file is empty (0 bytes)"
    except OSError as e:
        return False, f"Cannot read file size: {str(e)}"

    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            # Check for corrupted entries
            bad_file = zf.testzip()
            if bad_file:
                return False, f"Corrupted entry in ZIP: {bad_file}"

            # Check that it's not empty
            if len(zf.namelist()) == 0:
                return False, "ZIP archive is empty"

            # Check for path traversal attempts
            for name in zf.namelist():
                if _is_path_traversal(name):
                    return False, f"Potentially malicious path detected: {name}"

        return True, None
    except zipfile.BadZipFile:
        return False, "File is not a valid ZIP archive"
    except Exception as e:
        return False, f"Error validating ZIP: {str(e)}"


def safe_extract_zip(zip_path: Path, extract_to: Path) -> tuple[bool, Optional[str], Optional[Path]]:
    """
    Safely extract a ZIP file preventing path traversal attacks.

    Returns:
        Tuple of (success, error_message, project_root_path)
    """
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            # Security check: verify all paths are safe
            for member in zf.infolist():
                member_path = Path(member.filename)

                # Reject absolute paths
                if member_path.is_absolute():
                    return False, f"Absolute path in ZIP: {member.filename}", None

                # Reject path traversal
                if _is_path_traversal(member.filename):
                    return False, f"Path traversal attempt: {member.filename}", None

                # Reject symbolic links
                if member.external_attr >> 28 == 0xA:
                    return False, f"Symbolic link in ZIP: {member.filename}", None

            # Extract safely
            for member in zf.infolist():
                # Skip directories, they'll be created as needed
                target_path = extract_to / member.filename

                # Ensure target is within extract_to (resolve symlinks)
                try:
                    # On Windows, resolve() may fail for non-existent paths
                    # Use a simpler check
                    abs_extract = str(extract_to.resolve())
                    abs_target = str((extract_to / member.filename).resolve())
                    if not abs_target.startswith(abs_extract):
                        return False, f"Path escape attempt: {member.filename}", None
                except (OSError, ValueError):
                    pass

                if member.is_dir():
                    target_path.mkdir(parents=True, exist_ok=True)
                else:
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member) as source, open(target_path, "wb") as target:
                        shutil.copyfileobj(source, target)

        # Detect the actual project root (might be inside a subdirectory)
        project_root = _find_project_root(extract_to)
        return True, None, project_root

    except zipfile.BadZipFile:
        return False, "Invalid ZIP file", None
    except PermissionError as e:
        return False, f"Permission denied during extraction: {str(e)}", None
    except Exception as e:
        return False, f"Extraction error: {str(e)}", None


def _find_project_root(extract_to: Path) -> Path:
    """
    Find the actual project root directory.

    Many ZIPs contain a single top-level directory (e.g., project-name/).
    If so, return that directory as the project root.
    Otherwise, the extract directory itself is the root.
    """
    entries = [e for e in extract_to.iterdir() if not e.name.startswith(".")]

    # If there's exactly one directory and no files at root level
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]

    return extract_to


def _is_path_traversal(path_str: str) -> bool:
    """Check if a path string contains traversal attempts."""
    # Normalize separators
    normalized = path_str.replace("\\", "/")

    # Check for .. components
    parts = normalized.split("/")
    for part in parts:
        if part == "..":
            return True

    # Check for absolute paths (Unix or Windows)
    if normalized.startswith("/") or (len(normalized) > 1 and normalized[1] == ":"):
        return True

    return False


def format_file_size(size_bytes: int) -> str:
    """Format file size in human-readable format."""
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def sanitize_container_name(name: str) -> str:
    """Sanitize a string to be a valid Docker container name."""
    # Only allow alphanumeric, hyphens, and underscores
    sanitized = re.sub(r"[^a-zA-Z0-9_-]", "-", name.lower())
    # Remove leading/trailing hyphens
    sanitized = sanitized.strip("-")
    # Collapse multiple hyphens
    sanitized = re.sub(r"-+", "-", sanitized)
    return sanitized[:63]  # Docker name length limit


def orchestrator_public_api_url() -> str:
    """
    URL of the root deployment API as seen from the user's browser.
    Deployed preview copies of this platform must call this host (has Docker),
    not their nested backend container port.
    """
    return os.environ.get("ORCHESTRATOR_PUBLIC_API_URL", "http://localhost:8000").rstrip("/")


def resolve_project_tree(project_root: Path, workspace_subdir: str | None = None) -> Path:
    if workspace_subdir and workspace_subdir not in (".", ""):
        return (project_root / workspace_subdir).resolve()
    return project_root.resolve()


def is_anti_gravity_platform(project_root: Path) -> bool:
    """True when the tree is this deployment platform (not a generic uploaded app)."""
    root = project_root.resolve()
    markers = [
        root / "app" / "services" / "execution_engine.py",
        root / "src" / "lib" / "deployment-context.tsx",
        root / "frontend" / "src" / "lib" / "deployment-context.tsx",
    ]
    return any(p.is_file() for p in markers)


def browser_api_url_for_deploy(
    frontend_root: Path,
    backend_url: str | None,
    workspace_subdir: str | None = None,
) -> str:
    """
    API base URL baked into deployed frontends (NEXT_PUBLIC_* at build time).
    Platform UI always targets the root orchestrator; other apps use their backend URL.
    """
    tree = resolve_project_tree(frontend_root, workspace_subdir)
    if is_anti_gravity_platform(tree):
        return orchestrator_public_api_url()
    if backend_url:
        return backend_url.rstrip("/")
    return orchestrator_public_api_url()

def cleanup_workspace(workspace_path: Path) -> bool:
    """Remove a deployment workspace directory."""
    try:
        if workspace_path.exists():
            shutil.rmtree(workspace_path)
        return True
    except Exception:
        return False
