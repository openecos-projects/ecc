# pyright: strict
"""``ecc flow status`` and ``ecc flow edit``: the project's step selection.

Both read the selection (skipped and inserted steps) from ``ecc.toml`` (like
``ecc param``); a project.json workspace entry layers beneath it only when the
selector resolves one. ``edit`` writes the whole ``[flow]`` selection back to
``ecc.toml``, with the project's ``max_parallel_steps`` (a run-time setting
that is not part of the selection).
"""

import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from chipcompiler.cli.core.inputs import FlowEditInput, FlowStatusInput
from chipcompiler.cli.core.output import disclosure_cmd
from chipcompiler.cli.core.records import error_record, manifest_error_record, warning_record
from chipcompiler.cli.core.types import CommandContext, CommandResult, OutputMode
from chipcompiler.project.manifest import CONFIG_FILENAME

if TYPE_CHECKING:
    from rich.console import Console

    from chipcompiler.cli.interactive.flow_edit import EditedSelection
    from chipcompiler.cli.interactive.terminal import KeyReader
    from chipcompiler.cli.project.config import ProjectConfig
    from chipcompiler.cli.project.flow_selection import FlowConfig
    from chipcompiler.data.flow_plan import FlowPlan
    from chipcompiler.data.types import LECEngineEnum

Record = dict[str, object]
#: Shows the pending ``flow_edit`` records and answers whether to write them.
Confirm = Callable[[Sequence[Record]], bool]


@dataclass(frozen=True, slots=True)
class Selection:
    """The chosen steps of a preset: skipped chain steps and inserted steps."""

    skip_steps: tuple[str, ...]
    insert_steps: tuple[str, ...]


def flow_status(args: FlowStatusInput, ctx: CommandContext) -> CommandResult:
    from chipcompiler.cli.project.design_inputs import validate_entry_inputs
    from chipcompiler.cli.project.flow_selection import (
        changed_insert_steps,
        effective_insert_steps,
        effective_skip_steps,
        project_flow_plan,
        toggled_skip_steps,
    )
    from chipcompiler.cli.project.flow_status_view import status_view, view_records

    selection = project_selection(ctx, "ecc flow status")
    if isinstance(selection, CommandResult):
        return selection
    cfg, flow_config = selection
    max_parallel_steps = _declared_max_parallel_steps(ctx, cfg, "ecc flow status")
    if isinstance(max_parallel_steps, CommandResult):
        return max_parallel_steps
    try:
        skip = toggled_skip_steps(
            effective_skip_steps(cfg, flow_config), enable=args.enable, disable=args.disable
        )
        insert = changed_insert_steps(
            effective_insert_steps(cfg, flow_config), insert=args.insert, remove=args.remove
        )
        plan = project_flow_plan(cfg, flow_config, skip_steps=skip, insert_steps=insert)
    except ValueError as exc:
        return _invalid_selection(exc)
    if plan is None:
        return _no_preset()
    view = status_view(
        plan,
        flow=_flow_label(cfg, flow_config),
        max_parallel_steps=max_parallel_steps,
        input_errors=validate_entry_inputs(cfg, plan.enabled_steps[0]),
    )
    return CommandResult(
        records=tuple(view_records(view)), exit_code=1 if view.status == "error" else 0
    )


