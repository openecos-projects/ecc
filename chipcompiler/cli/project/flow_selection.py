# pyright: strict
"""The step selection of a project: its preset chain minus ``skip_steps``
plus ``insert_steps``.

The skip policy comes from the run's flow config (manifest entry or CLI
range), else an explicit ``ecc.toml`` ``[flow] skip_steps``, else the code
default. Inserted steps (an LEC after a design-building step, ``lec@CTS``)
come from the run's flow config, else ``ecc.toml``; nothing is inserted by
default. Only a declared policy is checked against the step capabilities: the
code default is fixed and fits every preset.
"""

import os
from collections.abc import Collection, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, cast

from chipcompiler.cli.core.records import warning_record
from chipcompiler.data.flow_plan import FlowPlan, inserted_chain, plan_flow, preset_chain

if TYPE_CHECKING:
    from chipcompiler.cli.project.config import ProjectConfig
    from chipcompiler.data.types import LECEngineEnum

#: A run's flow config (preset, range or policy keys); see ``build_dynamic_flow_data``.
FlowConfig = Mapping[str, object]


def effective_skip_steps(cfg: "ProjectConfig", flow_config: FlowConfig | None) -> tuple[str, ...]:
    """Canonical skipped step names; raises ``ValueError`` for an invalid policy."""
    from chipcompiler.rtl2gds import resolve_skip_steps

    if flow_config is not None and "skip_steps" in flow_config:
        return resolve_skip_steps(flow_config)
    if "flow.skip_steps" in _explicit_keys(cfg):
        return resolve_skip_steps({"skip_steps": cfg.flow_skip_steps})
    return resolve_skip_steps(None)


def effective_insert_steps(cfg: "ProjectConfig", flow_config: FlowConfig | None) -> tuple[str, ...]:
    """Canonical inserted step names; raises ``ValueError`` for an invalid list."""
    from chipcompiler.rtl2gds import resolve_insert_steps

    if flow_config is not None and "insert_steps" in flow_config:
        return resolve_insert_steps(flow_config)
    if "flow.insert_steps" in _explicit_keys(cfg):
        return resolve_insert_steps({"insert_steps": cfg.flow_insert_steps})
    return ()


def changed_insert_steps(
    insert_steps: Collection[str], *, insert: Collection[str] = (), remove: Collection[str] = ()
) -> tuple[str, ...]:
    """*insert_steps* with *insert* added and *remove* removed, canonical.

    Entries are ``STEP@AFTER`` and accept the selector aliases. Raises
    ``ValueError`` for an invalid entry, an entry both inserted and removed,
    or removing a step that is not inserted.
    """
    from chipcompiler.rtl2gds import resolve_insert_steps

    added = set(resolve_insert_steps({"insert_steps": list(insert)}))
    removed = set(resolve_insert_steps({"insert_steps": list(remove)}))
    if conflict := sorted(added & removed):
        raise ValueError(f"steps both inserted and removed: {', '.join(conflict)}")
    if missing := sorted(removed - set(insert_steps)):
        raise ValueError(f"steps not inserted, nothing to remove: {', '.join(missing)}")
    return resolve_insert_steps({"insert_steps": sorted((set(insert_steps) | added) - removed)})


def toggled_skip_steps(
    skip_steps: Collection[str], *, enable: Collection[str] = (), disable: Collection[str] = ()
) -> tuple[str, ...]:
    """*skip_steps* with *enable* removed and *disable* added, canonical.

    Step spellings accept the selector aliases. Raises ``ValueError`` for an
    unknown step or a step both enabled and disabled.
    """
    from chipcompiler.data import StepEnum
    from chipcompiler.rtl2gds import normalize_flow_step, resolve_skip_steps

    if any(normalize_flow_step(name) == StepEnum.LEC.value for name in (*enable, *disable)):
        raise ValueError(
            "lec is not a flow step to enable or disable; insert it after a step with "
            "--insert lec@STEP (lec@Synthesis checks synthesis)"
        )
    enabled = set(resolve_skip_steps({"skip_steps": list(enable)}))
    disabled = set(resolve_skip_steps({"skip_steps": list(disable)}))
    if conflict := sorted(enabled & disabled):
        raise ValueError(f"steps both enabled and disabled: {', '.join(conflict)}")
    return resolve_skip_steps({"skip_steps": sorted((set(skip_steps) | disabled) - enabled)})


