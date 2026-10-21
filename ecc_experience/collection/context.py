"""Capture optional attempt-bound runtime and selected PDK identities."""

from dataclasses import dataclass
from pathlib import Path

from ecc_experience.adapters.process_context import process_context
from ecc_experience.benchmark.preparation import runtime_identity
from ecc_experience.files import digest, read_json, safe_child
from ecc_experience.models import ExperienceError


@dataclass
class AttemptContext:
    attempt_id: str
    workspace: Path
    runtime_before: dict
    process_before: dict
    process_unchanged: bool = True
    snapshot_digest: str | None = None

    @classmethod
    def capture(cls, attempt_id: str, workspace: Path) -> "AttemptContext":
        return cls(attempt_id, workspace, _runtime(), _workspace_process(workspace))

    def committed(self, snapshot: dict) -> dict:
        observed = _process(snapshot)
        self.process_unchanged = self.process_unchanged and observed == self.process_before
        self.snapshot_digest = digest(snapshot)
        return observed

    def finish(self) -> dict:
        runtime_after = _runtime()
        process_after = _workspace_process(self.workspace)
        runtime_status = _comparison(self.runtime_before, runtime_after)
        process_status = _comparison(self.process_before, process_after)
        if process_status == "available" and not self.process_unchanged:
            process_status = "changed"
        return {
            "schema": "ecc-experience-execution-context/1",
            "attempt_id": self.attempt_id,
            "snapshot_digest": self.snapshot_digest,
            "runtime": self.runtime_before["identity"] if runtime_status == "available" else None,
            "process": self.process_before
            if process_status == "available"
            else {
                "status": "unknown",
                "fingerprint": None,
                "reason": f"Selected PDK identity is {process_status}",
            },
            "scope": "recorded_runtime_before_after_and_selected_pdk_at_step_commits",
            "checks": {"runtime": runtime_status, "process": process_status},
            "observations": {
                "runtime_before": self.runtime_before,
                "runtime_after": runtime_after,
                "process_before": self.process_before,
                "process_after": process_after,
                "process_unchanged_at_commits": self.process_unchanged,
            },
        }


def _comparison(before: dict, after: dict) -> str:
    if before.get("status") != "available" or after.get("status") != "available":
        return "unknown"
    return "available" if before == after else "changed"


def recorded_context(event: dict, attempt_id: str, snapshot_digest: str) -> dict | None:
    context = event.get("execution_context")
    if context is None:
        return None
    if (
        not isinstance(context, dict)
        or context.get("schema") != "ecc-experience-execution-context/1"
        or context.get("attempt_id") != attempt_id
        or context.get("snapshot_digest") != snapshot_digest
        or not isinstance(context.get("process"), dict)
        or (context.get("runtime") is not None and not isinstance(context["runtime"], dict))
    ):
        raise ExperienceError("Recorded execution context does not match the committed attempt")
    process = context["process"]
    if process.get("status") == "available" and (
        not isinstance(process.get("fingerprint"), str) or not process["fingerprint"]
    ):
        raise ExperienceError("Recorded process context has no fingerprint")
    return context


def _runtime() -> dict:
    try:
        return {"status": "available", "identity": runtime_identity()}
    except (Exception, SystemExit) as exc:
        return {"status": "unknown", "reason": f"Runtime capture failed: {type(exc).__name__}"}


def _process(snapshot: dict) -> dict:
    try:
        return process_context(snapshot)
    except (Exception, SystemExit) as exc:
        return {
            "status": "unknown",
            "fingerprint": None,
            "reason": f"PDK capture failed: {type(exc).__name__}",
        }


def _workspace_process(workspace: Path) -> dict:
    from chipcompiler.engine.snapshot import SNAPSHOT_FILENAME

    try:
        snapshot = read_json(safe_child(workspace, f"home/{SNAPSHOT_FILENAME}"))
    except (OSError, ValueError) as exc:
        return {
            "status": "unknown",
            "fingerprint": None,
            "reason": f"Committed snapshot unavailable: {type(exc).__name__}",
        }
    return _process(snapshot)