def flow_edit(args: FlowEditInput, ctx: CommandContext) -> CommandResult:
    """Choose steps interactively (or with ``--enable``/``--disable``/``--insert``/
    ``--remove``) and save them.

    ``--max-parallel-steps`` changes that setting alongside. The new selection
    is shown for confirmation before ecc.toml is written unless ``--yes`` is
    given, so without a terminal only a flag change with ``--yes`` writes.
    """
    from chipcompiler.cli.project.flow_selection import (
        changed_insert_steps,
        effective_insert_steps,
        effective_lec_engine,
        effective_skip_steps,
        toggled_skip_steps,
    )
    from chipcompiler.data.flow_plan import flow_target, preset_chain
    from chipcompiler.rtl2gds import get_flow_builders

    selection = project_selection(ctx, "ecc flow edit")
    if isinstance(selection, CommandResult):
        return selection
    cfg, flow_config = selection
    if ctx.config is None:
        return CommandResult.err(
            [
                error_record(
                    "flow_edit_requires_ecc_toml",
                    reason="ecc flow edit writes ecc.toml; this project has none",
                    path=os.path.join(ctx.project_dir, CONFIG_FILENAME),
                )
            ]
        )
    if cfg.flow_preset not in get_flow_builders():
        # A project.json range (no preset) can be planned but not edited: the
        # edit writes a preset selection (preset, lec_engine, skip_steps).
        return _no_preset(" and ecc flow edit edits a preset's steps; set [flow] preset first")
    # The ecc.toml preset is the flow target; only the entry's policy keys apply.
    policy = _policy_keys(flow_config)
    toggles = bool(args.enable or args.disable or args.insert or args.remove)
    # Any flag skips the checkbox; the value only changes when asked to.
    direct = toggles or args.max_parallel_steps is not None
    # An explicit --max-parallel-steps replaces the declared value, so it is
    # also the way to correct an invalid one.
    max_parallel_steps = (
        _declared_max_parallel_steps(ctx, cfg, "ecc flow edit")
        if args.max_parallel_steps is None
        else args.max_parallel_steps
    )
    if isinstance(max_parallel_steps, CommandResult):
        return max_parallel_steps
    try:
        current = effective_skip_steps(cfg, policy)
        current_inserted = effective_insert_steps(cfg, policy)
        lec_engine = effective_lec_engine(cfg, policy)
        # The flow target always runs, so a policy that skips it is edited
        # with it enabled.
        target = flow_target(preset_chain(cfg.flow_preset, lec_engine=lec_engine))
        start = tuple(step for step in current if step != target)
        toggled = toggled_skip_steps(start, enable=args.enable, disable=args.disable)
        inserted = changed_insert_steps(current_inserted, insert=args.insert, remove=args.remove)
    except ValueError as exc:
        return _invalid_selection(exc)
    previous = Selection(current, current_inserted)
    # A flag selection is checked before asking anything: an invalid one is
    # reported whether or not it could be confirmed.
    chosen = Selection(toggled, inserted)
    plan = _checked_plan(cfg, lec_engine, chosen) if direct else None
    if isinstance(plan, CommandResult):
        return plan
    if plan is not None and args.yes:
        return _write(
            ctx,
            cfg,
            plan,
            chosen,
            lec_engine,
            max_parallel_steps,
            previous=previous,
            confirm=None,
        )
    if not _interactive(ctx):
        return CommandResult.err([_needs_terminal(direct=direct)])

    from rich.console import Console

    from chipcompiler.cli.interactive.terminal import terminal_keys

    console = Console(highlight=False)
    with terminal_keys() as read_key:
        if plan is None:
            edited = _edit_interactively(
                cfg,
                Selection(start, current_inserted),
                lec_engine,
                max_parallel_steps,
                console=console,
                read_key=read_key,
            )
            if edited is None:
                return _cancelled()
            max_parallel_steps = edited.max_parallel_steps
            chosen = Selection(edited.skip_steps, edited.insert_steps)
            plan = _checked_plan(cfg, lec_engine, chosen)
            if isinstance(plan, CommandResult):
                return plan
        confirm = None if args.yes else _terminal_confirm(console, read_key)
        return _write(
            ctx,
            cfg,
            plan,
            chosen,
            lec_engine,
            max_parallel_steps,
            previous=previous,
            confirm=confirm,
        )


def project_selection(
    ctx: CommandContext, command: str
) -> "tuple[ProjectConfig, FlowConfig | None] | CommandResult":
    """The effective project config and run flow config of the next fresh run."""
    from chipcompiler.cli.project import effective_config

    inspect = disclosure_cmd(command, ctx.project)
    if ctx.config_error:
        return CommandResult.err(
            [error_record("config_error", reason=ctx.config_error, inspect=inspect)]
        )
    cfg = ctx.config
    if ctx.project_state == "manifest" and not ctx.manifest_error:
        resolved = effective_config.resolve_effective_config(ctx, ctx.run_id, cfg)
        if isinstance(resolved, CommandResult):
            return resolved
        resolved_cfg, flow_config, _warnings = resolved
        return resolved_cfg, flow_config
    if cfg is None:
        if ctx.manifest_error:
            return CommandResult.err([manifest_error_record(ctx.manifest_error, inspect=inspect)])
        return CommandResult.err(
            [
                error_record(
                    "missing_config",
                    path=os.path.join(ctx.project_dir, CONFIG_FILENAME),
                    inspect=inspect,
                )
            ]
        )
    return cfg, None


def _declared_max_parallel_steps(
    ctx: CommandContext, cfg: "ProjectConfig", command: str
) -> int | CommandResult:
    """The project's ``[flow] max_parallel_steps``, or the configuration error."""
    from chipcompiler.cli.project.config import resolve_max_parallel_steps

    try:
        return resolve_max_parallel_steps(cfg)
    except ValueError as exc:
        return CommandResult.err(
            [
                error_record(
                    "config_error",
                    reason=str(exc),
                    inspect=disclosure_cmd(command, ctx.project),
                )
            ]
        )


