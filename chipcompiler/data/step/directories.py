"""Where each step of a workspace lives: directory names and their lookup.

Workspace creation names each step directory ``<step>_<tool>``, prefixed with
the step's position in the flow for ledgers that record it
(``07_place_dreamplace``). Checklists, signoff packages, QoR scoring and the
design reports resolve per-step artifacts through this module instead of
spelling directory names themselves.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePath
from types import MappingProxyType
from typing import Protocol, cast, runtime_checkable

from chipcompiler.data.types import SkippableStepEnum, StepEnum, ToolName

# Legacy step-directory names along the canonical rtl2gds chain
# (``Synthesis_yosys``, ``place_dreamplace``, ...): the names readers use for a
# step whose ledger does not record its directory. Timing optimization is on
# the canonical chain but owns no artifact directory any consumer reads
# through these tables.
STEP_DIRECTORIES = {
    StepEnum.SYNTHESIS.value: "Synthesis_yosys",
    SkippableStepEnum.LEC.value: "lec_kepler_formal",
    StepEnum.PRE_FLOORPLAN.value: "preFloorplan_ecc",
    StepEnum.MACRO_PLACEMENT.value: "macroPlacement_dreamplace",
    StepEnum.POST_FLOORPLAN.value: "postFloorplan_ecc",
    StepEnum.PREPLACE.value: "preplace_sizer",
    StepEnum.PLACEMENT.value: "place_dreamplace",
    SkippableStepEnum.DIFF_OPT.value: "diff_opt_dreamplace",
    StepEnum.DIFF_BUFFERING.value: "diff_buffering_dreamplace",
    StepEnum.DIFF_SIZING.value: "diff_sizing_dreamplace",
    StepEnum.CTS.value: "CTS_ecc",
    StepEnum.LEGALIZATION.value: "legalization_dreamplace",
    StepEnum.ROUTING.value: "route_ecc",
    StepEnum.FILLER.value: "filler_ecc",
    StepEnum.RCX.value: "RCX_ecc",
    StepEnum.STA.value: "sta_ecc",
    StepEnum.POWER_ANALYSIS.value: "powerAnalysis_ecc",
    StepEnum.EMIR.value: "emir_ecc",
    StepEnum.LVS.value: "lvs_ecc",
    SkippableStepEnum.POST_ROUTE_LEC.value: "postRouteLec_kepler_formal",
    StepEnum.DRC.value: "drc_ecc",
    StepEnum.ANTENNA_CHECK.value: "antennaCheck_ecc",
    StepEnum.HARDEN.value: "Harden_ecc",
    StepEnum.DEFVIEW.value: "defview_ecc",
}

# Directories of retired LEC engines. Workspaces whose ledger still records
# them keep resolving artifacts under these names.
LEGACY_STEP_DIRECTORIES = {
    SkippableStepEnum.LEC.value: "lec_yosys_lec",
    SkippableStepEnum.POST_ROUTE_LEC.value: "postRouteLec_yosys_lec",
}

# Directories of the dual cross-checking LEC engine. Like the legacy
# single-engine directories, they resolve only through tool-aware lookup —
# the name-keyed table alone cannot tell which engine a ledger recorded.
DUAL_STEP_DIRECTORIES = {
    SkippableStepEnum.LEC.value: "lec_dual",
    SkippableStepEnum.POST_ROUTE_LEC.value: "postRouteLec_dual",
}


def step_directory_for_tool(step_name: str, tool: str | None) -> str:
    """Resolve a step directory for the engine the flow recorded.

    LEC steps own one directory per engine (yosys_lec historically,
    kepler_formal today, lec_dual for cross-checking); every other step
    has a single directory.
    """
    if tool == ToolName.YOSYS_LEC and step_name in LEGACY_STEP_DIRECTORIES:
        return LEGACY_STEP_DIRECTORIES[step_name]
    if tool == ToolName.LEC_DUAL and step_name in DUAL_STEP_DIRECTORIES:
        return DUAL_STEP_DIRECTORIES[step_name]
    directory = STEP_DIRECTORIES.get(step_name)
    if directory is not None:
        return directory
    # Tools with their own storage spelling (Sizer Timing Opt) own the stem.
    return f"{step_storage_name(step_name, tool or '')}_{tool}"


def all_step_directories() -> list[str]:
    """Current and legacy step directories, deduplicated in stable order.

    Directory scans (checklist aggregation, report extraction) iterate this so
    workspaces from either LEC-engine generation are covered.
    """
    return list(
        dict.fromkeys(
            [
                *STEP_DIRECTORIES.values(),
                *LEGACY_STEP_DIRECTORIES.values(),
                *DUAL_STEP_DIRECTORIES.values(),
            ]
        )
    )


def flow_step_directory(steps: Sequence[Mapping[str, object]] | None, step_name: str) -> str:
    """The directory a flow ledger records for *step_name*.

    A step missing from the ledger keeps its legacy ``<step>_<tool>`` name.
    """
    for step in reversed(steps or []):
        if step.get("name") == step_name:
            return recorded_step_directory(step)
    return STEP_DIRECTORIES.get(step_name, step_name)


def inactive_lec_step_directories(
    steps: Sequence[Mapping[str, object]] | None,
) -> frozenset[str]:
    """LEC step directories holding stale evidence for a flow ledger.

    LEC steps own one directory per engine; after an engine switch the
    previous engine's directory is preserved evidence, never current
    state. Returns every engine's directory for lec/postRouteLec except
    the one the ledger recorded (per step); when the ledger lacks a LEC
    step, all of that step's engine directories count as inactive.
    """
    from chipcompiler.data.types import LEC_STEP_TOOLS

    lec_names = {SkippableStepEnum.LEC.value, SkippableStepEnum.POST_ROUTE_LEC.value}
    ledger_names = {str(step.get("name", "")) for step in steps or []}
    active = {flow_step_directory(steps, name) for name in lec_names & ledger_names}
    return (
        frozenset(
            step_directory_for_tool(name, tool) for name in lec_names for tool in LEC_STEP_TOOLS
        )
        - active
    )


def step_storage_name(step_name: str, tool_name: str) -> str:
    """Directory stem for ``{stem}_{tool}`` workspace step folders.

    Sizer stores Timing Opt as ``timing_optimization_sizer`` instead of
    ``Timing optimization_sizer``. Other tools keep the flow step name.
    """
    if tool_name.lower() == ToolName.SIZER:
        return "_".join(step_name.split()).lower()
    return step_name


def new_step_directory(step_name: str, tool: str, *, index: int | None = None) -> str:
    """The directory name a step gets when it is added to a flow.

    ``<step>_<tool>`` (``Synthesis_yosys``; the dual LEC step uses
    ``<step>_dual``), prefixed with the step's two-digit position in the flow
    when *index* is given (``01_Synthesis_yosys``).
    """
    suffix = "dual" if tool == ToolName.LEC_DUAL else tool
    stem = f"{step_storage_name(step_name, tool)}_{suffix}"
    return stem if index is None else f"{index:02d}_{stem}"


def step_directory_index(name: str) -> int | None:
    """The index prefix of a step directory name (7 for ``07_place_dreamplace``)."""
    prefix, separator, stem = name.partition("_")
    if separator and len(prefix) >= 2 and prefix.isdigit() and stem:
        return int(prefix)
    return None


def unindexed_step_directory(name: str) -> str:
    """*name* without its index prefix (``07_place_dreamplace`` -> ``place_dreamplace``)."""
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

    Ledgers written before steps recorded their directory fall back to the
    ``<step>_<tool>`` name those workspaces were created with. A recorded name
    that is not a single directory name raises ``ValueError``.
    """
    directory = record.get("directory")
    if directory is None:
        return new_step_directory(str(record.get("name", "")), str(record.get("tool", "")))
    if not isinstance(directory, str) or not is_step_directory_name(directory):
        raise ValueError(f"flow step directory must be a single directory name: {directory!r}")
    return directory


def engine_step_directory(dual_directory: Path, engine: str) -> Path:
    """The directory of one engine of a dual LEC step.

    Engines run in siblings of the dual step's directory that keep its prefix:
    ``03_lec_dual`` runs kepler-formal in ``03_lec_kepler_formal``.
    """
    name = dual_directory.name
    if not name.endswith("_dual"):
        raise ValueError(f"not a dual LEC step directory: {dual_directory}")
    return dual_directory.with_name(f"{name.removesuffix('dual')}{engine}")


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
        # The ledger reader lives in the workspace package, which imports this one.
        from chipcompiler.data.workspace.flow_types import load_flow_document

        document = load_flow_document(Path(root) / "home" / "flow.json")
        return cls.from_records(Path(root), document.get("steps", []))

    def name(self, step: str) -> str:
        return self.by_step.get(step) or STEP_DIRECTORIES.get(step, step)

    def path(self, step: str) -> Path:
        return self.root / self.name(step)

    def scan_names(self) -> list[str]:
        """Every directory a whole-workspace scan visits, recorded ones first."""
        return list(dict.fromkeys([*self.recorded, *all_step_directories()]))
