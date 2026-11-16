"""Copy immutable display artifacts into their producing attempt."""

import hashlib
import shutil
from pathlib import Path

from chipcompiler.tools.replay_storage import within

GEOMETRY_FILES = {
    "meta",
    "shapes",
    "owners",
    "payload",
    "names",
    "name_index",
    "sidmap",
    "delta",
    "view",
    "layers",
    "sites",
    "masters",
    "vias",
    "grids",
    "connectivity",
    "nets",
    "buses",
    "groups",
    "drc",
    "clock_tree_meta",
    "clock_tree_nodes",
    "clock_tree_edges",
    "clock_tree_timing",
    "clock_tree_strings",
}


def freeze_geometry(source: Path, directory: Path) -> dict:
    """Freeze the manifest and every referenced side file, not a mutable pointer."""
    text = source.read_text()
    fields = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
    destination = directory / "subflows/save-data/overlays/final-geometry"
    destination.mkdir(parents=True, exist_ok=True)
    inventory = []
    for key in sorted(GEOMETRY_FILES & fields.keys()):
        value = fields[key].strip()
        if not value:
            continue
        origin = within(source.parent, source.parent / value)
        # Stable local basenames avoid copying external directory hierarchies.
        target = destination / f"{key}{origin.suffix}"
        shutil.copyfile(origin, target)
        with target.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        inventory.append(
            {
                "path": target.relative_to(directory).as_posix(),
                "size": target.stat().st_size,
                "sha256": digest,
            }
        )
        fields[key] = target.name
    manifest = destination / source.name
    manifest.write_text("".join(f"{key}={value}\n" for key, value in fields.items()))
    result = {
        "final_geometry": manifest.relative_to(directory).as_posix(),
        "artifact_files": inventory,
    }
    if "clock_tree_meta" in fields:
        result["frozen_clock_tree"] = result["final_geometry"]
    return result
