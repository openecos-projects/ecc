"""Where each step of a workspace lives, as its flow ledger records it.

Readers of step artifacts (signoff, checklists, QoR, reports) look a step's
directory up here instead of spelling ``<step>_<tool>`` themselves, so they
follow whatever directory the step was created in.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Protocol, cast, runtime_checkable

from chipcompiler.data.step import (
    STEP_DIRECTORIES,
    all_step_directories,
    recorded_step_directory,
    step_directory_for_tool,
)
from chipcompiler.data.workspace.flow_types import load_flow_document


@runtime_checkable
class _HasFlowSteps(Protocol):
    def steps(self) -> Sequence[Mapping[str, object]]: ...


class _HasDirectory(Protocol):
    @property
    def directory(self) -> Path: ...


@dataclass(frozen=True, slots=True)
class StepDirectories:
    """Step name to directory for one workspace.

    A ledger step that records its directory uses it. Any other step keeps the
    legacy name readers have always used: the engine-aware ``<step>_<tool>``
    lookup for a ledger step, ``STEP_DIRECTORIES`` for a step not in the
    ledger. Workspaces created before steps recorded a directory read unchanged.
    """

    root: Path
    by_step: Mapping[str, str]
    #: Directory names the ledger records explicitly, in ledger order.
    recorded: tuple[str, ...]

    @classmethod
    def from_records(cls, root: Path, records: Iterable[object]) -> "StepDirectories":
        by_step: dict[str, str] = {}
        recorded: list[str] = []
        for record in records:
            if not isinstance(record, Mapping):
                continue
            entry = cast("Mapping[str, object]", record)
            name = entry.get("name")
            if not isinstance(name, str):
                continue
            if "directory" in entry:
                directory = recorded_step_directory(entry)
                recorded.append(directory)
            else:
                tool = entry.get("tool")
                directory = step_directory_for_tool(name, tool if isinstance(tool, str) else None)
            by_step[name] = directory
        return cls(Path(root), MappingProxyType(by_step), tuple(recorded))

    @classmethod
    def of(cls, workspace: _HasDirectory) -> "StepDirectories":
        """The directories *workspace*'s ledger records (none without a ledger)."""
        flow = getattr(workspace, "flow", None)
        steps = flow.steps() if isinstance(flow, _HasFlowSteps) else ()
        return cls.from_records(Path(workspace.directory), steps)

    @classmethod
    def at(cls, root: Path | str) -> "StepDirectories":
        """The directories recorded in ``home/flow.json`` under *root*."""
        document = load_flow_document(Path(root) / "home" / "flow.json")
        return cls.from_records(Path(root), document.get("steps", []))

    def name(self, step: str) -> str:
        return self.by_step.get(step) or STEP_DIRECTORIES.get(step, step)

    def path(self, step: str) -> Path:
        return self.root / self.name(step)

    def scan_names(self) -> list[str]:
        """Every directory a whole-workspace scan visits, recorded ones first."""
        return list(dict.fromkeys([*self.recorded, *all_step_directories()]))
