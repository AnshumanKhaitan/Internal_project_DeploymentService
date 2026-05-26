"""
Anti Gravity Deployments - Project Scanner

Recursively scans extracted project directories to detect runtime, framework,
dependencies, scripts, environment variables, and deployment configuration.
"""

import json
import os
import re
from pathlib import Path
from typing import Optional

from app.models.schemas import (
    ProjectAnalysis,
    RuntimeType,
    FrameworkType,
    DependencyInfo,
    ScriptInfo,
)


class ProjectScanner:
    """Scans a project directory and produces analysis results."""

    # Directories to ignore during scanning
    IGNORE_DIRS = {
        "node_modules", ".git", "__pycache__", ".venv", "venv",
        "env", ".env", ".tox", ".mypy_cache", ".pytest_cache",
        "dist", "build", ".next", ".nuxt", ".output",
        "coverage", ".turbo", ".cache",
    }

    # Env template file names to look for
    ENV_TEMPLATE_FILES = {
        ".env.example", ".env.sample", ".env.template",
        ".env.local.example", ".env.development.example",
    }

    def scan(self, project_dir: Path) -> ProjectAnalysis:
        """
        Perform a full recursive scan of the project directory.

        Returns a ProjectAnalysis with detected stack information.
        """
        analysis = ProjectAnalysis()
        analysis.project_root = str(project_dir)

        # Gather file stats
        file_count = 0
        total_size = 0
        for root, dirs, files in os.walk(project_dir):
            # Prune ignored directories
            dirs[:] = [d for d in dirs if d not in self.IGNORE_DIRS]
            for f in files:
                file_path = Path(root) / f
                file_count += 1
                try:
                    total_size += file_path.stat().st_size
                except OSError:
                    pass

        analysis.file_count = file_count
        analysis.total_size_bytes = total_size

        # Detect Dockerfile / Docker Compose
        analysis.has_dockerfile = (project_dir / "Dockerfile").exists()
        analysis.has_docker_compose = (
            (project_dir / "docker-compose.yml").exists()
            or (project_dir / "docker-compose.yaml").exists()
        )

        # Try Node.js detection first
        node_result = self._detect_nodejs(project_dir)
        if node_result:
            analysis.runtime = node_result["runtime"]
            analysis.runtime_version = node_result.get("runtime_version")
            analysis.framework = node_result.get("framework", FrameworkType.UNKNOWN)
            analysis.framework_version = node_result.get("framework_version")
            analysis.detected_port = node_result.get("detected_port", 3000)
            analysis.entry_point = node_result.get("entry_point")
            analysis.startup_command = node_result.get("startup_command")
            analysis.dependencies = node_result.get("dependencies", [])
            analysis.dependencies_count = len(analysis.dependencies)
            analysis.scripts = node_result.get("scripts", [])
        else:
            # Try Python detection
            python_result = self._detect_python(project_dir)
            if python_result:
                analysis.runtime = python_result["runtime"]
                analysis.runtime_version = python_result.get("runtime_version")
                analysis.framework = python_result.get("framework", FrameworkType.UNKNOWN)
                analysis.framework_version = python_result.get("framework_version")
                analysis.detected_port = python_result.get("detected_port", 8000)
                analysis.entry_point = python_result.get("entry_point")
                analysis.startup_command = python_result.get("startup_command")
                analysis.dependencies = python_result.get("dependencies", [])
                analysis.dependencies_count = len(analysis.dependencies)

        # Detect env template files
        env_result = self._detect_env_template(project_dir)
        if env_result:
            analysis.env_template_keys = env_result["keys"]
            analysis.env_template_file = env_result["file"]

        return analysis

    def _detect_nodejs(self, project_dir: Path) -> Optional[dict]:
        """Detect Node.js project details from package.json."""
        package_json_path = project_dir / "package.json"
        if not package_json_path.exists():
            return None

        try:
            with open(package_json_path, "r", encoding="utf-8") as f:
                pkg = json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

        result: dict = {
            "runtime": RuntimeType.NODEJS,
            "entry_point": "package.json",
        }

        # Extract Node.js version from engines
        engines = pkg.get("engines", {})
        if "node" in engines:
            result["runtime_version"] = engines["node"]

        # Extract dependencies
        deps: list[DependencyInfo] = []
        for name, version in pkg.get("dependencies", {}).items():
            deps.append(DependencyInfo(name=name, version=version, is_dev=False))
        for name, version in pkg.get("devDependencies", {}).items():
            deps.append(DependencyInfo(name=name, version=version, is_dev=True))
        result["dependencies"] = deps

        # Extract scripts
        scripts: list[ScriptInfo] = []
        for name, command in pkg.get("scripts", {}).items():
            scripts.append(ScriptInfo(name=name, command=command))
        result["scripts"] = scripts

        # Determine startup command
        if "start" in pkg.get("scripts", {}):
            result["startup_command"] = "npm start"
        elif "serve" in pkg.get("scripts", {}):
            result["startup_command"] = "npm run serve"
        elif "dev" in pkg.get("scripts", {}):
            result["startup_command"] = "npm run dev"

        # Detect framework and version
        all_deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}

        if "next" in all_deps:
            result["framework"] = FrameworkType.NEXTJS
            result["framework_version"] = _clean_version(all_deps["next"])
            result["detected_port"] = 3000
            result["startup_command"] = "npm start"
        elif (project_dir / "angular.json").exists() or "@angular/core" in all_deps:
            result["framework"] = FrameworkType.ANGULAR
            result["framework_version"] = _clean_version(
                all_deps.get("@angular/core", "")
            )
            result["detected_port"] = 4200
        elif "vite" in all_deps:
            # Check if it's a React+Vite or just Vite
            if "react" in all_deps:
                result["framework"] = FrameworkType.REACT
                result["framework_version"] = _clean_version(all_deps.get("react", ""))
            elif "vue" in all_deps:
                result["framework"] = FrameworkType.VUE
                result["framework_version"] = _clean_version(all_deps.get("vue", ""))
            else:
                result["framework"] = FrameworkType.VITE
                result["framework_version"] = _clean_version(all_deps.get("vite", ""))
            result["detected_port"] = 5173

            # Check vite.config for custom port
            vite_port = self._detect_vite_port(project_dir)
            if vite_port:
                result["detected_port"] = vite_port
        elif "react" in all_deps:
            result["framework"] = FrameworkType.REACT
            result["framework_version"] = _clean_version(all_deps.get("react", ""))
            result["detected_port"] = 3000
        elif "vue" in all_deps:
            result["framework"] = FrameworkType.VUE
            result["framework_version"] = _clean_version(all_deps.get("vue", ""))
            result["detected_port"] = 8080
        elif "express" in all_deps:
            result["framework"] = FrameworkType.EXPRESS
            result["framework_version"] = _clean_version(all_deps.get("express", ""))
            result["detected_port"] = 3000

        return result

    def _detect_python(self, project_dir: Path) -> Optional[dict]:
        """Detect Python project details."""
        requirements_path = project_dir / "requirements.txt"
        pyproject_path = project_dir / "pyproject.toml"
        setup_path = project_dir / "setup.py"

        has_python = (
            requirements_path.exists()
            or pyproject_path.exists()
            or setup_path.exists()
        )
        if not has_python:
            return None

        result: dict = {
            "runtime": RuntimeType.PYTHON,
            "entry_point": "requirements.txt" if requirements_path.exists() else "pyproject.toml",
        }

        # Parse requirements.txt for dependencies and framework detection
        deps: list[DependencyInfo] = []
        framework_map = {
            "fastapi": (FrameworkType.FASTAPI, 8000),
            "flask": (FrameworkType.FLASK, 5000),
            "django": (FrameworkType.DJANGO, 8000),
        }

        if requirements_path.exists():
            try:
                with open(requirements_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or line.startswith("-"):
                            continue
                        # Parse "package==version" or "package>=version" etc
                        match = re.match(
                            r"^([a-zA-Z0-9_-]+(?:\[[a-zA-Z0-9_,-]+\])?)\s*([><=!~]+\s*[\d.]+)?",
                            line,
                        )
                        if match:
                            name = match.group(1)
                            version = (match.group(2) or "").strip()
                            # Strip extras from name for lookup
                            base_name = re.sub(r"\[.*\]", "", name).lower()
                            deps.append(
                                DependencyInfo(name=name, version=version, is_dev=False)
                            )

                            # Check for framework
                            if base_name in framework_map:
                                fw_type, port = framework_map[base_name]
                                result["framework"] = fw_type
                                result["framework_version"] = version.lstrip("><=!~ ") if version else None
                                result["detected_port"] = port
            except OSError:
                pass

        result["dependencies"] = deps

        # Determine startup command
        if result.get("framework") == FrameworkType.FASTAPI:
            # Look for main.py or app/main.py
            if (project_dir / "app" / "main.py").exists():
                result["startup_command"] = "uvicorn app.main:app --host 0.0.0.0 --port 8000"
                result["entry_point"] = "app/main.py"
            elif (project_dir / "main.py").exists():
                result["startup_command"] = "uvicorn main:app --host 0.0.0.0 --port 8000"
                result["entry_point"] = "main.py"
        elif result.get("framework") == FrameworkType.FLASK:
            if (project_dir / "app.py").exists():
                result["startup_command"] = "flask run --host 0.0.0.0 --port 5000"
                result["entry_point"] = "app.py"
        elif result.get("framework") == FrameworkType.DJANGO:
            if (project_dir / "manage.py").exists():
                result["startup_command"] = "python manage.py runserver 0.0.0.0:8000"
                result["entry_point"] = "manage.py"

        return result

    def _detect_vite_port(self, project_dir: Path) -> Optional[int]:
        """Try to detect a custom port from vite config files."""
        for config_name in ["vite.config.js", "vite.config.ts", "vite.config.mjs"]:
            config_path = project_dir / config_name
            if config_path.exists():
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    match = re.search(r"port\s*:\s*(\d+)", content)
                    if match:
                        return int(match.group(1))
                except OSError:
                    pass
        return None

    def _detect_env_template(self, project_dir: Path) -> Optional[dict]:
        """
        Detect .env.example / .env.sample / .env.template files
        and extract variable keys.
        """
        for template_name in self.ENV_TEMPLATE_FILES:
            template_path = project_dir / template_name
            if template_path.exists():
                keys = self._parse_env_file_keys(template_path)
                return {"file": template_name, "keys": keys}
        return None

    def _parse_env_file_keys(self, env_path: Path) -> list[str]:
        """Parse an env template file and extract variable key names."""
        keys: list[str] = []
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    # Match KEY=value or KEY= patterns
                    match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
                    if match:
                        keys.append(match.group(1))
        except OSError:
            pass
        return keys


def _clean_version(version_str: str) -> str:
    """Clean a version string by removing ^, ~, >= etc."""
    return re.sub(r"^[\^~>=<*]+\s*", "", version_str).strip()


# Singleton instance
project_scanner = ProjectScanner()
