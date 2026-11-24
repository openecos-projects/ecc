"""Seal tool recordings and publish results only after the parent flow has finalized."""

import json
import logging
import uuid

from chipcompiler.data.types import inserted_step_kind
from chipcompiler.tools.replay_storage import atomic_json, read_pointer, replay_root, update_pointer
from chipcompiler.utility.workspace_lock import workspace_lock

logger = logging.getLogger(__name__)


def prepare(workspace, step) -> str | None:
    """Invalidate a rerun before DB initialization, even when capture is disabled."""
    from chipcompiler.tools.replay import SUPPORTED, read_settings

    root = replay_root(step)
    if root is None:
        return None
    if (
        not read_settings(workspace)
        or (inserted_step_kind(step.name) or step.name) not in SUPPORTED
    ):
        if (root / "manifest.json").exists():
            update_pointer(root, {"status": "stale"})
        return None
    attempt = uuid.uuid4().hex
    update_pointer(root, {"status": "recording", "attempt_id": attempt})
    return attempt


def finalize(
    workspace, step, attempt: str | None, state: str, *, checklist_current: bool = False
) -> None:
    """Replay errors cannot change the EDA outcome. A late worker cannot publish."""
    if attempt is None:
        return
    root = replay_root(step)
    if root is None:
        return
    try:
        pointer = read_pointer(root)
        if pointer.get("attempt_id") != attempt:
            return
        if pointer.get("status") != "sealed":
            if state != "Success" and pointer.get("status") == "recording":
                update_pointer(
                    root,
                    {
                        "status": "unavailable",
                        "attempt_id": attempt,
                        "reason": f"Flow step ended with {state}",
                    },
                    expected=attempt,
                )
            return
        directory = root / "attempts" / attempt
        manifest = json.loads((directory / "manifest.json").read_text())
        if manifest.get("attempt_id") != attempt or manifest.get("status") != "sealed":
            raise ValueError("Replay sealed attempt identity mismatch")
        diagnostic = manifest.get("diagnostic_only") is True and state == "Incomplete"
        if state != "Success" and not diagnostic:
            update_pointer(
                root,
                {
                    "status": "unavailable",
                    "attempt_id": attempt,
                    "reason": f"Flow step ended with {state}",
                },
                expected=attempt,
            )
            return
        manifest["flow_state"] = state
        from chipcompiler.tools.replay_results import completion_checklist, current_metrics

        freshness_ns = manifest.get("capture_started_fs_ns", manifest["started_at_unix_ns"])
        manifest["result_checklist"] = completion_checklist(
            workspace, step, freshness_ns, freshly_written=checklist_current
        )
        metrics = current_metrics(step, freshness_ns)
        if metrics:
            manifest["result_metrics"] = metrics
        from chipcompiler.tools.replay_metrics import attach_comparisons

        baseline_path = directory / "baseline.json"
        baseline = json.loads(baseline_path.read_text()) if baseline_path.exists() else None
        manifest["result_metrics"] = attach_comparisons(
            manifest.get("result_metrics", []), baseline
        )
        from chipcompiler.tools.replay_integrity import fingerprint, inventory

        manifest["files"] = inventory(directory)
        manifest["results_frozen"] = True
        manifest["status"] = "diagnostic_only" if diagnostic else "complete"
        # Only the short commit is locked. Artifact preparation happens outside it.
        with workspace_lock(root):
            if read_pointer(root).get("attempt_id") != attempt:
                return
            atomic_json(directory / "manifest.json", manifest)
            update_pointer(
                root,
                {
                    "schema": manifest["schema"],
                    "status": manifest["status"],
                    "attempt_id": attempt,
                    "manifest": f"attempts/{attempt}/manifest.json",
                    "manifest_sha256": fingerprint(directory / "manifest.json")["sha256"],
                },
                expected=attempt,
            )
        from chipcompiler.tools.replay_retention import prune_completed

        prune_completed(root)
    except Exception as error:
        logger.warning("Cannot finalize Replay for %s: %s", step.name, error)
        try:
            update_pointer(
                root,
                {"status": "unavailable", "attempt_id": attempt, "reason": str(error)},
                expected=attempt,
            )
        except OSError:
            logger.warning("Cannot record Replay publication failure", exc_info=True)