def project_flow_plan(
    cfg: "ProjectConfig",
    flow_config: FlowConfig | None,
    *,
    skip_steps: Collection[str] | None = None,
    insert_steps: Sequence[str] | None = None,
) -> FlowPlan | None:
    """The plan of the ledger a fresh run creates; None without a flow target.

    *skip_steps* and *insert_steps* replace the effective policy (for example
    an edited one). Raises ``ValueError`` for an invalid policy or a skipped
    flow boundary.
    """
    from chipcompiler import rtl2gds as rtl2gds_api

    lec_engine = effective_lec_engine(cfg, flow_config)
    skip = effective_skip_steps(cfg, flow_config) if skip_steps is None else tuple(skip_steps)
    inserted = inserted_chain(
        effective_insert_steps(cfg, flow_config) if insert_steps is None else insert_steps,
        lec_engine=lec_engine,
    )
    if (start := _flow_option(flow_config, "start_step")) is not None:
        end = _flow_option(flow_config, "end_step")
        return plan_flow(
            preset_chain("rtl2gds", lec_engine=lec_engine),
            skip_steps=skip,
            inserted=inserted,
            start=rtl2gds_api.normalize_flow_step(start),
            end=rtl2gds_api.normalize_flow_step(end) if end is not None else None,
        )
    if cfg.flow_preset not in rtl2gds_api.get_flow_builders():
        return None
    return plan_flow(
        preset_chain(cfg.flow_preset, lec_engine=lec_engine), skip_steps=skip, inserted=inserted
    )


def entry_step(cfg: "ProjectConfig", flow_config: FlowConfig | None) -> str | None:
    """The canonical first step a fresh run executes; None without a target.

    An explicit start step wins; otherwise the first step of the preset chain
    the skip policy keeps. An invalid policy falls back to the chain's first
    step and is reported by config validation.
    """
    from chipcompiler import rtl2gds as rtl2gds_api

    if (start := _flow_option(flow_config, "start_step")) is not None:
        return rtl2gds_api.normalize_flow_step(start)
    if cfg.flow_preset not in rtl2gds_api.get_flow_builders():
        return None
    names = [name for name, _tool in preset_chain(cfg.flow_preset)]
    try:
        skipped = set(effective_skip_steps(cfg, flow_config))
    except ValueError:
        skipped: set[str] = set()
    return next((name for name in names if name not in skipped), names[0] if names else None)


def selection_errors(cfg: "ProjectConfig", flow_config: FlowConfig | None) -> list[str]:
    """Why a declared skip policy or inserted steps cannot run; [] for the code default."""
    if not _policy_declared(cfg, flow_config):
        return []
    plan, error = _plan_or_error(cfg, flow_config)
    if error is not None:
        return [error]
    if plan is None:
        return []
    inserted = set(plan.insert_steps)
    return [
        f"flow.{'insert_steps' if violation.step in inserted else 'skip_steps'}: "
        f"{violation.message()}"
        for violation in plan.errors
    ]


def selection_warnings(
    cfg: "ProjectConfig", flow_config: FlowConfig | None
) -> list[dict[str, object]]:
    """One ``flow_step_degraded`` warning per step that runs without optional data."""
    if not _policy_declared(cfg, flow_config):
        return []
    plan, _error = _plan_or_error(cfg, flow_config)
    if plan is None:
        return []
    return [
        warning_record(
            "flow_step_degraded",
            step=violation.step,
            missing=list(violation.missing_names),
            fixes=list(violation.fixes),
            reason=violation.message(),
        )
        for violation in plan.warnings
    ]


