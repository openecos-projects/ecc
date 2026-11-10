"""Generate a read-only layout-view snapshot from a DEF in a Workspace."""

from pathlib import Path

from chipcompiler.cli.core.errors import CommandError, command_handler
from chipcompiler.cli.core.records import error_record
from chipcompiler.cli.core.types import CommandContext, CommandResult
from chipcompiler.cli.inspection.discovery import resolve_loaded_workspace
from chipcompiler.data import StepEnum
from chipcompiler.tools.ecc import build_step
from chipcompiler.tools.ecc.defview import run_defview


def _defview_failure(reason: str, **fields) -> CommandError:
    return CommandError([error_record("defview_failed", reason=reason, **fields)])


@command_handler
def defview(command_input, ctx: CommandContext) -> CommandResult:
    """Load a standalone DEF and publish geometry under ``<workspace>/defview``."""
    workspace, failure = resolve_loaded_workspace(command_input, ctx)
    if failure is not None:
        return failure
    assert workspace is not None

    def_path = Path(command_input.def_path).expanduser()
    if not def_path.is_file():
        raise _defview_failure(f"DEF input does not exist: {def_path}", def_path=str(def_path))
    def_path = def_path.resolve()

    step_directory = Path(workspace.directory) / StepEnum.DEFVIEW.value
    step = build_step(
        workspace,
        StepEnum.DEFVIEW.value,
        input_def=def_path,
        input_verilog=None,
        output_def=step_directory / "output" / "defview.def",
        step_directory=step_directory,
    )
    Path(step.output.dir or step_directory / "output").mkdir(parents=True, exist_ok=True)
    Path(step.data.dir or step_directory / "data").mkdir(parents=True, exist_ok=True)

    try:
        generated = run_defview(workspace=workspace, step=step)
    except Exception as exc:
        raise _defview_failure(
            f"ECC could not read the selected DEF: {exc}",
            def_path=str(def_path),
            output=str(step.output.geometry or ""),
        ) from exc

    if not generated:
        raise _defview_failure(
            "ECC could not generate a geometry snapshot from the selected DEF",
            def_path=str(def_path),
            output=str(step.output.geometry or ""),
        )

    manifest = step.output.geometry_manifest
    if manifest is None or not manifest.is_file():
        raise _defview_failure(
            "geometry manifest was not generated",
            def_path=str(def_path),
            output=str(step.output.geometry or ""),
        )

    return CommandResult.ok(
        [
            {
                "kind": "defview",
                "status": "success",
                "workspace": str(workspace.directory),
                "def_path": str(def_path),
                "directory": str(step.directory),
                "geometry": str(step.output.geometry or ""),
                "geometry_manifest": str(manifest),
                "image": str(step.output.image or ""),
            }
        ]
    )
