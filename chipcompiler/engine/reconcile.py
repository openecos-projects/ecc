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

Ledgers persisted in the pre-reorder chain order (DRC/LVS before filler,
RCX/STA/Harden as preset suffixes) are migrated onto the canonical chain by
step name instead of rejected: records up to ``route`` keep their states,
everything after restarts from Unstart, and the outcome falls back to
``repaired``/``resume``.

:func:`classify_workspace` exposes the pure-read phase to callers that
must reject a mismatch before loading (and thereby initializing or
migrating) the workspace; it additionally returns ``pending_mutation``
when the flow is compatible but an append/adopt is due.
"""

import fcntl
import logging
from contextlib import contextmanager
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


def compare_flows(persisted: list[tuple[str, str]], target: list[tuple[str, str]]) -> str:
    """Pairwise (name, tool) comparison of persisted vs target step lists."""
    if persisted == target:
        return "equal"
    if len(persisted) < len(target) and target[: len(persisted)] == persisted:
        return "proper_prefix"
    if len(target) < len(persisted) and persisted[: len(target)] == target:
        return "target_prefix"
    return "divergent"


def _is_legacy_missing_synthesis_lec(
    persisted: list[tuple[str, str]], target: list[tuple[str, str]]
) -> bool:
    """Recognize pre-synthesis-LEC ledgers as upgradeable flow prefixes."""
    if not any(name == "lec" and tool == "yosys_lec" for name, tool in target):
        return False
    target_without_lec = [entry for entry in target if entry != ("lec", "yosys_lec")]
    return persisted == target_without_lec or (
        len(persisted) < len(target_without_lec)
        and target_without_lec[: len(persisted)] == persisted
    )


# The pre-reorder canonical chain: DRC/LVS ran before filler, and RCX/STA/
# Harden were preset-only suffixes. Ledgers persisted in this shape map onto
# the current chain by step name.
_LEGACY_RTL2GDS_CHAIN = (
    ("Synthesis", "yosys"),
    ("lec", "yosys_lec"),
    ("Floorplan", "ecc"),
    ("place", "dreamplace"),
    ("CTS", "ecc"),
    ("legalization", "dreamplace"),
    ("Timing optimization", "sizer"),
    ("route", "ecc"),
    ("drc", "ecc"),
    ("lvs", "ecc"),
    ("filler", "ecc"),
    ("postRouteLec", "yosys_lec"),
    ("RCX", "ecc"),
    ("sta", "ecc"),
    ("Harden", "ecc"),
)


def _is_legacy_reordered_chain(persisted: list[tuple[str, str]]) -> bool:
    """Whether a ledger is an order-preserving slice of the pre-reorder chain.

    Legacy presets always began at Synthesis, so a ledger starting anywhere
    else is a foreign shape, not a legacy one.
    """
    if not persisted or persisted[0] != _LEGACY_RTL2GDS_CHAIN[0]:
        return False
    positions = {entry: index for index, entry in enumerate(_LEGACY_RTL2GDS_CHAIN)}
    taken = []
    for entry in persisted:
        position = positions.get(entry)
        if position is None:
            return False
        taken.append(position)
    return taken == sorted(set(taken)) and len(taken) == len(set(taken))


def _target_entries(flow_section: dict) -> list[tuple[str, str]]:
    """(name, tool) entries for a [flow] section, over the canonical chain."""
    from chipcompiler.data.workspace import _canonical_rtl2gds_flow_entries
    from chipcompiler.data.workspace_config import flow_range_of

    flow_range = flow_range_of(flow_section)
    if flow_range is None:
        return []
    start, end = flow_range
    chain = _canonical_rtl2gds_flow_entries()
    names = [name for name, _tool, _state in chain]
    return [(name, tool) for name, tool, _state in chain[names.index(start) : names.index(end) + 1]]


def _derive_section_from_persisted(persisted: list[tuple[str, str]]) -> dict:
    """The [flow] section describing exactly the persisted step list."""
    if not persisted:
        return {}
    return {"start": persisted[0][0], "end": persisted[-1][0]}


def _persisted_flow_data(workspace_dir: Path, json_read) -> dict:
    flow_data = json_read(workspace_dir / "home" / "flow.json")
    return flow_data if isinstance(flow_data, dict) else {}


@contextmanager
def _workspace_lock(workspace_dir: Path):
    # The lock lives NEXT TO the workspace (never inside it): an overwrite
    # deleting the tree cannot invalidate the lock's inode, so a waiter
    # always serializes against the run that replaces the directory.
    lock_path = workspace_dir.parent / f"{workspace_dir.name}.lock"
    workspace_dir.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        yield
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


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
    from chipcompiler.data.workspace_config import (
        WorkspaceConfigError,
        WorkspaceFlowTargetError,
        flow_range_of,
        load_workspace_config,
    )
    from chipcompiler.utility import json_read

    flow_data = _persisted_flow_data(workspace_dir, json_read)
    persisted = _persisted_entries(flow_data)

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
    if relation == "divergent" and _is_legacy_missing_synthesis_lec(persisted, target):
        relation = "legacy_missing_synthesis_lec"
    if relation == "divergent" and _is_legacy_reordered_chain(persisted):
        relation = "legacy_reordered_chain"
    if relation == "divergent":
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
    if (
        relation in {"proper_prefix", "legacy_missing_synthesis_lec", "legacy_reordered_chain"}
        or stale
    ):
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
        from chipcompiler.data.step import FINISHED_STEP_STATES

        target_states = {
            str(step.get("state", ""))
            for step in flow_data.get("steps", [])[: len(target)]
            if isinstance(step, dict)
        }
        return (
            ReconcileResult(
                outcome="no_op" if target_states <= FINISHED_STEP_STATES else "resume",
                persisted=_entry_names(persisted),
                target=_entry_names(target),
            ),
            {},
        )

    from chipcompiler.data.step import FINISHED_STEP_STATES

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
    workspace_dir: str | Path, target_section: dict | None = None
) -> ReconcileResult:
    """Pure-read classification of the workspace against the target range.

    Use before loading/initializing a workspace: a ``mismatch`` result
    guarantees nothing was written (no lock, no migration, no home.json).
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

    with _workspace_lock(workspace_dir):
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
        import copy

        from chipcompiler.data.workspace import _flow_step_template

        context["flow_data_original"] = copy.deepcopy(flow_data)
        steps = flow_data.setdefault("steps", [])
        for name, tool in target[len(persisted) :]:
            steps.append(_flow_step_template(name, tool, "Unstart"))
            appended.append(name)
        if not json_write(workspace_dir / "home" / "flow.json", flow_data):
            return ReconcileResult(
                outcome="mismatch",
                error=f"failed to append flow steps to {workspace_dir / 'home' / 'flow.json'}",
            )
        adopted_flow = dict(target_section)
        outcome = "extended"
    elif relation == "legacy_missing_synthesis_lec":
        # Insert the newly required synthesis-level LEC while preserving all
        # existing step records and their states.
        import copy

        from chipcompiler.data.workspace import _flow_step_template

        context["flow_data_original"] = copy.deepcopy(flow_data)
        steps = flow_data.setdefault("steps", [])
        lec_index = next(index for index, (name, _tool) in enumerate(target) if name == "lec")
        lec_name, lec_tool = target[lec_index]
        steps.insert(lec_index, _flow_step_template(lec_name, lec_tool, "Unstart"))
        appended.append(lec_name)
        for name, tool in target[len(persisted) + 1 :]:
            steps.append(_flow_step_template(name, tool, "Unstart"))
            appended.append(name)
        if not json_write(workspace_dir / "home" / "flow.json", flow_data):
            return ReconcileResult(
                outcome="mismatch",
                error=f"failed to insert flow step into {workspace_dir / 'home' / 'flow.json'}",
            )
        adopted_flow = dict(target_section)
        outcome = "extended"
    elif relation == "legacy_reordered_chain":
        # Map a pre-reorder ledger onto the canonical chain by step name:
        # the Synthesis..route prefix is identical in both orders and keeps
        # its records; every post-route step ran with pre-reorder inputs
        # (DRC/LVS before filler), so it restarts from Unstart.
        import copy

        from chipcompiler.data.workspace import (
            _canonical_rtl2gds_flow_entries,
            _flow_step_template,
        )

        context["flow_data_original"] = copy.deepcopy(flow_data)
        persisted_by_name = {
            step.get("name"): step for step in flow_data.get("steps", []) if isinstance(step, dict)
        }
        chain_names = [name for name, _tool, _state in _canonical_rtl2gds_flow_entries()]
        route_position = chain_names.index("route")
        steps = []
        for name, tool in target:
            old = persisted_by_name.get(name)
            if old is not None and chain_names.index(name) <= route_position:
                steps.append(old)
            else:
                steps.append(_flow_step_template(name, tool, "Unstart"))
                if name not in persisted_by_name:
                    appended.append(name)
        flow_data["steps"] = steps
        if not json_write(workspace_dir / "home" / "flow.json", flow_data):
            return ReconcileResult(
                outcome="mismatch",
                error=f"failed to rewrite flow steps into {workspace_dir / 'home' / 'flow.json'}",
            )
        adopted_flow = dict(target_section)
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
        if appended:
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
        from chipcompiler.data.step import FINISHED_STEP_STATES

        if relation == "target_prefix":
            # The persisted flow already covers the target: no-op only
            # when every step within the requested target range finished.
            flow_data = _persisted_flow_data(workspace_dir, json_read)
            target_states = {
                str(step.get("state", ""))
                for step in flow_data.get("steps", [])[: len(target)]
                if isinstance(step, dict)
            }
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
