"""Open a workspace step's GDS in KLayout's interactive viewer."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from chipcompiler.cli.command_handlers.chipview import (
    _read_flow_steps,
    _resolve_step_geometry,
)
from chipcompiler.cli.core.errors import CommandError, command_handler
from chipcompiler.cli.core.records import error_record
from chipcompiler.cli.core.types import CommandContext, CommandResult
from chipcompiler.cli.inspection.discovery import resolve_workspace_path
from chipcompiler.tools.klayout_tool.viewer import KlayoutUnavailableError, view_gds


def _display_available() -> bool:
    return any(os.environ.get(key) for key in ("DISPLAY", "WAYLAND_DISPLAY", "WAYLAND_SOCKET"))


def _gds_candidates(output_dir: Path) -> list[Path]:
    if not output_dir.is_dir():
        return []
    return sorted(
        path
        for pattern in ("*.gds", "*.gds.gz")
        for path in output_dir.glob(pattern)
        if path.is_file()
    )


def _available_gds_steps(workspace: Path) -> list[str]:
    try:
        steps = _read_flow_steps(workspace)
    except CommandError:
        return []
    available: list[str] = []
    for flow_step in steps:
        name = str(flow_step.get("name", "")).strip()
        tool = str(flow_step.get("tool", "")).strip()
        if not name or not tool:
            continue
        try:
            directory = _resolve_step_geometry(workspace, name)
        except CommandError:
            continue
        if _gds_candidates(directory["output"]):
            available.append(name)
    return available


def _resolve_gds(workspace: Path, step: str) -> dict:
    resolved = _resolve_step_geometry(workspace, step)
    candidates = _gds_candidates(resolved["output"])
    if not candidates:
        available = _available_gds_steps(workspace)
        raise CommandError(
            [
                error_record(
                    "gds_view_unavailable",
                    step=resolved["name"],
                    output=str(resolved["output"]),
                    reason="the selected step does not publish a GDS file in its output directory",
                    available_steps=", ".join(available) or "(none)",
                    remediation=(
                        "select a step with a GDS output, such as a completed filler or Harden step"
                    ),
                )
            ]
        )
    if len(candidates) > 1:
        raise CommandError(
            [
                error_record(
                    "gds_view_ambiguous",
                    step=resolved["name"],
                    output=str(resolved["output"]),
                    candidates=", ".join(str(path) for path in candidates),
                    reason="more than one GDS file is present for the selected step",
                    remediation="keep one step GDS output before running ecc gdsview",
                )
            ]
        )
    return {**resolved, "gds": candidates[0]}


@command_handler
def gds_view(command_input, ctx: CommandContext) -> CommandResult:
    if sys.platform != "linux":
        return CommandResult.err(
            [
                error_record(
                    "gds_view_platform_unsupported",
                    reason="KLayout GDS viewing through ecc gdsview currently requires Linux",
                )
            ]
        )
    if ctx.manifest_error:
        from chipcompiler.cli.core.records import manifest_error_record

        return CommandResult.err([manifest_error_record(ctx.manifest_error)])

    workspace_dir, error = resolve_workspace_path(
        command_input.workspace, ctx.project, ctx.run_id, ctx.run_dir
    )
    if error is not None:
        return CommandResult.err([error])
    assert workspace_dir is not None

    workspace = Path(workspace_dir)
    resolved = _resolve_gds(workspace, command_input.step)
    if not _display_available():
        return CommandResult.err(
            [
                error_record(
                    "gds_view_display_unavailable",
                    gds=str(resolved["gds"]),
                    reason="no Linux display environment was detected",
                    remediation=(
                        "run ECOS Studio or KLayout in a desktop session with "
                        "DISPLAY or WAYLAND_DISPLAY set"
                    ),
                )
            ]
        )

    try:
        view_gds(resolved["gds"])
    except (ImportError, KlayoutUnavailableError) as exc:
        return CommandResult.err(
            [
                error_record(
                    "gds_view_klayout_unavailable",
                    gds=str(resolved["gds"]),
                    reason=f"KLayout's GUI executable is unavailable: {exc}",
                    remediation="install the KLayout GUI executable or set KLAYOUT_BIN",
                )
            ]
        )
    except (OSError, RuntimeError, ValueError) as exc:
        return CommandResult.err(
            [
                error_record(
                    "gds_view_launch_failed",
                    gds=str(resolved["gds"]),
                    reason=str(exc),
                    remediation="verify the GDS file and the KLayout GUI environment",
                )
            ]
        )

    return CommandResult.ok(
        [
            {
                "gds_view": "closed",
                "status": "closed",
                "workspace": str(workspace),
                "step": resolved["name"],
                "gds": str(resolved["gds"]),
            }
        ]
    )