def _checked_plan(
    cfg: "ProjectConfig", lec_engine: "LECEngineEnum", chosen: Selection
) -> "FlowPlan | CommandResult":
    """The plan of *chosen*, or the errors that keep it from being written."""
    try:
        plan = _preset_plan(cfg, lec_engine, chosen)
    except ValueError as exc:
        return _invalid_selection(exc)
    if not plan.errors:
        return plan
    return CommandResult.err(
        [
            error_record(
                "flow_selection_invalid",
                step=violation.step,
                missing=list(violation.missing_names),
                fixes=list(violation.fixes),
                reason=violation.message(),
            )
            for violation in plan.errors
        ]
    )


def _write(
    ctx: CommandContext,
    cfg: "ProjectConfig",
    plan: "FlowPlan",
    chosen: Selection,
    lec_engine: "LECEngineEnum",
    max_parallel_steps: int,
    *,
    previous: Selection,
    confirm: Confirm | None,
) -> CommandResult:
    """Ask *confirm* (None: ``--yes``), then write *plan* of *chosen* to ecc.toml [flow]."""
    from chipcompiler.cli.project.flow_selection import write_flow_selection

    config_path = os.path.join(ctx.project_dir, CONFIG_FILENAME)
    changes, warnings = _selection_records(
        ctx,
        cfg,
        plan,
        chosen,
        lec_engine,
        max_parallel_steps,
        previous=previous,
        config_path=config_path,
    )
    if confirm is not None and not confirm([changes, *warnings]):
        return _cancelled()
    write_flow_selection(
        config_path,
        preset=cfg.flow_preset,
        lec_engine=lec_engine.value,
        skip_steps=plan.skip_steps,
        # Kept as chosen: an inserted step whose step the preset lacks stays declared.
        insert_steps=chosen.insert_steps,
        max_parallel_steps=max_parallel_steps,
    )
    return CommandResult.ok(
        [
            {"record": "flow_edit", "status": "written", **changes},
            *warnings,
            *_shadow_warnings(ctx, config_path),
        ]
    )


def _selection_records(
    ctx: CommandContext,
    cfg: "ProjectConfig",
    plan: "FlowPlan",
    chosen: Selection,
    lec_engine: "LECEngineEnum",
    max_parallel_steps: int,
    *,
    previous: Selection,
    config_path: str,
) -> tuple[Record, list[Record]]:
    """What writing *plan* changes in ecc.toml [flow], and its warnings."""
    from chipcompiler.cli.project.design_inputs import validate_entry_inputs
    from chipcompiler.cli.project.flow_selection import mismatched_workspaces

    order = [step.name for step in plan.steps]
    was_skipped, now_skipped = set(previous.skip_steps), set(plan.skip_steps)
    was_inserted, now_inserted = set(previous.insert_steps), set(chosen.insert_steps)
    changes: Record = {
        "path": config_path,
        "preset": cfg.flow_preset,
        "lec_engine": lec_engine.value,
        "skip_steps": list(plan.skip_steps),
        "insert_steps": list(chosen.insert_steps),
        "max_parallel_steps": max_parallel_steps,
        "enabled": [name for name in order if name in was_skipped - now_skipped],
        "disabled": [name for name in order if name in now_skipped - was_skipped],
        "inserted": [name for name in chosen.insert_steps if name not in was_inserted],
        "removed": [name for name in previous.insert_steps if name not in now_inserted],
    }
    records: list[Record] = []
    records.extend(
        warning_record(
            "flow_step_degraded",
            step=violation.step,
            missing=list(violation.missing_names),
            fixes=list(violation.fixes),
            reason=violation.message(),
        )
        for violation in plan.warnings
    )
    entry = plan.enabled_steps[0]
    records.extend(
        warning_record("flow_input_missing", step=entry, reason=reason)
        for reason in validate_entry_inputs(cfg, entry)
    )
    section: Record = {
        "preset": cfg.flow_preset,
        "lec_engine": lec_engine.value,
        "skip_steps": list(plan.skip_steps),
        "insert_steps": list(chosen.insert_steps),
    }
    records.extend(
        warning_record(
            "workspace_flow_mismatch",
            workspace_id=workspace_id,
            workspace=path,
            # A derived workspace keeps its source's steps, so only these two
            # pick up the new selection.
            reason="the workspace ledger does not match the new selection; rerun it with "
            f"'ecc run --workspace {workspace_id} --overwrite', or run the selection in a "
            "new workspace with 'ecc run --workspace <new id>'",
        )
        for workspace_id, path in mismatched_workspaces(ctx.project_dir, section)
    )
    return changes, records


