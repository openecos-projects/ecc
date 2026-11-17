"""Reference the producing step's geometry without storing another snapshot."""

from pathlib import Path

from chipcompiler.tools.replay_integrity import fingerprint
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


def reference_geometry(source: Path) -> dict:
    """Bind the existing snapshot by content; reruns invalidate the recording."""
    text = source.read_text()
    fields = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
    files = {source.name: fingerprint(source)}
    for key in sorted(
        (GEOMETRY_FILES & fields.keys()) | {key for key in fields if key.startswith("display.")}
    ):
        value = fields[key].strip()
        if not value:
            continue
        origin = within(source.parent, source.parent / value)
        relative = origin.relative_to(source.parent.resolve()).as_posix()
        files[relative] = fingerprint(origin)
    return {
        "shared_geometry": {
            "manifest": source.name,
            "files": files,
            "clock_tree": bool(fields.get("clock_tree_meta", "").strip()),
        }
    }
