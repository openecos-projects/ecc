#!/usr/bin/env python

"""Reconcile an existing workspace's persisted flow against a target range.

The flow target (``home/ecc.toml [flow]``, or the project ``ecc.toml
[flow]`` in project mode) describes intent; ``home/flow.json`` is the
execution ledger. This module compares them and, under the workspace lock,
appends missing suffix steps, adopts the new target, or repairs a stale
``[flow]`` — never deleting or invalidating successful prefix steps.

Outcomes:

- ``no_op``: persisted == target (or target is a prefix of persisted) and
  every step succeeded.
- ``resume``: same shape, but some step is not Success — resume from the
  first non-Success step.
- ``extended``: persisted was a proper prefix of the target; the missing
  suffix was appended as Unstart and the target adopted into ``[flow]``.
- ``repaired``: shapes matched but ``[flow]`` was stale (e.g. a crash
  between append and adopt); the section was rewritten in place.
- ``mismatch``: divergent flows — validation is pure-read, nothing was
  written; the caller surfaces flow_mismatch.
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


def compare_flows(persisted: list[tuple[str, str]], target: list[tuple[str, str]]) -> str:
    """Pairwise (name, tool) comparison of persisted vs target step lists."""
    if persisted == target:
        return "equal"
    if len(persisted) < len(target) and target[: len(persisted)] == persisted:
        return "proper_prefix"
    if len(target) < len(persisted) and persisted[: len(target)] == target:
        return "target_prefix"
    return "divergent"


def _target_entries(flow_section: dict) -> list[tuple[str, str]]:
    """(name, tool) entries for a [flow] section, over the canonical chain."""
    from chipcompiler.data.workspace import _canonical_harden_flow_entries
    from chipcompiler.data.workspace_config import flow_range_of

    flow_range = flow_range_of(flow_section)
    if flow_range is None:
        return []
    start, end = flow_range
    chain = _canonical_harden_flow_entries()
    names = [name for name, _tool, _state in chain]
    return [(name, tool) for name, tool, _s in chain[names.index(start) : names.index(end) + 1]]


def _derive_section_from_persisted(persisted: list[tuple[str, str]]) -> dict:
    """The [flow] section describing exactly the persisted step list."""
    if not persisted:
        return {}
    return {"start": persisted[0][0], "end": persisted[-1][0]}


@contextmanager
def _workspace_lock(workspace_dir: Path):
    home = workspace_dir / "home"
    home.mkdir(parents=True, exist_ok=True)
    with open(home / "workspace.lock", "a") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def resolve_target_section(project_flow: dict | None, workspace_flow: dict | None) -> dict:
    """Target precedence: project ecc.toml [flow] > home/ecc.toml [flow]."""
    if project_flow:
        return dict(project_flow)
    if workspace_flow:
        return dict(workspace_flow)
    return {}


def reconcile_workspace(
    workspace_dir: str | Path, target_section: dict | None = None
) -> ReconcileResult:
    """Reconcile the workspace's persisted flow with the target range.

    *target_section* is the effective [flow] section (already resolved per
    the caller's precedence). When None, the workspace's own
    ``home/ecc.toml [flow]`` is the target; when that is also absent, the
    persisted range itself is the target (nothing to reconcile).
    """
    from chipcompiler.data.workspace_config import (
        WorkspaceConfigError,
        WorkspaceFlowTargetError,
        load_workspace_config,
        save_workspace_config,
    )
    from chipcompiler.utility import json_read, json_write

    workspace_dir = Path(workspace_dir).resolve()
    flow_path = workspace_dir / "home" / "flow.json"

    with _workspace_lock(workspace_dir):
        flow_data = json_read(flow_path) if flow_path.exists() else {}
        if not isinstance(flow_data, dict):
            flow_data = {}
        persisted = _persisted_entries(flow_data)

        try:
            config = load_workspace_config(workspace_dir)
        except (WorkspaceConfigError, WorkspaceFlowTargetError) as exc:
            return ReconcileResult(outcome="mismatch", error=f"workspace_config_invalid: {exc}")
        params = {key: value for key, value in config.items() if key != "_flow"}
        workspace_flow = config["_flow"]

        if target_section is None:
            target_section = workspace_flow or _derive_section_from_persisted(persisted)
        target = _target_entries(target_section)

        if not persisted:
            return ReconcileResult(
                outcome="no_op",
                persisted=(),
                target=tuple(name for name, _tool in target),
            )

        relation = compare_flows(persisted, target)
        if relation == "divergent":
            return ReconcileResult(
                outcome="mismatch",
                persisted=tuple(name for name, _tool in persisted),
                target=tuple(name for name, _tool in target),
                error="flow_mismatch",
            )

        appended: list[str] = []
        adopted_flow: dict = {}
        outcome = None

        if relation == "proper_prefix":
            # Append the missing suffix as Unstart, then adopt the target.
            suffix = target[len(persisted) :]
            steps = flow_data.setdefault("steps", [])
            for name, tool in suffix:
                steps.append(
                    {
                        "name": name,
                        "tool": tool,
                        "state": "Unstart",
                        "runtime": "",
                        "peak memory (mb)": 0,
                        "info": {},
                    }
                )
                appended.append(name)
            if not json_write(flow_path, flow_data):
                return ReconcileResult(
                    outcome="mismatch",
                    error=f"failed to append flow steps to {flow_path}",
                )
            adopted_flow = dict(target_section)
            outcome = "extended"
        else:
            # equal or target_prefix: adopt the effective section when the
            # persisted [flow] is stale (crash between append and adopt, or
            # a hand-edited file). Staleness compares ranges, not section
            # form: preset="rcx" and start=Synthesis..end=sta describe the
            # same steps.
            from chipcompiler.data.workspace_config import flow_range_of

            effective = (
                dict(target_section)
                if relation == "equal"
                else _derive_section_from_persisted(persisted)
            )
            if workspace_flow:
                stale = flow_range_of(workspace_flow) != flow_range_of(effective)
            else:
                stale = bool(effective)
            if stale:
                adopted_flow = effective
                outcome = "repaired"

        if adopted_flow and not save_workspace_config(workspace_dir, params, adopted_flow):
            # flow.json is already consistent with the target; the stale
            # [flow] is repaired by the next reconcile (equal + stale →
            # repaired). Proceed with the run.
            logger.warning(
                "failed to adopt flow target into %s; will repair on next run",
                workspace_dir / "home" / "ecc.toml",
            )
            adopted_flow = {}

        if outcome is None:
            states = {
                str(step.get("state", ""))
                for step in flow_data.get("steps", [])
                if isinstance(step, dict)
            }
            outcome = "no_op" if states == {"Success"} else "resume"

        return ReconcileResult(
            outcome=outcome,
            persisted=tuple(name for name, _tool in _persisted_entries(flow_data)),
            target=tuple(name for name, _tool in target),
            appended=tuple(appended),
            adopted_flow=adopted_flow,
        )
