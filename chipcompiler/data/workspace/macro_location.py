"""Workspace macro-location Tcl generation.

``macro_placements`` reads the manual hard-macro placements from the
workspace parameters; ``refresh_generated_macro_location`` renders them
into ``config/macro_location.tcl``. An empty placement list leaves the
file untouched so the seeded template and DreamPlace's own handoff
survive parameter refreshes.
"""

import math
from pathlib import Path
from typing import TYPE_CHECKING, Final

from chipcompiler.utility.file import write_text_atomic

if TYPE_CHECKING:
    from chipcompiler.data import Workspace

MACRO_LOCATION_MARKER: Final[str] = "# Auto-generated macro location file"

MACRO_ORIENTATIONS: Final[frozenset[str]] = frozenset(
    {"R0", "R90", "R180", "R270", "MX", "MY", "MX90", "MY90"}
)


def macro_placements(workspace: "Workspace") -> list[dict]:
    """Return the manual macro placement entries stored in the parameters."""
    macro = workspace.parameters.data.get("macro", {})
    if not isinstance(macro, dict):
        return []
    placements = macro.get("placements", [])
    return placements if isinstance(placements, list) else []


def validate_placements(placements: list[dict]) -> list[str]:
    """Return one error message per invalid placement entry."""
    errors = []
    for index, entry in enumerate(placements):
        if not isinstance(entry, dict):
            errors.append(f"placement #{index + 1} is not an object")
            continue
        instance = entry.get("instance")
        if not isinstance(instance, str) or not instance.strip():
            errors.append(f"placement #{index + 1} has an empty instance name")
        for key in ("x", "y"):
            value = entry.get(key)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                errors.append(f"placement #{index + 1} has a non-finite {key} coordinate")
        if entry.get("orientation") not in MACRO_ORIENTATIONS:
            errors.append(
                "placement #{index + 1} orientation must be one of "
                + "/".join(sorted(MACRO_ORIENTATIONS))
            )
    return errors


def render_macro_location_tcl(placements: list[dict]) -> str:
    """Render the placeInstance handoff consumed by postFloorplan (iFP)."""
    lines = [MACRO_LOCATION_MARKER, ""]
    for entry in placements:
        lines.append(
            "placeInstance {} {:g} {:g} {}".format(
                entry["instance"], entry["x"], entry["y"], entry["orientation"]
            )
        )
        lines.append(f"setInstancePlacementStatus -status fixed -name {entry['instance']}")
    return "\n".join(lines) + "\n"


def refresh_generated_macro_location(workspace: "Workspace") -> None:
    """Regenerate config/macro_location.tcl from the manual placements."""
    placements = macro_placements(workspace)
    if not placements:
        return

    errors = validate_placements(placements)
    if errors:
        raise ValueError("; ".join(errors))

    target = workspace.config.get("macro_location")
    if not target:
        return
    write_text_atomic(Path(target), render_macro_location_tcl(placements))
