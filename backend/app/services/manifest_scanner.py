from pathlib import Path


COMMON_NODE_ENTRYPOINTS = [
    "index.js",
    "server.js",
    "app.js",
    "main.js",
]

COMMON_PYTHON_ENTRYPOINTS = [
    "main.py",
    "app.py",
]


class ManifestScanner:

    MANIFEST_FILES = [
        "package.json",
        "requirements.txt",
        "pyproject.toml",
        "pom.xml",
    ]

    EXCLUDED_DIRS = {
        "node_modules",
        ".git",
        ".venv",
        "__pycache__",
        "dist",
        "build",
        ".next",
    }

    @classmethod
    def scan(
        cls,
        root_path: str,
    ):

        root = Path(root_path)

        manifests = []

        entry_points = []

        # ─────────────────────────────────────────────
        # Scan entry points
        # ─────────────────────────────────────────────

        for file_path in root.rglob("*"):

            if any(
                excluded in file_path.parts
                for excluded in cls.EXCLUDED_DIRS
            ):
                continue

            if file_path.is_file():

                if file_path.name in (
                    COMMON_NODE_ENTRYPOINTS
                    + COMMON_PYTHON_ENTRYPOINTS
                ):

                    entry_points.append(
                        str(
                            file_path.relative_to(
                                root
                            )
                        )
                    )

        # ─────────────────────────────────────────────
        # Scan manifest files
        # ─────────────────────────────────────────────

        for path in root.rglob("*"):

            if any(
                excluded in path.parts
                for excluded in cls.EXCLUDED_DIRS
            ):
                continue

            if (
                path.is_file()
                and path.name in cls.MANIFEST_FILES
            ):

                try:

                    manifests.append({
                        "file_name":
                            path.name,

                        "relative_path":
                            str(
                                path.relative_to(root)
                            ),
                    })

                except Exception as e:

                    print(
                        f"Failed reading {path}: {e}"
                    )

        # ─────────────────────────────────────────────
        # Runtime detection
        # ─────────────────────────────────────────────

        runtime = "unknown"

        manifest_names = [
            manifest["file_name"].lower()
            for manifest in manifests
        ]

        if "package.json" in manifest_names:
            runtime = "nodejs"

        elif (
            "requirements.txt" in manifest_names
            or "pyproject.toml" in manifest_names
        ):
            runtime = "python"

        # ─────────────────────────────────────────────
        # Framework detection
        # ─────────────────────────────────────────────

        framework = "unknown"

        package_json_path = (
            root / "package.json"
        )

        if package_json_path.exists():

            try:

                import json

                package_data = json.loads(
                    package_json_path.read_text(
                        encoding="utf-8",
                        errors="ignore",
                    )
                )

                dependencies = {
                    **package_data.get(
                        "dependencies",
                        {}
                    ),
                    **package_data.get(
                        "devDependencies",
                        {}
                    ),
                }

                dependency_names = [
                    dep.lower()
                    for dep in dependencies.keys()
                ]

                if "next" in dependency_names:
                    framework = "nextjs"

                elif "vite" in dependency_names:
                    framework = "vite"

                elif "express" in dependency_names:
                    framework = "express"

                elif "react" in dependency_names:
                    framework = "react"

            except Exception as e:

                print(
                    f"Failed parsing package.json: {e}"
                )

        return {
            "runtime":
                runtime,

            "framework":
                framework,

            "entry_points":
                entry_points,

            "manifests":
                manifests,
        }