def _plan_or_error(
    cfg: "ProjectConfig", flow_config: FlowConfig | None
) -> tuple[FlowPlan | None, str | None]:
    try:
        # Invalid names and engines are reported where they are declared.
        effective_skip_steps(cfg, flow_config)
        effective_lec_engine(cfg, flow_config)
        effective_insert_steps(cfg, flow_config)
    except ValueError:
        return None, None
    try:
        return project_flow_plan(cfg, flow_config), None
    except ValueError as exc:
        return None, f"flow.skip_steps: {exc}"


def _policy_declared(cfg: "ProjectConfig", flow_config: FlowConfig | None) -> bool:
    return any(
        (flow_config is not None and key in flow_config) or f"flow.{key}" in _explicit_keys(cfg)
        for key in ("skip_steps", "insert_steps")
    )


def effective_lec_engine(cfg: "ProjectConfig", flow_config: FlowConfig | None) -> "LECEngineEnum":
    """The run flow config's LEC engine, else ecc.toml's, else the code default."""
    from chipcompiler.rtl2gds import resolve_lec_engine

    if flow_config is not None and "lec_engine" in flow_config:
        return resolve_lec_engine(flow_config)
    if "flow.lec_engine" in _explicit_keys(cfg):
        return resolve_lec_engine({"lec_engine": cfg.flow_lec_engine})
    return resolve_lec_engine(None)


def _explicit_keys(cfg: "ProjectConfig") -> frozenset[str]:
    keys: object = getattr(cfg, "_explicit_keys", frozenset[str]())
    if not isinstance(keys, frozenset):
        return frozenset()
    return frozenset(str(key) for key in cast("frozenset[object]", keys))


def _flow_option(flow_config: FlowConfig | None, key: str) -> str | None:
    """A non-empty string option of *flow_config*; None when absent or empty."""
    value = flow_config.get(key) if flow_config is not None else None
    return value if isinstance(value, str) and value else None


def write_flow_selection(
    config_path: str,
    *,
    preset: str,
    lec_engine: str,
    skip_steps: Sequence[str],
    insert_steps: Sequence[str],
    max_parallel_steps: int,
) -> None:
    """Declare the whole selection in ``ecc.toml`` ``[flow]``, comments kept.

    Every key is written explicitly, the defaults included, so the file alone
    states which steps the next fresh run executes. ``insert_steps`` is the
    exception: nothing inserted is the absent key, so it is removed then.
    """
    from chipcompiler.cli.project.toml_edit import remove_scoped_key, set_scoped_key
    from chipcompiler.utility.file import write_text_atomic

    with open(config_path, encoding="utf-8") as f:
        text = f.read()
    for name, value in (
        ("preset", preset),
        ("lec_engine", lec_engine),
        ("skip_steps", list(skip_steps)),
        ("max_parallel_steps", max_parallel_steps),
    ):
        text = set_scoped_key(text, "flow", name, value)
    if insert_steps:
        text = set_scoped_key(text, "flow", "insert_steps", list(insert_steps))
    else:
        text = remove_scoped_key(text, "flow", "insert_steps") or text
    write_text_atomic(Path(config_path), text)


def mismatched_workspaces(
    project_dir: str, flow_section: dict[str, object]
) -> list[tuple[str, str]]:
    """(workspace id, path) of existing workspaces whose ledger *flow_section* contradicts.

    A fresh or ``--overwrite`` run applies a new selection; existing ledgers
    are never re-filtered.
    """
    from chipcompiler.engine.reconcile import classify_workspace
    from chipcompiler.project.manifest import MANIFEST_FILENAME, ManifestError, load_manifest

    if os.path.isfile(os.path.join(project_dir, MANIFEST_FILENAME)):
        try:
            workspaces = [
                (entry.workspace_id, entry.workspace_path)
                for entry in load_manifest(project_dir).workspaces
            ]
        except ManifestError:
            return []
    else:
        workspaces = [("default", os.path.join(project_dir, "default"))]
    return [
        (workspace_id, path)
        for workspace_id, path in workspaces
        if os.path.isfile(os.path.join(path, "home", "flow.json"))
        and classify_workspace(path, flow_section).outcome == "mismatch"
    ]
