#!/usr/bin/env python

"""Reconcile an existing workspace's persisted flow against a target range.

The flow target (``home/params.toml [flow]``, or the project ``ecc.toml
[flow]`` in project mode) describes intent; ``home/flow.json`` is the
execution ledger. This module compares them and, under the workspace lock,
appends missing suffix steps, adopts the new target, or repairs a stale
``[flow]`` — never deleting or invalidating successful prefix steps.

Classification is pure-read and happens BEFORE any lock file or workspace
initialization: a ``mismatch`` (or a read-only outcome) never creates the
sibling ``<workspace>.lock`` nor touches the tree. Only when the flow is
compatible but needs an append/adopt does reconcile take the lock, re-read,
reclassify, and mutate.

Outcomes:

- ``no_op``: persisted == target (or target is a prefix of persisted) and
  every step finished (Success).
- ``resume``: same shape, but some step is not finished — resume from the
  first unfinished step.
- ``extended``: persisted was a proper prefix of the target; the missing
  suffix was appended as Unstart and the target adopted into ``[flow]``.
- ``repaired``: shapes matched but ``[flow]`` was stale (e.g. a crash
  between append and adopt); the section was rewritten in place.
- ``mismatch``: divergent flows — validation is pure-read, nothing was
  written; the caller surfaces flow_mismatch.

:func:`classify_workspace` exposes the pure-read phase to callers that
must reject a mismatch before loading and initializing the workspace; it
additionally returns ``pending_mutation``
when the flow is compatible but an append/adopt is due.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReconcileResult:
    outcome: str
    persisted: tuple[str, ...] = ()
    target: tuple[str, ...] = ()
    appended: tuple[str, ...] = ()
    adopted_flow: dict = field(default_factory=dict)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.outcome != "mismatch"


def _persisted_entries(flow_data: dict) -> list[tuple[str, str]]:
    steps = flow_data.get("steps", [])
    if not isinstance(steps, list):
        return []
    return [
        (str(step.get("name", "")), str(step.get("tool", "")))
        for step in steps
        if isinstance(step, dict)
    ]


def _entry_names(entries: list[tuple[str, str]]) -> tuple[str, ...]:
    return tuple(name for name, _tool in entries)


def _target_step_states(flow_data: dict, target: list[tuple[str, str]]) -> set[str]:
    """States of the ledger steps the target names, matched by step name.

    Name matching (not position slicing) keeps skipped ledger entries from
    shifting which states fall inside the evaluated target range.
    """
    states_by_name = {
        str(step.get("name", "")): str(step.get("state", ""))
        for step in flow_data.get("steps", [])
        if isinstance(step, dict)
    }
    return {states_by_name.get(name, "") for name, _tool in target}


def compare_flows(persisted: list[tuple[str, str]], target: list[tuple[str, str]]) -> str:
    """Pairwise (name, tool) comparison of persisted vs target step lists."""
    if persisted == target:
        return "equal"
    if len(persisted) < len(target) and target[: len(persisted)] == persisted:
        return "proper_prefix"
    if len(target) < len(persisted) and persisted[: len(target)] == target:
        return "target_prefix"
    return "divergent"


def _relation_with_skipped_steps(
    persisted: list[tuple[str, str]], target: list[tuple[str, str]], skip: tuple[str, ...]
) -> str:
    """Compatibility relation treating policy-skipped ledger steps as inert.

    A ledger written under a wider policy (e.g. with diff_opt enabled)
    stays runnable when the effective policy excludes those
    steps: the excluded entries are ignored for comparison and never
    removed from the ledger. An entry only counts as a skipped step when
    its (name, tool) pair matches the canonical chain — a corrupted entry
    (right name, wrong tool) is never silently ignored. A check inserted
    after an ignored step goes with it, as it runs only with its step.
    Returns "" when the ledger is not compatible even after ignoring
    skipped steps.
    """
    from chipcompiler.data import LEC_STEP_TOOLS
    from chipcompiler.data.workspace import _canonical_rtl2gds_flow_entries
    from chipcompiler.rtl2gds import parse_inserted_step

    # A corrupted (right name, foreign tool) entry is never silently ignored.
    canonical_tools = {name: tool for name, tool, _state in _canonical_rtl2gds_flow_entries()}
    excluded = set(skip)
    kept = [
        entry
        for entry in persisted
        if not (entry[0] in excluded and entry[1] == canonical_tools.get(entry[0]))
    ]
    ignored = {name for name, _tool in persisted} - {name for name, _tool in kept}
    kept = [
        (name, tool)
        for name, tool in kept
        if not (
            (parsed := parse_inserted_step(name)) is not None
            and parsed[1] in ignored
            and tool in LEC_STEP_TOOLS
        )
    ]
    if kept == target:
        return "equal"
    if len(kept) < len(target) and target[: len(kept)] == kept:
        return "proper_prefix"
    if len(target) < len(kept) and kept[: len(target)] == target:
        return "target_prefix"
    return ""


#: What older ECC versions recorded for LEC and no longer exists: the
#: synthesis ``lec`` chain step and the Yosys and dual engines.
_REMOVED_LEC_STEP = "lec"
_REMOVED_LEC_TOOLS = frozenset({"yosys_lec", "lec_dual"})


def _built_with_removed_lec(workspace_dir: Path, persisted: list[tuple[str, str]]) -> bool:
    """Whether a workspace was built with an LEC step or engine ECC removed.

    Its ledger records one, or its ``home/params.toml`` [flow] names one
    (a flow whose LEC steps were all skipped). Such a workspace is a
    flow_mismatch whatever target it is compared with, decided before that
    [flow], which no longer validates, is loaded.
    """
    import tomllib

    from chipcompiler.data.workspace_config import workspace_config_path

    if any(name == _REMOVED_LEC_STEP or tool in _REMOVED_LEC_TOOLS for name, tool in persisted):
        return True
    try:
        document = tomllib.loads(workspace_config_path(workspace_dir).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return False
    flow = document.get("flow")
    if not isinstance(flow, dict):
        return False
    # Other value types are left to the [flow] validator.
    names = (flow.get("lec_engine"), flow.get("start"), flow.get("end"))
    return any(
        isinstance(name, str) and (name in _REMOVED_LEC_TOOLS or name == _REMOVED_LEC_STEP)
        for name in names
    )


def _insertions_differ(persisted: list[tuple[str, str]], target: list[tuple[str, str]]) -> bool:
    """Whether the two insert different steps after a step both of them run.

    Inserted steps belong to the flow target, so adding or removing one is a
    flow_mismatch, also after the ledger's last step, where the shape
    comparison alone would append the new check (``proper_prefix``) or
    ignore the removed one (``target_prefix``). Steps only one side runs are
    left to that comparison.
    """
    from chipcompiler.rtl2gds import parse_inserted_step

    def inserted_after(entries: list[tuple[str, str]]) -> dict[str, set[str]]:
        steps: dict[str, set[str]] = {}
        for name, _tool in entries:
            if parsed := parse_inserted_step(name):
                steps.setdefault(parsed[1], set()).add(name)
        return steps

    def chain_steps(entries: list[tuple[str, str]]) -> set[str]:
        return {name for name, _tool in entries if parse_inserted_step(name) is None}

    persisted_inserted, target_inserted = inserted_after(persisted), inserted_after(target)
    return any(
        persisted_inserted.get(step, set()) != target_inserted.get(step, set())
        for step in chain_steps(persisted) & chain_steps(target)
    )


def _resolved_skip_steps(flow_section: dict) -> tuple[str, ...]:
    """The skip policy a [flow] section carries (default when undeclared)."""
    from chipcompiler.rtl2gds import resolve_skip_steps

    return resolve_skip_steps(flow_section)


def _target_entries(flow_section: dict) -> list[tuple[str, str]]:
    """(name, tool) entries for a [flow] section, over the canonical chain.

    The section's skip policy (its declared list, or the code default when
    undeclared) is applied to the chain, so the target never contains steps
    the workspace excludes; its inserted steps follow their steps inside the
    range, run by the section's LEC engine.
    """
    from chipcompiler.data.workspace import _canonical_rtl2gds_flow_entries
    from chipcompiler.data.workspace.flow_data import _flow_entries_for_config
    from chipcompiler.data.workspace_config import flow_range_of
    from chipcompiler.rtl2gds import (
        filter_flow_steps,
        insert_flow_steps,
        resolve_insert_steps,
        resolve_lec_engine,
    )

    flow_range = flow_range_of(flow_section)
    if flow_range is None:
        return []
    start, end = flow_range
    preset = flow_section.get("preset") if isinstance(flow_section, dict) else None
    chain = (
        _flow_entries_for_config({"preset": preset})
        if isinstance(preset, str)
        else _canonical_rtl2gds_flow_entries()
    )
    names = [name for name, _tool, _state in chain]
    entries = [
        (name, tool) for name, tool, _state in chain[names.index(start) : names.index(end) + 1]
    ]
    entries = filter_flow_steps(entries, _resolved_skip_steps(flow_section))
    lec_tool = resolve_lec_engine(flow_section).value
    with_inserted = insert_flow_steps(
        [(name, tool, "") for name, tool in entries],
        resolve_insert_steps(flow_section),
        lec_tool,
    )
    return [(name, tool) for name, tool, _state in with_inserted]


def _derive_section_from_persisted(persisted: list[tuple[str, str]]) -> dict:
    """The [flow] section describing exactly the persisted step list."""
    from chipcompiler.data.workspace_config import ledger_flow_section

    return ledger_flow_section([name for name, _tool in persisted])


def _persisted_flow_data(workspace_dir: Path, json_read) -> dict:
    flow_data = json_read(workspace_dir / "home" / "flow.json")
    return flow_data if isinstance(flow_data, dict) else {}


def resolve_target_section(project_flow: dict | None, workspace_flow: dict | None) -> dict:
    """Target precedence: project ecc.toml [flow] > home/params.toml [flow]."""
    if project_flow:
        return dict(project_flow)
    if workspace_flow:
        return dict(workspace_flow)
    return {}


def _probe_workspace(workspace_dir: Path, target_section: dict | None):
    """Pure-read classification plus the loaded inputs a mutation would need.

    Returns (ReconcileResult, context) — the context dict is populated
    only for ``pending_mutation``. The outcome is ``mismatch``, ``no_op``,
    ``resume``, or ``pending_mutation`` (compatible, but an append/adopt
    is due). Nothing is created or written here: no lock, no config
    initialization, no ledger rewrite.
    """
    from chipcompiler.data.schema_versions import (
        FLOW_JSON,
        UnsupportedSchemaVersionError,
        ensure_supported_schema_version,
    )
    from chipcompiler.data.workspace_config import (
        WorkspaceConfigError,
        WorkspaceFlowTargetError,
        flow_range_of,
        load_workspace_config,
    )
    from chipcompiler.utility import json_read

    flow_data = _persisted_flow_data(workspace_dir, json_read)
    flow_path = workspace_dir / "home" / "flow.json"
    try:
        ensure_supported_schema_version(FLOW_JSON, flow_path, flow_data)
    except UnsupportedSchemaVersionError as exc:
        return ReconcileResult(outcome="mismatch", error=f"unsupported_schema_version: {exc}"), {}
    persisted = _persisted_entries(flow_data)
    if _built_with_removed_lec(workspace_dir, persisted):
        return (
            ReconcileResult(
                outcome="mismatch", persisted=_entry_names(persisted), error="flow_mismatch"
            ),
            {},
        )

    try:
        config = load_workspace_config(workspace_dir)
    except FileNotFoundError:
        config = {"_flow": {}}
    except (WorkspaceConfigError, WorkspaceFlowTargetError) as exc:
        return ReconcileResult(outcome="mismatch", error=f"workspace_config_invalid: {exc}"), {}
    except OSError as exc:
        # An existing but unreadable home/params.toml (permissions, a directory
        # in its place) is invalid configuration, never an uncaught traceback.
        return ReconcileResult(outcome="mismatch", error=f"workspace_config_invalid: {exc}"), {}
    workspace_flow = config["_flow"]

    if target_section is None:
        target_section = workspace_flow or _derive_section_from_persisted(persisted)
    try:
        target = _target_entries(target_section)
    except WorkspaceFlowTargetError as exc:
        # Reached when the target had to be derived from the persisted
        # ledger (no [flow] anywhere): unknown persisted step names — a
        # foreign or hand-edited flow.json — make the ledger unreadable,
        # which is a recorded mismatch, never an uncaught exception.
        return (
            ReconcileResult(
                outcome="mismatch",
                error=f"workspace_config_invalid: the persisted flow is not on "
                f"the canonical chain: {exc}",
            ),
            {},
        )

    if not persisted:
        return ReconcileResult(outcome="no_op", target=_entry_names(target)), {}

    relation = compare_flows(persisted, target)
    if relation == "divergent":
        # A ledger holding steps the target's policy skips stays compatible:
        # the skipped entries are inert, never removed or re-inserted.
        relation = (
            _relation_with_skipped_steps(
                persisted,
                target,
                _resolved_skip_steps(target_section or {}),
            )
            or relation
        )
    if relation == "divergent" or _insertions_differ(persisted, target):
        return (
            ReconcileResult(
                outcome="mismatch",
                persisted=_entry_names(persisted),
                target=_entry_names(target),
                error="flow_mismatch",
            ),
            {},
        )

    if workspace_flow:
        stale = flow_range_of(workspace_flow) != flow_range_of(target_section)
    else:
        stale = bool(target_section)
    if relation == "proper_prefix" or stale:
        context = {
            "flow_data": flow_data,
            "persisted": persisted,
            "target": target,
            "target_section": target_section,
            "params": {key: value for key, value in config.items() if key != "_flow"},
            "relation": relation,
        }
        return (
            ReconcileResult(
                outcome="pending_mutation",
                persisted=_entry_names(persisted),
                target=_entry_names(target),
            ),
            context,
        )

    if relation == "target_prefix":
        # The persisted flow already covers the target: no-op only when
        # every step WITHIN the requested target range finished; an
        # unfinished one resumes. Steps beyond the target are never the
        # run's business.
        from chipcompiler.data.types import FINISHED_STEP_STATES

        target_states = _target_step_states(flow_data, target)
        return (
            ReconcileResult(
                outcome="no_op" if target_states <= FINISHED_STEP_STATES else "resume",
                persisted=_entry_names(persisted),
                target=_entry_names(target),
            ),
            {},
        )

    from chipcompiler.data.types import FINISHED_STEP_STATES

    states = {
        str(step.get("state", "")) for step in flow_data.get("steps", []) if isinstance(step, dict)
    }
    outcome = "no_op" if states <= FINISHED_STEP_STATES else "resume"
    return (
        ReconcileResult(
            outcome=outcome,
            persisted=_entry_names(persisted),
            target=_entry_names(target),
        ),
        {},
    )


def classify_workspace(
    workspace_dir: str | Path, target_section: dict[str, object] | None = None
) -> ReconcileResult:
    """Pure-read classification of the workspace against the target range.

    Use before loading/initializing a workspace: a ``mismatch`` result
    guarantees nothing was written and no lock was taken.
    ``pending_mutation`` means the flow is compatible but an append/adopt
    is due — load the workspace and call :func:`reconcile_workspace`,
    which re-classifies under the lock before writing.
    """
    probe, _context = _probe_workspace(Path(workspace_dir).resolve(), target_section)
    return probe


def reconcile_workspace_locked(
    workspace_dir: str | Path, target_section: dict | None = None
) -> ReconcileResult:
    """Reconcile assuming the caller already holds the workspace lock.

    Same re-probe-and-apply as :func:`reconcile_workspace` but without
    acquiring the lock again — used when execution ownership must span
    revalidation, the engine run, and terminal persistence.
    """
    workspace_dir = Path(workspace_dir).resolve()

    probe, context = _probe_workspace(workspace_dir, target_section)
    if probe.outcome != "pending_mutation":
        return probe
    return _apply_mutation(workspace_dir, probe, context)


def reconcile_workspace(
    workspace_dir: str | Path, target_section: dict | None = None
) -> ReconcileResult:
    """Reconcile the workspace's persisted flow with the target range.

    *target_section* is the effective [flow] section (already resolved per
    the caller's precedence). When None, the workspace's own
    ``home/params.toml [flow]`` is the target; when that is also absent, the
    persisted range itself is the target (nothing to reconcile).
    """
    workspace_dir = Path(workspace_dir).resolve()

    probe, _context = _probe_workspace(workspace_dir, target_section)
    if probe.outcome != "pending_mutation":
        # Mismatch and read-only outcomes never see the lock created.
        return probe

    from chipcompiler.utility.workspace_lock import workspace_lock

    with workspace_lock(workspace_dir):
        # Re-read and reclassify under the lock: a concurrent reconcile may
        # already have appended or repaired, downgrading this to read-only.
        fresh, context = _probe_workspace(workspace_dir, target_section)
        if fresh.outcome != "pending_mutation":
            return fresh
        return _apply_mutation(workspace_dir, fresh, context)


def _apply_mutation(workspace_dir: Path, probe: ReconcileResult, context: dict) -> ReconcileResult:
    """Append/adopt under the workspace lock for a pending classification."""
    from chipcompiler.data.workspace_config import save_workspace_config
    from chipcompiler.utility import json_read, json_write

    persisted = context["persisted"]
    target = context["target"]
    target_section = context["target_section"]
    flow_data = context["flow_data"]
    relation = context["relation"]

    appended: list[str] = []
    adopted_flow: dict = {}
    outcome = None

    if relation == "proper_prefix":
        # Append the missing suffix as Unstart, then adopt the target.
        # Entries already in the ledger (e.g. steps the effective policy
        # now skips) are never appended twice, so the suffix is computed
        # against what the ledger actually holds.
        import copy

        from chipcompiler.data.step import next_step_index
        from chipcompiler.data.workspace import _flow_step_template

        context["flow_data_original"] = copy.deepcopy(flow_data)
        steps = flow_data.setdefault("steps", [])
        present = set(persisted)
        for name, tool in target:
            if (name, tool) in present:
                continue
            steps.append(_flow_step_template(name, tool, "Unstart", index=next_step_index(steps)))
            appended.append(name)
        if not json_write(workspace_dir / "home" / "flow.json", flow_data):
            return ReconcileResult(
                outcome="mismatch",
                error=f"failed to append flow steps to {workspace_dir / 'home' / 'flow.json'}",
            )
        adopted_flow = dict(target_section)
        outcome = "extended"
    else:
        # Adopt the effective target when the persisted [flow] is stale
        # (crash between append and adopt, a hand-edited file, or an
        # older wider intent superseded by the current target).
        # Staleness compares ranges, not section form: a named preset and
        # its equivalent start/end range describe the same steps. Adoption
        # always writes the effective target itself — never a range
        # derived from the persisted ledger — so extra persisted steps
        # are kept but never become the target.
        adopted_flow = dict(target_section)

    if adopted_flow and not save_workspace_config(workspace_dir, context["params"], adopted_flow):
        # A stale [flow] must never survive a completed run: adoption
        # failure is an error, not a tolerated partial state. Roll the
        # ledger back too — leaving the appended suffix behind would
        # report failure while the persisted flow is wider than the target.
        if "flow_data_original" in context:
            json_write(workspace_dir / "home" / "flow.json", context["flow_data_original"])
        return ReconcileResult(
            outcome="mismatch",
            persisted=probe.persisted,
            target=probe.target,
            error=(
                "flow_adopt_failed: failed to adopt flow target into "
                f"{_config_path_text(workspace_dir)}"
            ),
        )

    if outcome is None:
        from chipcompiler.data.types import FINISHED_STEP_STATES

        if relation == "target_prefix":
            # The persisted flow already covers the target: no-op only
            # when every step within the requested target range finished.
            flow_data = _persisted_flow_data(workspace_dir, json_read)
            target_states = _target_step_states(flow_data, target)
            outcome = "no_op" if target_states <= FINISHED_STEP_STATES else "resume"
        else:
            flow_data = _persisted_flow_data(workspace_dir, json_read)
            states = {
                str(step.get("state", ""))
                for step in flow_data.get("steps", [])
                if isinstance(step, dict)
            }
            outcome = "repaired" if states <= FINISHED_STEP_STATES else "resume"

    return ReconcileResult(
        outcome=outcome,
        persisted=_entry_names(_persisted_entries(flow_data)),
        target=probe.target,
        appended=tuple(appended),
        adopted_flow=adopted_flow,
    )


def _config_path_text(workspace_dir) -> str:
    """The workspace config path for messages — single-sourced name."""
    from chipcompiler.data.workspace_config import workspace_config_path

    return str(workspace_config_path(workspace_dir))