def _shadow_warnings(ctx: CommandContext, config_path: str) -> list[Record]:
    """The ``skip_steps_shadowed`` warning when project.json declares another policy."""
    if ctx.project_state != "manifest" or ctx.manifest_error:
        return []
    from chipcompiler.cli.project import effective_config
    from chipcompiler.cli.project.config import load_project_config

    resolved = effective_config.resolve_effective_config(
        ctx, ctx.run_id, load_project_config(config_path)
    )
    if isinstance(resolved, CommandResult):
        return []
    _cfg, _flow_config, warnings = resolved
    return [warning for warning in warnings if warning.get("warning") == "skip_steps_shadowed"]


def _edit_interactively(
    cfg: "ProjectConfig",
    current: Selection,
    lec_engine: "LECEngineEnum",
    max_parallel_steps: int,
    *,
    console: "Console",
    read_key: "KeyReader",
) -> "EditedSelection | None":
    from chipcompiler.cli.interactive.flow_edit import edit_selection
    from chipcompiler.cli.project.design_inputs import validate_entry_inputs
    from chipcompiler.cli.project.flow_status_view import StatusView, status_view

    def view_of(skip: tuple[str, ...], insert: tuple[str, ...]) -> StatusView:
        plan = _preset_plan(cfg, lec_engine, Selection(skip, insert))
        return status_view(
            plan,
            flow=cfg.flow_preset,
            max_parallel_steps=max_parallel_steps,
            input_errors=validate_entry_inputs(cfg, plan.enabled_steps[0]),
        )

    return edit_selection(
        current.skip_steps,
        current.insert_steps,
        view_of=view_of,
        console=console,
        read_key=read_key,
    )


def _terminal_confirm(console: "Console", read_key: "KeyReader") -> Confirm:
    from chipcompiler.cli.interactive.terminal import confirm_write
    from chipcompiler.cli.rendering.flow_selection_view import flow_edit_summary

    def confirm(records: Sequence[Record]) -> bool:
        return confirm_write(
            flow_edit_summary(records, written=False), console=console, read_key=read_key
        )

    return confirm


def _preset_plan(
    cfg: "ProjectConfig", lec_engine: "LECEngineEnum", chosen: Selection
) -> "FlowPlan":
    from chipcompiler.data.flow_plan import inserted_chain, plan_flow, preset_chain

    return plan_flow(
        preset_chain(cfg.flow_preset, lec_engine=lec_engine),
        skip_steps=chosen.skip_steps,
        inserted=inserted_chain(chosen.insert_steps, lec_engine=lec_engine),
    )


def _policy_keys(flow_config: "FlowConfig | None") -> Record:
    from chipcompiler.data.workspace_config import FLOW_POLICY_KEYS

    if flow_config is None:
        return {}
    return {key: flow_config[key] for key in FLOW_POLICY_KEYS if key in flow_config}


def _interactive(ctx: CommandContext) -> bool:
    """Text output on a terminal the checkbox can redraw (``TERM=dumb`` cannot)."""
    from chipcompiler.cli.interactive.terminal import interactive_terminal

    return ctx.output_mode is OutputMode.TEXT and interactive_terminal()


def _needs_terminal(*, direct: bool) -> Record:
    if direct:
        return error_record(
            "flow_edit_requires_confirmation",
            reason="writing ecc.toml asks for confirmation in a terminal; pass --yes to "
            "write without asking",
        )
    return error_record(
        "flow_edit_requires_terminal",
        reason="the checkbox editor needs an interactive terminal; pass --enable/--disable, "
        "--insert/--remove or --max-parallel-steps with --yes, or edit [flow] in ecc.toml",
    )


def _invalid_selection(exc: ValueError) -> CommandResult:
    return CommandResult.err([error_record("flow_selection_invalid", reason=str(exc))])


def _cancelled() -> CommandResult:
    return CommandResult.ok([{"record": "flow_edit", "status": "cancelled"}])


def _flow_label(cfg: "ProjectConfig", flow_config: "FlowConfig | None") -> str:
    start = flow_config.get("start_step") if flow_config is not None else None
    if isinstance(start, str) and start:
        end = flow_config.get("end_step") if flow_config is not None else None
        return f"{start}..{end if isinstance(end, str) and end else 'Harden'}"
    return cfg.flow_preset


def _no_preset(hint: str = "") -> CommandResult:
    return CommandResult.err(
        [error_record("flow_target_missing", reason=f"ecc.toml declares no [flow] preset{hint}")]
    )
