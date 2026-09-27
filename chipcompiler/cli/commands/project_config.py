"""Project-level configuration editing commands."""

from typing import Annotated

import typer

from chipcompiler.cli.command_handlers import project_config as handlers
from chipcompiler.cli.command_handlers import project_doctor as doctor_handlers
from chipcompiler.cli.core.apps import create_app
from chipcompiler.cli.core.inputs import (
    ProjectAddInput,
    ProjectApplyInput,
    ProjectBaselineInput,
    ProjectReconcileInput,
    ProjectSetInput,
    ProjectShowInput,
    ProjectUnsetInput,
    output_options,
    project_options,
)
from chipcompiler.cli.core.invocation import execute_command
from chipcompiler.cli.core.options import PlainOption, ProjectOption

project_app = create_app(help="Edit project declarations in ecc.toml")


def _finish(subcommand: str, command_input, handler) -> None:
    execute_command("project", command_input, handler, render_key=f"project:{subcommand}")


@project_app.command("apply", help="Atomically apply multiple Project settings")
def apply_cmd(
    *,
    project: ProjectOption = None,
    sets: Annotated[list[str] | None, typer.Option("--set")] = None,
    unsets: Annotated[list[str] | None, typer.Option("--unset")] = None,
    add_rtl: Annotated[list[str] | None, typer.Option("--add-rtl")] = None,
    remove_rtl: Annotated[list[str] | None, typer.Option("--remove-rtl")] = None,
    no_wait: Annotated[bool, typer.Option("--no-wait")] = False,
    plain: PlainOption = False,
) -> None:
    _finish(
        "apply",
        ProjectApplyInput(
            output=output_options(plain=plain),
            project=project_options(project),
            sets=tuple(sets or ()),
            unsets=tuple(unsets or ()),
            add_rtl=tuple(add_rtl or ()),
            remove_rtl=tuple(remove_rtl or ()),
            no_wait=no_wait,
        ),
        handlers.project_apply,
    )


@project_app.command("baseline", help="Select the Project QoR baseline")
def baseline_cmd(
    *,
    workspace_id: Annotated[str, typer.Argument()],
    project: ProjectOption = None,
    reason: Annotated[str, typer.Option("--reason")] = "",
    plain: PlainOption = False,
) -> None:
    _finish(
        "baseline",
        ProjectBaselineInput(
            output=output_options(plain=plain),
            project=project_options(project),
            workspace_id=workspace_id,
            reason=reason,
        ),
        handlers.project_baseline,
    )


@project_app.command("reconcile", help="Repair provable Project intermediate states")
def reconcile_cmd(
    *,
    project: ProjectOption = None,
    no_wait: Annotated[bool, typer.Option("--no-wait")] = False,
    plain: PlainOption = False,
) -> None:
    _finish(
        "reconcile",
        ProjectReconcileInput(
            output=output_options(plain=plain),
            project=project_options(project),
            no_wait=no_wait,
        ),
        handlers.project_reconcile,
    )


@project_app.command("set", help="Set one project declaration")
def set_cmd(
    *,
    key: Annotated[str, typer.Argument()],
    values: Annotated[list[str], typer.Argument()],
    project: ProjectOption = None,
    plain: PlainOption = False,
) -> None:
    _finish(
        "set",
        ProjectSetInput(
            output=output_options(plain=plain),
            project=project_options(project),
            key=key,
            values=tuple(values),
        ),
        handlers.project_set,
    )


@project_app.command("unset", help="Remove one project declaration")
def unset_cmd(
    *,
    key: Annotated[str, typer.Argument()],
    project: ProjectOption = None,
    plain: PlainOption = False,
) -> None:
    _finish(
        "unset",
        ProjectUnsetInput(
            output=output_options(plain=plain),
            project=project_options(project),
            key=key,
        ),
        handlers.project_unset,
    )


@project_app.command("add", help="Add RTL sources to design.rtl")
def add_cmd(
    *,
    key: Annotated[str, typer.Argument()],
    values: Annotated[list[str], typer.Argument()],
    project: ProjectOption = None,
    plain: PlainOption = False,
) -> None:
    _finish(
        "add",
        ProjectAddInput(
            output=output_options(plain=plain),
            project=project_options(project),
            key=key,
            values=tuple(values),
        ),
        handlers.project_add,
    )


@project_app.command("remove", help="Remove RTL sources from design.rtl")
def remove_cmd(
    *,
    key: Annotated[str, typer.Argument()],
    values: Annotated[list[str], typer.Argument()],
    project: ProjectOption = None,
    plain: PlainOption = False,
) -> None:
    _finish(
        "remove",
        ProjectAddInput(
            output=output_options(plain=plain),
            project=project_options(project),
            key=key,
            values=tuple(values),
        ),
        handlers.project_remove,
    )


@project_app.command("show", help="Show declarations stored in ecc.toml")
def show_cmd(
    *,
    key: Annotated[str | None, typer.Argument()] = None,
    project: ProjectOption = None,
    plain: PlainOption = False,
) -> None:
    _finish(
        "show",
        ProjectShowInput(
            output=output_options(plain=plain),
            project=project_options(project),
            key=key,
        ),
        handlers.project_show,
    )


@project_app.command("doctor", help="Check project.json against workspace directories")
def doctor_cmd(
    *,
    fix: Annotated[
        bool,
        typer.Option("--fix", help="Repair every reported inconsistency explicitly"),
    ] = False,
    project: ProjectOption = None,
    plain: PlainOption = False,
) -> None:
    """Check manifest ↔ workspace-directory consistency.

    Reports three classes: entries whose derived fields
    (start_step/end_step/status/parameter_patch) disagree with the
    workspace directory, entries pointing at missing directories, and
    workspace directories under the project root with no manifest entry.
    Read-only by default and exits 1 when inconsistencies are found.
    With --fix, derived fields are rebuilt from directory facts, dead
    entries are removed, unregistered directories are registered, and
    every repair is printed as a record; the exit code is 1 only when a
    repair failed.
    """
    _finish(
        "doctor",
        ProjectDoctorInput(
            output=output_options(plain=plain),
            project=project_options(project),
            fix=fix,
        ),
        doctor_handlers.project_doctor,
    )
