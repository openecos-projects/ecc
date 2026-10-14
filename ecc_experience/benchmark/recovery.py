"""Recover quiescent campaign attempts using durable public-command receipts."""

import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from chipcompiler.project.runtime_processes import _boot_id, _host_id
from chipcompiler.utility.workspace_lock import workspace_lock
from ecc_experience.benchmark.execute import _exit_code, _record, campaign_identity, read_run_state
from ecc_experience.benchmark.ledger import read_campaign_ledger
from ecc_experience.benchmark.manifest import load_manifest
from ecc_experience.benchmark.preparation import assert_inputs, prepare, runtime_identity
from ecc_experience.benchmark.summary import summarize
from ecc_experience.benchmark.trial import complete_trial
from ecc_experience.command_receipts import load_request, read_receipt
from ecc_experience.files import safe_child
from ecc_experience.models import ExperienceError
from ecc_experience.optimization.plan import write_plan
from ecc_experience.optimization.process import CliRunner


def recover_campaign(manifest_path: str | Path, *, trial_id: str) -> dict:
    manifest, summary = load_manifest(manifest_path)
    output = Path(summary["output_root"])
    ledger = safe_child(output, "campaign-ledger.json")
    try:
        with workspace_lock(ledger, blocking=False):
            prepared = prepare(manifest, summary)
            inputs = {item.design_id: item.fingerprint for item in prepared}
            identity = campaign_identity(summary, inputs, runtime_identity())
            path = safe_child(output, "campaign-run.json")
            state = read_run_state(path, identity, prepared)
            view = read_campaign_ledger(manifest_path)
            trial = next((item for item in state["trials"] if item["trial_id"] == trial_id), None)
            if trial is None:
                raise ExperienceError(
                    "Campaign trial does not exist", code="experience_campaign_trial_invalid"
                )
            if trial["status"] != "running":
                _record(str(view.path), trial)
                return {
                    "status": "already_terminal",
                    "exit_code": 0,
                    "result": str(path),
                    "trial": trial,
                }
            directory = safe_child(output, f"attempts/{trial_id}")
            project = safe_child(directory, "project")
            workspace = safe_child(project, "baseline")
            expected = {
                "directory": directory,
                "project": project,
                "workspace_path": workspace,
                "flow_log": safe_child(workspace, f"log/{trial['run_id']}.log"),
            }
            if trial["workspace"] != "baseline" or any(
                str(value) != trial.get(key) for key, value in expected.items()
            ):
                raise ExperienceError(
                    "Campaign trial paths changed", code="experience_source_changed"
                )
            commands = trial.get("commands")
            if not isinstance(commands, list) or not commands:
                raise _busy("No command completion evidence is available")
            completed = []
            for command in commands:
                requested = command.get("request")
                fingerprint = command.get("request_fingerprint")
                if not isinstance(requested, str) or not isinstance(fingerprint, str):
                    raise _busy("Legacy command has no durable completion receipt")
                request_path = safe_child(directory, Path(requested).name)
                if str(request_path) != requested:
                    raise ExperienceError(
                        "Command request path changed", code="experience_source_changed"
                    )
                request = load_request(request_path)
                if request.arguments != command["arguments"] or str(request.receipt) != command.get(
                    "receipt"
                ):
                    raise ExperienceError(
                        "Command request changed", code="experience_source_changed"
                    )
                receipt = read_receipt(request, fingerprint)
                if (
                    receipt is None
                    or receipt["status"] != "complete"
                    or not receipt["process_tree_quiescent"]
                ):
                    raise _busy("Command or descendants have not completed")
                worker = receipt.get("worker")
                if (
                    not isinstance(worker, dict)
                    or worker.get("host_id") != _host_id()
                    or worker.get("boot_id") != _boot_id()
                ):
                    raise _busy("Command completion belongs to a different host or boot")
                completed.append(
                    {**command, "status": "complete", "exit_code": receipt["exit_code"]}
                )
            if workspace.exists():
                with workspace_lock(workspace, blocking=False):
                    pass
            source = next(item for item in prepared if item.design_id == trial["design_id"])
            assert_inputs(manifest, summary, inputs, design_id=source.design_id)
            trial.update(
                commands=completed,
                status="blocked",
                execution_status="interrupted",
                exit_code=6,
                reason="interrupted_attempt",
            )
            if completed[-1]["arguments"][0] == "run":
                trial.update(
                    exit_code=completed[-1]["exit_code"],
                    status="fail",
                    execution_status="complete" if completed[-1]["exit_code"] == 0 else "failed",
                )
                queries = safe_child(directory, f"recovery-{uuid4().hex}")
                queries.mkdir(exist_ok=False)
                deadline = time.monotonic() + min(manifest.budget.timeout_seconds_per_trial, 120)
                complete_trial(
                    source,
                    directory,
                    summary["store"],
                    trial,
                    CliRunner(queries, deadline),
                    deadline,
                )
                assert_inputs(manifest, summary, inputs, design_id=source.design_id)
            trial["recovery"] = {
                "status": "complete",
                "recorded_at": datetime.now(UTC).isoformat(),
                "method": "quiescent_command_receipts",
            }
            write_plan(path, state)
            _record(str(view.path), trial)
            progress = summarize(manifest_path)
            state.update(
                status=progress["campaign_status"],
                summary=progress,
                exit_code=_exit_code(progress, timed_out=False),
            )
            state.pop("reason", None)
            write_plan(path, state)
            return {
                "status": "recovered",
                "exit_code": 0,
                "result": str(path),
                "trial": trial,
                "summary": progress,
            }
    except BlockingIOError as exc:
        raise _busy("Campaign or workspace is busy") from exc


def _busy(reason: str) -> ExperienceError:
    return ExperienceError(reason, code="experience_workspace_busy")
