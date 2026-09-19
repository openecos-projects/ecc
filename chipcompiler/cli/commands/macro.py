from typing import Annotated

import typer

from chipcompiler.cli.command_handlers.macro import macro_import as macro_import_handler
from chipcompiler.cli.command_handlers.macro import macro_remove as macro_remove_handler
from chipcompiler.cli.command_handlers.macro import macro_set as macro_set_handler
from chipcompiler.cli.command_handlers.macro import macro_show as macro_show_handler
from chipcompiler.cli.core.apps import create_app
from chipcompiler.cli.core.inputs import (
    MacroImportInput,
    MacroRemoveInput,
    MacroSetInput,
    MacroShowInput,
    output_options,
    project_options,
)
from chipcompiler.cli.core.invocation import CommandHandler, CommandInputT, execute_command
from chipcompiler.cli.core.options import (
    PlainOption,
    ProjectOption,
    WorkspaceOption,
)

macro_app = create_app(help="Manage manual macro placement (macro_location.tcl)")


def _finish_macro(
    macro_command: str,
    command_input: CommandInputT,
    handler: CommandHandler[CommandInputT],
) -> None:
    execute_command("macro", command_input, handler, render_key=f"macro:{macro_command}")


@macro_app.command("set")
def set_cmd(
    *,
    instance: Annotated[str, typer.Argument()],
    x: Annotated[float, typer.Option("--x", help="X coordinate in micrometers.")],
    y: Annotated[float, typer.Option("--y", help="Y coordinate in micrometers.")],
    orientation: Annotated[
        str,
        typer.Option(
            "--orient",
            help="Orientation: R0, R90, R180, R270, MX, MY, MX90, or MY90.",
        ),
    ],
    project: ProjectOption = None,
    workspace: WorkspaceOption = None,
    plain: PlainOption = False,
) -> None:
    """Set one macro instance placement.

    Scopes:

    - project (default): stored in `ecc.toml` `[params.macro]`; rendered
      into `config/macro_location.tcl` when a workspace is created or
      refreshed.
    - `--workspace NAME`: written to `home/params.toml`, the Tcl file is
      regenerated immediately, and `macroPlacement` and its suffix are
      marked pending.

    Coordinates are in micrometers and the instance is committed `fixed`.
    While `macro.placements` is non-empty the `macroPlacement` step keeps
    its load/save flow but skips DreamPlace macro placement.

    ```bash
    ecc macro set u_ram0 --x 10 --y 20.5 --orient R0
    ```
    """
    command_input = MacroSetInput(
        output=output_options(plain=plain),
        project=project_options(project),
        instance=instance,
        x=x,
        y=y,
        orientation=orientation,
        workspace=workspace,
    )
    _finish_macro("set", command_input, macro_set_handler)


@macro_app.command("remove")
def remove_cmd(
    *,
    instance: Annotated[str, typer.Argument()],
    project: ProjectOption = None,
    workspace: WorkspaceOption = None,
    plain: PlainOption = False,
) -> None:
    """Remove one macro instance placement.

    Removing the last entry clears `macro.placements`, so the next
    `macroPlacement` run goes back to DreamPlace macro placement.

    ```bash
    ecc macro remove u_ram0
    ```
    """
    command_input = MacroRemoveInput(
        output=output_options(plain=plain),
        project=project_options(project),
        instance=instance,
        workspace=workspace,
    )
    _finish_macro("remove", command_input, macro_remove_handler)


@macro_app.command("import")
def import_cmd(
    *,
    path: Annotated[
        str,
        typer.Argument(help="Path to a placeInstance macro_location.tcl file."),
    ],
    project: ProjectOption = None,
    workspace: WorkspaceOption = None,
    plain: PlainOption = False,
) -> None:
    """Import a macro_location.tcl file as the manual macro placements.

    Parses `placeInstance` statements (micrometers, R-notation) and
    replaces `macro.placements` wholesale; comments and
    `setInstancePlacementStatus` lines are skipped, any other statement
    fails the import without writing anything.

    Scopes:

    - project (default): replaces `ecc.toml` `[params.macro]`; rendered
      into `config/macro_location.tcl` when a workspace is created or
      refreshed.
    - `--workspace NAME`: written to `home/params.toml`, the Tcl file is
      regenerated immediately, and `macroPlacement` and its suffix are
      marked pending. An empty file clears the placements.

    ```bash
    ecc macro import config/macro_location.tcl --workspace baseline
    ```
    """
    command_input = MacroImportInput(
        output=output_options(plain=plain),
        project=project_options(project),
        path=path,
        workspace=workspace,
    )
    _finish_macro("import", command_input, macro_import_handler)


@macro_app.command("show")
def show_cmd(
    *,
    project: ProjectOption = None,
    workspace: WorkspaceOption = None,
    plain: PlainOption = False,
) -> None:
    """Show the manual macro placements and the generated Tcl path.

    ```bash
    ecc macro show
    ecc macro show --workspace baseline
    ```
    """
    command_input = MacroShowInput(
        output=output_options(plain=plain),
        project=project_options(project),
        workspace=workspace,
    )
    _finish_macro("show", command_input, macro_show_handler)
