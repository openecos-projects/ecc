"""Recover completed execution observations from the project outbox."""

import re
from collections import defaultdict
from pathlib import Path

from ecc_experience.adapters.chipcompiler_reader import read_workspace_observation
from ecc_experience.collection.collect import collect_committed_case
from ecc_experience.collection.context import recorded_context
from ecc_experience.files import read_json, safe_child
from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.models import ExperienceError
from ecc_experience.recording import load_config

_ATTEMPT_ID = re.compile(r"attempt-[0-9a-f]{32}\Z")


def drain(project: str | Path, *, limit: int = 32) -> list[dict]:
    config = load_config(project)
    if config is None:
        raise ExperienceError(
            "Experience recording is not configured", code="experience_not_configured"
        )
    root = Path(project).expanduser().resolve()
    outbox = safe_child(root, ".ecc/experience/outbox")
    if not outbox.exists():
        return []
    events = defaultdict(list)
    for path in sorted(outbox.glob("*.json")):
        try:
            event = read_json(path, 256 * 1024)
        except ExperienceError:
            continue
        attempt_id = event.get("attempt_id") if isinstance(event, dict) else None
        if isinstance(attempt_id, str) and _ATTEMPT_ID.fullmatch(attempt_id):
            events[attempt_id].append((path, event))

    results = []
    for attempt_id, entries in sorted(events.items())[:limit]:
        started = next(
            (item for _path, item in entries if item.get("event") == "attempt_started"), None
        )
        finished = next(
            (item for _path, item in entries if item.get("event") == "attempt_finished"), None
        )
        committed = [item for _path, item in entries if item.get("event") == "step_committed"]
        if started is None or finished is None or not committed:
            results.append({"attempt_id": attempt_id, "status": "pending", "reason": "incomplete"})
            continue
        workspace = started.get("workspace")
        snapshot_digest = committed[-1].get("snapshot_digest")
        if not isinstance(workspace, str) or not isinstance(snapshot_digest, str):
            results.append(
                {"attempt_id": attempt_id, "status": "failed", "reason": "invalid_event"}
            )
            continue
        try:
            execution_context = recorded_context(finished, attempt_id, snapshot_digest)
            result = collect_committed_case(
                workspace,
                ExperienceStore(config.store),
                read_workspace_observation,
                attempt_id=attempt_id,
                expected_snapshot_digest=snapshot_digest,
                execution_context=execution_context,
            )
        except (ExperienceError, OSError) as exc:
            results.append({"attempt_id": attempt_id, "status": "failed", "reason": str(exc)})
            continue
        processed = safe_child(root, f".ecc/experience/processed/{attempt_id}")
        processed.mkdir(parents=True, exist_ok=True)
        for path, _event in entries:
            path.rename(safe_child(processed, path.name))
        results.append(
            {
                "attempt_id": attempt_id,
                "status": "created" if result.status == "created" else "already_present",
                "case_id": result.case.case_id,
            }
        )
    return results
