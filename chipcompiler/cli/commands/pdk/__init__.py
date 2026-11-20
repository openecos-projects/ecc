from typing import Annotated

import typer

from chipcompiler.cli.command_handlers import pdk as pdk_handlers
from chipcompiler.cli.core.apps import create_app
from chipcompiler.cli.core.inputs import (
    PdkSetRootInput,
    PdkShowInput,
    PdkUnsetInput,
    output_options,
    project_options,
)
from chipcompiler.cli.core.invocation import execute_command
from chipcompiler.cli.core.options import (
    JsonOption,
    PlainOption,
    ProjectOption,
)

from .configure import configure_app
from .library import library_app
from .profiles import profiles_app

pdk_app = create_app(help="Show and configure the PDK path used by this project")
pdk_app.add_typer(configure_app, name="configure")
pdk_app.add_typer(library_app, name="library")
pdk_app.add_typer(profiles_app, name="profiles")


def _finish(subcommand: str, command_input, handler) -> None:
    execute_command("pdk", command_input, handler, render_key=f"pdk:{subcommand}")


@pdk_app.command("set-root")
def set_root_cmd(
    *,
    path: Annotated[
        str,
        typer.Argument(help="Path to a PDK with ecc-pdk.json (absolute after expansion)"),
    ],
    project: ProjectOption = None,
    plain: PlainOption = False,
) -> None:
    """Set the [pdk] root path in ecc.toml.

    `pdk.root` is the base directory for the PDK content paths `pdk.tech`,
    `pdk.lefs`, `pdk.libs`, and `pdk.mapping_file`. The design-data paths
    `pdk.sdc` and `pdk.spef` resolve against the project directory instead.
    All six get file-existence validation.

    See 'ecc doc config' for the full reference.
    """
    command_input = PdkSetRootInput(
        output=output_options(plain=plain),
        project=project_options(project),
        path=path,
    )
    _finish("set-root", command_input, pdk_handlers.set_root)


@pdk_app.command("show", help="Show the resolved PDK root and its source")
def show_cmd(
    *,
    project: ProjectOption = None,
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    command_input = PdkShowInput(
        output=output_options(plain=plain, json_output=json_output),
        project=project_options(project),
    )
    _finish("show", command_input, pdk_handlers.show)


@pdk_app.command("verify", help="Verify the resolved PDK contents without changing configuration")
def verify_cmd(
    *,
    project: ProjectOption = None,
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    command_input = PdkShowInput(
        output=output_options(plain=plain, json_output=json_output),
        project=project_options(project),
    )
    _finish("verify", command_input, pdk_handlers.verify)


@pdk_app.command(
    "unset", help="Clear [pdk] root (fall back to explicit environment or selected library default)"
)
def unset_cmd(
    *,
    project: ProjectOption = None,
    plain: PlainOption = False,
) -> None:
    command_input = PdkUnsetInput(
        output=output_options(plain=plain),
        project=project_options(project),
    )
    _finish("unset", command_input, pdk_handlers.unset)


@pdk_app.command("clone-with-pdk")
def clone_with_pdk_cmd(
    source: Annotated[str, typer.Option(help="Source RTL project")],
    target: Annotated[str, typer.Option(help="New project directory; must not exist")],
    root: Annotated[str, typer.Option(help="Selected PDK directory")],
) -> None:
    from pathlib import Path

    from chipcompiler.pdk.clone import clone_with_pdk

    from .configure import _failure, _print

    try:
        created = clone_with_pdk(Path(source), Path(target), Path(root))
        _print({"project": str(created), "status": "created"})
    except (ValueError, OSError, RuntimeError) as exc:
        _failure(exc)
