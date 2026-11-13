"""Each step's run results, kept in its own step directory.

Whenever the flow saves its ledger it records how each step's runs went (state,
runtime, peak memory, checklist status, resource observation and the markers of
a run in progress) in ``<step dir>/state.json``, then generates
``home/flow.json`` from the same records with a digest of those results. On
load, a ledger that still matches its digest takes each step's results from the
step directories, so an interrupted save resolves to what the step directories
hold. A ledger whose results were edited by another writer (ECOS, recovery
tools) no longer matches its digest and keeps its own results.
"""

import hashlib
import json
from collections.abc import Iterable, Mapping, MutableMapping, Sequence
from contextlib import suppress
from pathlib import Path
from typing import Final, cast

from chipcompiler.data.step.directories import recorded_step_directory
from chipcompiler.utility.file import write_text_atomic

STATE_FILE: Final = "state.json"
SCHEMA_VERSION: Final = 1
#: Ledger record fields that describe a step's runs rather than the flow plan.
RESULT_FIELDS: Final = (
    "state",
    "runtime",
    "peak memory (mb)",
    "checklist",
    "checklist_status",
    "resource_observation",
)
#: ``info`` entries that mark a run in progress.
RUN_MARKERS: Final = ("execution", "runtime_operation")


def step_results(record: Mapping[str, object]) -> dict[str, object]:
    """The results one ledger record holds about its step's runs."""
    results = {field: record[field] for field in RESULT_FIELDS if field in record}
    info = record.get("info")
    if isinstance(info, Mapping):
        markers = cast("Mapping[str, object]", info)
        present = {marker: markers[marker] for marker in RUN_MARKERS if marker in markers}
        if present:
            results["run_markers"] = present
    return results


def results_digest(records: Iterable[object]) -> str:
    """A digest of every record's step results, in ledger order."""
    payload = [
        [entry.get("name"), entry.get("tool"), _directory(entry), step_results(entry)]
        for entry in _records(records)
    ]
    text = json.dumps(payload, sort_keys=True, default=str)
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def persist_step_results(
    workspace_directory: Path, records: Sequence[Mapping[str, object]]
) -> list[tuple[Path, str | None]]:
    """Write ``state.json`` into every existing step directory whose results changed.

    Returns each written file with its previous content (None when it did not
    exist) so the caller can roll back. A failed write rolls back the files
    already written and raises ``OSError``.
    """
    written: list[tuple[Path, str | None]] = []
    try:
        for record in records:
            directory = _directory(record)
            if directory is None or not (workspace_directory / directory).is_dir():
                continue
            path = workspace_directory / directory / STATE_FILE
            text = _state_text(record)
            previous = _read_text(path)
            if previous == text:
                continue
            write_text_atomic(path, text)
            written.append((path, previous))
    except OSError:
        restore_step_results(written)
        raise
    return written


def restore_step_results(written: Sequence[tuple[Path, str | None]]) -> None:
    """Put back the files :func:`persist_step_results` replaced."""
    for path, previous in reversed(written):
        with suppress(OSError):
            if previous is None:
                path.unlink(missing_ok=True)
            else:
                write_text_atomic(path, previous)


def apply_step_results(
    document: MutableMapping[str, object], workspace_directory: Path, *, digest_field: str
) -> None:
    """Take each step's results from its step directory, for a ledger generated here.

    A document whose results no longer match the digest it was generated with
    was written by someone else and is left unchanged.
    """
    steps = document.get("steps")
    if not isinstance(steps, list) or document.get(digest_field) != results_digest(
        cast("list[object]", steps)
    ):
        return
    for record in _records(cast("list[object]", steps)):
        directory = _directory(record)
        if directory is None:
            continue
        stored = _load(workspace_directory / directory / STATE_FILE)
        if (
            stored is None
            or stored.get("step") != record.get("name")
            or stored.get("tool") != record.get("tool")
        ):
            continue
        _apply(cast("dict[str, object]", record), stored)


def _apply(record: dict[str, object], stored: Mapping[str, object]) -> None:
    for field in RESULT_FIELDS:
        if field in stored:
            record[field] = stored[field]
        else:
            record.pop(field, None)
    markers = stored.get("run_markers")
    present: Mapping[str, object] = (
        cast("Mapping[str, object]", markers) if isinstance(markers, Mapping) else {}
    )
    info = record.get("info")
    if not isinstance(info, dict):
        if not present:
            return
        info = {}
        record["info"] = info
    entries = cast("dict[str, object]", info)
    for marker in RUN_MARKERS:
        if marker in present:
            entries[marker] = present[marker]
        else:
            entries.pop(marker, None)


def _records(records: Iterable[object]) -> list[Mapping[str, object]]:
    return [cast("Mapping[str, object]", record) for record in records if isinstance(record, dict)]


def _directory(record: Mapping[str, object]) -> str | None:
    try:
        return recorded_step_directory(record)
    except ValueError:
        return None


def _state_text(record: Mapping[str, object]) -> str:
    document = {
        "schema_version": SCHEMA_VERSION,
        "step": record.get("name"),
        "tool": record.get("tool"),
        **step_results(record),
    }
    return json.dumps(document, indent=2, default=str) + "\n"


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def _load(path: Path) -> Mapping[str, object] | None:
    try:
        parsed: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    stored = cast("dict[str, object]", parsed)
    return stored if stored.get("schema_version") == SCHEMA_VERSION else None
