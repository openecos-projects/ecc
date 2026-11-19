"""Keep config/macro_location.tcl consistent with the committed macro.placements."""

from pathlib import Path

from .workspace.lifecycle import WorkspaceLifecycleError


def prune_macro_location_after_write(workspace, written: set[str]) -> None:
    """Keep config/macro_location.tcl consistent when a committed write
    emptied macro.placements (§20.5.4): no stale placeInstance lines."""
    if "macro.placements" in written:
        from chipcompiler.data.workspace.macro_location import prune_macro_location_tcl

        prune_macro_location_tcl(workspace)


def verify_published_macro_location(workspace) -> None:
    """Ensure the committed parameters and the post_floorplan handoff agree."""
    from chipcompiler.data.workspace.macro_location import (
        macro_placements,
        parse_macro_location_tcl,
        render_macro_location_tcl,
    )

    expected = macro_placements(workspace)
    target = workspace.config.get("macro_location")
    path = Path(target) if target else None
    if not expected:
        if path is None or not path.is_file():
            return
        try:
            actual = parse_macro_location_tcl(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise WorkspaceLifecycleError(
                "step_output_invalid",
                f"Published macro location handoff is invalid: {exc}",
            ) from exc
        if not actual:
            return
        raise WorkspaceLifecycleError(
            "step_output_mismatch",
            "Published macro location handoff does not match macro.placements",
            {"expectedCount": 0, "actualCount": len(actual)},
        )

    if path is None or not path.is_file():
        raise WorkspaceLifecycleError(
            "step_output_not_published",
            "Workspace has no published macro location handoff",
            {"expectedCount": len(expected)},
        )
    try:
        actual = parse_macro_location_tcl(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise WorkspaceLifecycleError(
            "step_output_invalid",
            f"Published macro location handoff is invalid: {exc}",
        ) from exc

    # The handoff is the canonical physical representation; compare against
    # the same render/parse round-trip used to produce it rather than rejecting
    # harmless float formatting differences in the parameter value.
    try:
        expected = parse_macro_location_tcl(render_macro_location_tcl(expected))
    except ValueError as exc:
        raise WorkspaceLifecycleError(
            "step_output_invalid",
            f"macro.placements cannot be rendered to a handoff: {exc}",
        ) from exc

    def identity(entries: list[dict]) -> list[tuple[str, float, float, str]]:
        return sorted(
            (
                str(entry["instance"]),
                float(entry["x"]),
                float(entry["y"]),
                str(entry["orientation"]),
            )
            for entry in entries
        )

    if identity(actual) != identity(expected):
        raise WorkspaceLifecycleError(
            "step_output_mismatch",
            "Published macro location handoff does not match macro.placements",
            {"expectedCount": len(expected), "actualCount": len(actual)},
        )
