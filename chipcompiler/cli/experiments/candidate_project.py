import json
import shutil
from pathlib import Path

from chipcompiler.project.manifest import MANIFEST_FILENAME, load_manifest


def copy_candidate_project(project: Path, destination: Path) -> None:
    manifest = load_manifest(str(project)) if (project / MANIFEST_FILENAME).is_file() else None
    workspace_roots = (
        tuple(Path(entry.workspace_path) for entry in manifest.workspaces) if manifest else ()
    )

    def ignore(source: str, names: list[str]) -> set[str]:
        return {
            name
            for name in names
            if name in {"experiments", ".git"}
            or name.endswith(".lock")
            or name.startswith("ws_")
            or any((Path(source) / name).resolve().is_relative_to(root) for root in workspace_roots)
        }

    shutil.copytree(project, destination, ignore=ignore)
    if manifest:
        document = {
            **manifest.raw,
            "root_path": str(destination),
            "workspaces": [],
            "runtime_processes": {},
        }
        (destination / MANIFEST_FILENAME).write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n"
        )
