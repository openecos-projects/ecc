#!/usr/bin/env python
"""Typed path-group layout for workspace steps.

Every EDA tool step shares the same shape of "path groups" (``input``,
``output``, ``data`` ...). Historically each group was an untyped ``dict``.
This module gives each group a real dataclass with named attributes, and the
step itself a small hierarchy: a shared :class:`WorkspaceStepBase` plus a
:class:`YosysStep` (synthesis) and an :class:`EccStep` (place-and-route, reused
by ecc/dreamplace/sizer).

``_MigrationMapping`` is a TEMPORARY bridge: while readers are still written as
``group.get("verilog")`` / ``group["def"]`` / ``dict(group)``, each group is
also a full ``MutableMapping`` keyed by the legacy dict keys. It is removed once
every reader uses attribute access.
"""

from __future__ import annotations

from collections.abc import Iterator, MutableMapping
from dataclasses import Field, dataclass, field, fields
from pathlib import Path
from typing import Any, ClassVar

# Legacy dict keys that are not valid Python identifiers map to attribute names.
_KEY_ALIASES: dict[str, str] = {"def": "def_"}
_ATTR_ALIASES: dict[str, str] = {attr: key for key, attr in _KEY_ALIASES.items()}


class _Unset:
    """Sentinel default marking a group field the caller never supplied."""

    def __repr__(self) -> str:
        return "<unset>"


_UNSET: Any = _Unset()


# TEMPORARY — deleted once every reader uses attribute access.
class _MigrationMapping(MutableMapping[str, Any]):
    """Mixin making a group dataclass behave like its former ``dict``.

    Only keys actually supplied are visible, so ``dict(group)``, iteration and
    ``len`` reproduce exactly the legacy dict (a field left at its ``_UNSET``
    default is not projected, but is still readable as ``None`` via attribute
    access). ``get``/``items``/``keys``/``values``/``update``/``pop``/
    ``__contains__`` come free from ``MutableMapping`` on top of the five
    methods below. The legacy key ``"def"`` maps to the attribute ``def_``.
    """

    # Present on every dataclass subclass; declaring it lets ``fields(self)`` type.
    __dataclass_fields__: ClassVar[dict[str, Field[Any]]]

    def __post_init__(self) -> None:
        assigned: dict[str, None] = {}
        for f in fields(self):
            value = getattr(self, f.name)
            if value is _UNSET:
                object.__setattr__(self, f.name, None)
            else:
                assigned[_ATTR_ALIASES.get(f.name, f.name)] = None
        object.__setattr__(self, "_assigned_keys", assigned)

    def __setattr__(self, name: str, value: Any) -> None:
        object.__setattr__(self, name, value)
        # A field written after construction becomes a visible legacy key, so
        # attribute writes and dict-style reads stay consistent during migration.
        if not name.startswith("_") and "_assigned_keys" in self.__dict__:
            self.__dict__["_assigned_keys"][_ATTR_ALIASES.get(name, name)] = None

    def _assigned(self) -> dict[str, None]:
        store = self.__dict__.get("_assigned_keys")
        if store is None:
            store = {}
            object.__setattr__(self, "_assigned_keys", store)
        return store

    @staticmethod
    def _attr(key: str) -> str:
        return _KEY_ALIASES.get(key, key)

    def __getitem__(self, key: str) -> Any:
        if key not in self._assigned():
            raise KeyError(key)
        return getattr(self, self._attr(key))

    def __setitem__(self, key: str, value: Any) -> None:
        object.__setattr__(self, self._attr(key), value)
        self._assigned()[key] = None

    def __delitem__(self, key: str) -> None:
        if key not in self._assigned():
            raise KeyError(key)
        del self._assigned()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(list(self._assigned()))

    def __len__(self) -> int:
        return len(self._assigned())


def _coerce_group(group_cls: type[Any], value: Any) -> Any:
    """Normalize a legacy dict into a typed group, seeding it key by key.

    Seeding through ``__setitem__`` (rather than ``group_cls(**value)``) keeps
    the ``"def"`` alias working and tolerates dynamic keys that are not declared
    fields (e.g. per-step ``data`` directories). Field VALUES are never coerced.
    """
    if isinstance(value, group_cls):
        return value
    group = group_cls()
    for key, item in value.items():
        group[key] = item
    return group


# --- path groups shared by every step -------------------------------------

@dataclass
class StepInput(_MigrationMapping):
    verilog: Path | None = _UNSET
    def_: Path | None = _UNSET
    db: Path | None = _UNSET


@dataclass
class OutputPaths(_MigrationMapping):
    # Common across tools.
    dir: Path | None = _UNSET
    def_: Path | None = _UNSET
    verilog: Path | None = _UNSET
    json: Path | None = _UNSET
    image: Path | None = _UNSET
    # Synthesis extras.
    fixed_verilog: Path | None = _UNSET
    report: Path | None = _UNSET
    # Place-and-route extras. `db` is `""` for sizer, a Path elsewhere.
    db: Path | str | None = _UNSET
    gds: Path | None = _UNSET
    view_json: Path | None = _UNSET
    view_json_edits: Path | None = _UNSET
    lef: Path | None = _UNSET
    lib: Path | None = _UNSET
    spef: list = _UNSET


