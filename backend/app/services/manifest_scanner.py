from pathlib import Path


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

        for path in root.rglob("*"):

            if any(
                excluded in path.parts
                for excluded in cls.EXCLUDED_DIRS
            ):
                continue

            if path.name in cls.MANIFEST_FILES:

                try:

                    content = path.read_text(
                        encoding="utf-8",
                        errors="ignore",
                    )

                    manifests.append({
                        "file_name": path.name,
                        "relative_path": str(
                            path.relative_to(root)
                        ),
                    })

                except Exception as e:

                    print(
                        f"Failed reading {path}: {e}"
                    )

        return manifests