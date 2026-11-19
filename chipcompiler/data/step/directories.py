"""Where each step of a workspace lives: directory names and their lookup.

Workspace creation names each step directory ``<step>_<tool>``, prefixed with
the step's position in the flow for ledgers that record it
(``07_placement_dreamplace``). Checklists, signoff packages, QoR scoring and the
design reports resolve per-step artifacts through this module instead of
spelling directory names themselves.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePath
from types import MappingProxyType
from typing import Final, Protocol, cast, runtime_checkable

from chipcompiler.data.types import SkippableStepEnum, StepEnum, ToolName

# The tool each step runs along the canonical rtl2gds chain, and the base
# ``<step>_<tool>`` directory names derived from it. They identify inherited
# directories and steps absent from a bounded derived ledger. Timing
# optimization owns no artifact directory any consumer reads through these tables.
# Keyed by step members; a member is a str, so a plain step name looks it up.
STEP_TOOLS: Final[dict[str, ToolName]] = {
    StepEnum.SYNTHESIS: ToolName.YOSYS,
    StepEnum.PRE_FLOORPLAN: ToolName.ECC,
    StepEnum.MACRO_PLACEMENT: ToolName.DREAMPLACE,
    StepEnum.POST_FLOORPLAN: ToolName.ECC,
    StepEnum.PREPLACE: ToolName.SIZER,
    StepEnum.PLACEMENT: ToolName.DREAMPLACE,
    SkippableStepEnum.DIFF_OPT: ToolName.DREAMPLACE,
    StepEnum.DIFF_SIZING: ToolName.DREAMPLACE,
    StepEnum.CTS: ToolName.ECC,
    StepEnum.LEGALIZATION: ToolName.DREAMPLACE,
    StepEnum.ROUTING: ToolName.ECC,
    StepEnum.FILLER: ToolName.ECC,
    StepEnum.RCX: ToolName.ECC,
    StepEnum.STA: ToolName.ECC,
    StepEnum.POWER_ANALYSIS: ToolName.ECC,
    StepEnum.EMIR: ToolName.ECC,
    StepEnum.LVS: ToolName.ECC,
    SkippableStepEnum.POST_ROUTE_LEC: ToolName.KEPLER_FORMAL,
    StepEnum.DRC: ToolName.ECC,
    StepEnum.ANTENNA_CHECK: ToolName.ECC,
    StepEnum.HARDEN: ToolName.ECC,
    StepEnum.DEFVIEW: ToolName.ECC,
}
STEP_DIRECTORIES: Final[dict[str, str]] = {
    step: f"{step}_{tool}" for step, tool in STEP_TOOLS.items()
}


def step_directory_for_tool(step_name: str, tool: str | None) -> str:
    """The base directory of *step_name* run by *tool*."""
    directory = STEP_DIRECTORIES.get(step_name)
    if directory is not None:
        return directory
    return f"{step_name}_{tool}"


def all_step_directories() -> list[str]:
    """All base step directories, deduplicated in stable order (directory scans)."""
    return list(dict.fromkeys(STEP_DIRECTORIES.values()))


def flow_step_directory(steps: Sequence[Mapping[str, object]] | None, step_name: str) -> str:
    """The directory a flow ledger records for *step_name*.

    A step missing from the ledger uses its base ``<step>_<tool>`` name.
    """
    for step in reversed(steps or []):
        if step.get("name") == step_name:
            return recorded_step_directory(step)
    return STEP_DIRECTORIES.get(step_name, step_name)


def new_step_directory(step_name: str, tool: str, *, index: int | None = None) -> str:
    """The directory name a step gets when it is added to a flow.

    ``<step>_<tool>`` (``synthesis_yosys``), prefixed with the step's
    two-digit position in the flow when *index* is given
    (``01_synthesis_yosys``).
    """
    stem = f"{step_name}_{tool}"
    return stem if index is None else f"{index:02d}_{stem}"


def step_directory_index(name: str) -> int | None:
    """The index prefix of a step directory name (7 for ``07_placement_dreamplace``)."""
    prefix, separator, stem = name.partition("_")
    if separator and len(prefix) >= 2 and prefix.isdigit() and stem:
        return int(prefix)
    return None


def unindexed_step_directory(name: str) -> str:
    """*name* without its index prefix (``07_placement_dreamplace`` -> ``placement_dreamplace``)."""
    if step_directory_index(name) is None:
        return name
    return name.partition("_")[2]


def next_step_index(records: Iterable[Mapping[str, object]]) -> int | None:
    """The index for a step appended to a flow ledger.

    Indices are append-only: one past the highest recorded index, so existing
    directories never move. A ledger created before steps recorded indexed
    directories keeps unindexed names for appended steps (None).
    """
    indices: list[int] = []
    for record in records:
        directory = record.get("directory")
        index = step_directory_index(directory) if isinstance(directory, str) else None
        if index is None:
            return None
        indices.append(index)
    return max(indices, default=0) + 1


def is_step_directory_name(name: str) -> bool:
    """Whether *name* is a single directory name directly under the workspace."""
    return bool(name) and name not in {".", ".."} and PurePath(name).name == name


def recorded_step_directory(record: Mapping[str, object]) -> str:
    """The directory name a flow ledger step records.

    Every current ledger step must record its directory. A missing directory
    or a name that is not a single path component raises ``ValueError``.
    """
    directory = record.get("directory")
    if directory is None:
        raise ValueError(
            f"flow step {record.get('name', '<unnamed>')} has no recorded directory; "
            "create a new workspace"
        )
    if not isinstance(directory, str) or not is_step_directory_name(directory):
        raise ValueError(f"flow step directory must be a single directory name: {directory!r}")
    return directory


@runtime_checkable
class _HasFlowSteps(Protocol):
    def steps(self) -> Sequence[Mapping[str, object]]: ...


class _HasDirectory(Protocol):
    @property
    def directory(self) -> Path: ...


@dataclass(frozen=True, slots=True)
class StepDirectories:
    """Step name to directory for one workspace.

    Every ledger step uses its recorded directory. A step absent from a bounded
    derived ledger uses an inherited indexed directory when present, or its base
    ``STEP_DIRECTORIES`` name otherwise.
    """

    root: Path
    by_step: Mapping[str, str]
    #: Directory names the ledger records explicitly, in ledger order.
    recorded: tuple[str, ...]
    #: Unindexed name -> the highest-indexed unrecorded directory with it.
    inherited: Mapping[str, str]
    #: Directory names present under *root* when the lookup was built.
    present: frozenset[str]

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
            directory = recorded_step_directory(entry)
            if "directory" in entry:
                recorded.append(directory)
            by_step[name] = directory
        root = Path(root)
        present = frozenset(_directory_names(root))
        inherited: dict[str, str] = {}
        for directory in sorted(present - set(by_step.values()), key=_index_order):
            if step_directory_index(directory) is not None:
                inherited[unindexed_step_directory(directory)] = directory
        return cls(
            root,
            MappingProxyType(by_step),
            tuple(recorded),
            MappingProxyType(inherited),
            present,
        )

    @classmethod
    def of(cls, workspace: _HasDirectory) -> "StepDirectories":
        """The directories *workspace*'s ledger records (none without a ledger)."""
        flow = getattr(workspace, "flow", None)
        steps = flow.steps() if isinstance(flow, _HasFlowSteps) else ()
        return cls.from_records(Path(workspace.directory), steps)

    @classmethod
    def at(cls, root: Path | str) -> "StepDirectories":
        """The directories recorded in ``home/flow.json`` under *root*."""
        # The ledger reader lives in the workspace package, which imports this one.
        from chipcompiler.data.flow.document import load_flow_document

        document = load_flow_document(Path(root) / "home" / "flow.json")
        return cls.from_records(Path(root), document.get("steps", []))

    def name(self, step: str) -> str:
        recorded = self.by_step.get(step)
        if recorded is not None:
            return recorded
        base = STEP_DIRECTORIES.get(step, step)
        return self.inherited.get(base, base)

    def path(self, step: str) -> Path:
        return self.root / self.name(step)

    def reader_step_names(self) -> list[str]:
        """Steps whose current or inherited artifacts may be read."""
        inherited_steps = [
            step for step, directory in STEP_DIRECTORIES.items() if directory in self.inherited
        ]
        return [*self.by_step, *inherited_steps]

    def scan_names(self) -> list[str]:
        """Every directory a whole-workspace scan visits, recorded ones first."""
        return list(dict.fromkeys([*self.recorded, *self.inherited.values()]))


def _directory_names(root: Path) -> list[str]:
    try:
        return [entry.name for entry in root.iterdir() if entry.is_dir()]
    except OSError:
        return []


def _index_order(directory: str) -> tuple[int, str]:
    return (step_directory_index(directory) or 0, directory)