@dataclass
class StepData(_MigrationMapping):
    # Common fixed directories.
    dir: Path | None = _UNSET
    tmp: Path | None = _UNSET
    # Place-and-route per-step working directories, keyed by step name (StepEnum
    # values, some containing spaces), so they cannot be plain attributes.
    steps: dict[str, Path] = _UNSET

    def workdir_for(self, name: str) -> Path | None:
        """Working directory for a step name, falling back to the base dir."""
        steps = self.steps or {}
        return steps.get(name, self.dir)

    def iter_directories(self) -> Iterator[Path]:
        """All concrete directories to create (base, tmp, and per-step)."""
        if self.dir is not None:
            yield self.dir
        if self.tmp is not None:
            yield self.tmp
        yield from (self.steps or {}).values()


@dataclass
class StepFeature(_MigrationMapping):
    dir: Path | None = _UNSET
    # Synthesis extras.
    generic_stat: Path | None = _UNSET
    stat: Path | None = _UNSET
    # Place-and-route extras.
    db: Path | None = _UNSET
    step: Path | None = _UNSET
    map: Path | None = _UNSET
    # STA-at-synthesis QoR roots; nested mapping.
    sta: dict = _UNSET


@dataclass
class StepReport(_MigrationMapping):
    dir: Path | None = _UNSET
    # Synthesis extras.
    stat: Path | None = _UNSET
    check: Path | None = _UNSET
    # Place-and-route extras. `sta` is a nested mapping of report paths.
    db: Path | None = _UNSET
    step: Path | None = _UNSET
    sta: dict = _UNSET


@dataclass
class LogPaths(_MigrationMapping):
    dir: Path | None = _UNSET
    file: Path | None = _UNSET


@dataclass
class ScriptPaths(_MigrationMapping):
    dir: Path | None = _UNSET
    main: Path | None = _UNSET
    # Sizer extras.
    sizer_env: Path | None = _UNSET
    sizer_cmd: Path | None = _UNSET


@dataclass
class AnalysisPaths(_MigrationMapping):
    dir: Path | None = _UNSET
    metrics: Path | None = _UNSET
    # QoR extras.
    qor_metrics: Path | None = _UNSET
    qor_summary: Path | None = _UNSET
    qor_hotspots: Path | None = _UNSET
    sta_timing_issues: Path | None = _UNSET
    # Place-and-route extra.
    statis_csv: Path | None = _UNSET


@dataclass
class SubflowState(_MigrationMapping):
    path: Path | None = _UNSET
    steps: list = _UNSET


@dataclass
class ChecklistState(_MigrationMapping):
    path: Path | None = _UNSET
    # Holds either the checklist rows (list) or a loaded checklist mapping.
    checklist: list | dict = _UNSET


# --- step hierarchy --------------------------------------------------------

@dataclass
class WorkspaceStepBase:
    """Shared spine for every EDA tool step.

    Each path group is a typed dataclass holding the union of the keys any tool
    uses for that group; the two step variants (:class:`YosysStep`,
    :class:`EccStep`) differ only by identity, so cross-tool readers need no
    narrowing and pyright sees no field-override variance. Assigning a plain
    ``dict`` to a group (as builders and tests do) is normalized into the group
    type via ``__setattr__``, so ``step.output = {...}`` keeps working while the
    value is really an :class:`OutputPaths`.
    """

    # Per-field group types, used to normalize dict assignments.
    _GROUP_TYPES: ClassVar[dict[str, type[Any]]] = {
        "input": StepInput,
        "output": OutputPaths,
        "data": StepData,
        "feature": StepFeature,
        "report": StepReport,
        "log": LogPaths,
        "script": ScriptPaths,
        "analysis": AnalysisPaths,
        "subflow": SubflowState,
        "checklist": ChecklistState,
    }

    name: str = ""
    directory: Path | None = None
    tool: str = ""
    version: str = ""

    input: StepInput = field(default_factory=StepInput)
    output: OutputPaths = field(default_factory=OutputPaths)
    data: StepData = field(default_factory=StepData)
    feature: StepFeature = field(default_factory=StepFeature)
    report: StepReport = field(default_factory=StepReport)
    log: LogPaths = field(default_factory=LogPaths)
    script: ScriptPaths = field(default_factory=ScriptPaths)
    analysis: AnalysisPaths = field(default_factory=AnalysisPaths)
    subflow: SubflowState = field(default_factory=SubflowState)
    checklist: ChecklistState = field(default_factory=ChecklistState)

    def __setattr__(self, name: str, value: Any) -> None:
        group_cls = self._GROUP_TYPES.get(name)
        if group_cls is not None and not isinstance(value, group_cls):
            value = _coerce_group(group_cls, value)
        object.__setattr__(self, name, value)


@dataclass
class YosysStep(WorkspaceStepBase):
    """Synthesis step."""


@dataclass
class EccStep(WorkspaceStepBase):
    """Place-and-route step, shared by ecc, dreamplace and sizer."""
