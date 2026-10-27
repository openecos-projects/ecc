"""Serial, budgeted optimization through existing ECC workspace and flow commands."""

import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from chipcompiler.cli.core.exit_codes import EXIT_GATE_FAILED, EXIT_GATE_UNKNOWN, EXIT_TIMEOUT
from chipcompiler.project.manifest import ManifestError, load_manifest
from ecc_experience.models import ExperienceError, WorkspaceObservation
from ecc_experience.optimization.evidence import (
    check_trial_configuration,
    inspect_workspace,
    validate_trial,
)
from ecc_experience.optimization.plan import write_plan
from ecc_experience.optimization.policy import (
    OptimizationLimits,
    check_baseline,
    eligible_candidates,
    invalid_plan,
    read_execution_plan,
)
from ecc_experience.optimization.process import CliRunner, cancellation_signals


def _trial(
    project: Path,
    baseline: WorkspaceObservation,
    candidate: dict,
    limits: OptimizationLimits,
    store: str | Path,
    runner: CliRunner,
    workspace_id: str,
    record: dict,
    save: Callable[[], None],
    source_id: str,
) -> dict:
    started = time.monotonic()
    deadline = min(runner.deadline, started + limits.trial_timeout_seconds)
    run_id = str(uuid.uuid4())
    workspace = project / workspace_id
    record.update(
        {
            "workspace": str(workspace),
            "workspace_id": workspace_id,
            "run_id": run_id,
            "source_case_id": candidate["case_id"],
            "parameters": candidate["parameters"],
            "status": "running",
            "exit_code": 1,
        }
    )
    commands = [
        ["workspace", "derive", str(source_id), workspace_id, "--no-wait"],
    ]
    if candidate["sets"]:
        commands.append(
            [
                "param",
                "apply",
                "--workspace",
                workspace_id,
                "--no-wait",
                *[argument for pair in candidate["sets"] for argument in ("--set", pair)],
            ]
        )
    commands.append(["run", "--workspace", workspace_id, "--run-id", run_id, "--no-wait"])
    record["commands"] = []
    save()
    for command in commands:
        if command[0] == "run":
            check_trial_configuration(
                workspace,
                baseline,
                candidate["parameters"],
                require_effects=False,
            )
        command_record = {"arguments": command, "status": "running"}
        record["commands"].append(command_record)
        save()
        invocation = runner.invoke(
            [*command, "--project", str(project), "--plain"], deadline=deadline
        )
        command_record.update(
            {
                "status": "complete",
                "exit_code": invocation.exit_code,
                "stdout": str(invocation.stdout),
                "stderr": str(invocation.stderr),
            }
        )
        record["exit_code"] = invocation.exit_code
        save()
        if invocation.exit_code != 0:
            record["status"] = "failed"
            break
    try:
        if (
            commands[-1] == record["commands"][-1]["arguments"]
            and record["exit_code"] != EXIT_TIMEOUT
        ):
            evidence = inspect_workspace(
                project, workspace, runner, deadline, exit_code=record["exit_code"]
            )
            record.update(evidence)
            if EXIT_TIMEOUT in (
                evidence["workspace_status_exit_code"],
                evidence["signoff_exit_code"],
            ):
                record["exit_code"] = EXIT_TIMEOUT
            record.update(
                validate_trial(workspace, store, baseline, candidate["parameters"], run_id)
            )
            if record["status"] == "passed" and record["verification"]["status"] != "pass":
                record["status"] = (
                    "unknown" if record["verification"]["status"] == "unknown" else "failed"
                )
    except (ExperienceError, OSError) as exc:
        record["status"] = "failed"
        record["reason"] = str(exc)
        if isinstance(exc, ExperienceError) and exc.code == "experience_source_changed":
            raise
    if record["exit_code"] == EXIT_TIMEOUT or time.monotonic() >= deadline:
        record["exit_code"] = EXIT_TIMEOUT
        record["status"] = "timeout"
    record["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return record


def optimize(
    project: str | Path,
    plan_path: str | Path,
    store: str | Path,
    output: str | Path,
) -> dict:
    with cancellation_signals():
        return _optimize(project, plan_path, store, output)


def _optimize(
    project: str | Path,
    plan_path: str | Path,
    store: str | Path,
    output: str | Path,
) -> dict:
    if not Path("/proc/self/task").is_dir():
        raise invalid_plan(
            "Controlled optimization requires Linux process-tree cancellation support"
        )
    root = Path(project).expanduser().resolve()
    plan, limits = read_execution_plan(plan_path, store)
    baseline = check_baseline(plan)
    try:
        manifest = load_manifest(str(root))
    except ManifestError as exc:
        raise invalid_plan(str(exc)) from exc
    source_workspace = next(
        (
            item
            for item in manifest.workspaces
            if Path(item.workspace_path).resolve() == Path(baseline.source.workspace_root)
        ),
        None,
    )
    if source_workspace is None:
        raise invalid_plan("Baseline must be a declared workspace of the selected project")
    store_path = Path(store).expanduser().resolve()
    source_path = Path(baseline.source.workspace_root)
    if store_path.is_relative_to(source_path) or source_path.is_relative_to(store_path):
        raise invalid_plan("Experience store and baseline workspace must not overlap")
    candidates, skipped = eligible_candidates(plan, limits, baseline, store)
    if not candidates:
        return {
            "status": "insufficient_evidence",
            "exit_code": EXIT_GATE_UNKNOWN,
            "reason": "No eligible observed configurations",
            "skipped": skipped,
        }
    destination = Path(output).expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        raise invalid_plan("Optimization output must be a new directory")
    if destination.resolve().is_relative_to(Path(baseline.source.workspace_root)):
        raise invalid_plan("Optimization output must not be inside the baseline workspace")
    destination.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    runner = CliRunner(destination, started + limits.max_seconds, durable_receipts=True)
    result = {
        "schema": "ecc-experience-optimization-result/1",
        "optimization_id": f"opt_{uuid.uuid4().hex[:12]}",
        "created_at": datetime.now(UTC).isoformat(),
        "plan_fingerprint": plan["plan_fingerprint"],
        "release_id": plan.get("release_id"),
        "baseline_workspace": baseline.source.workspace_root,
        "limits": limits.model_dump(),
        "validation_scope": "full_flow",
        "status": "running",
        "stop_reason": None,
        "trials": [],
        "skipped": skipped,
        "winner": None,
        "fresh_validation": None,
        "exit_code": EXIT_GATE_UNKNOWN,
    }
    result_path = destination / "result.json"

    def save() -> None:
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        write_plan(result_path, result)

    save()
    try:
        baseline_evidence = inspect_workspace(
            root, Path(baseline.source.workspace_root), runner, runner.deadline
        )
        result["baseline_evidence"] = baseline_evidence
        if EXIT_TIMEOUT in (
            baseline_evidence["workspace_status_exit_code"],
            baseline_evidence["signoff_exit_code"],
        ):
            result.update(
                status="timeout", stop_reason="baseline_inspection_timeout", exit_code=EXIT_TIMEOUT
            )
            return result
        best = None
        failures = 0
        best_score = baseline_evidence["qor_score"]
        if best_score is None:
            best_score = float("-inf")
        for index, candidate in enumerate(candidates[: limits.max_trials - 1], 1):
            check_baseline(plan)
            record = {}
            result["trials"].append(record)
            record = _trial(
                root,
                baseline,
                candidate,
                limits,
                store,
                runner,
                f"{result['optimization_id']}_{index:03d}",
                record,
                save,
                source_workspace.workspace_id,
            )
            check_baseline(plan)
            if record["status"] == "passed":
                score = record["qor_score"]
                if best is None or score > best[1]["qor_score"]:
                    best = (candidate, record)
                    result["winner"] = record
                if score > best_score:
                    failures = 0
                    best_score = score
                else:
                    failures += 1
            else:
                failures += 1
            save()
            if record["status"] == "timeout":
                result.update(stop_reason="time_budget", exit_code=EXIT_TIMEOUT)
                break
            if limits.target_score is not None and best_score >= limits.target_score:
                result["stop_reason"] = "target_score"
                break
            if failures >= limits.patience:
                result["stop_reason"] = "patience"
                break
        if result["stop_reason"] is None:
            result["stop_reason"] = (
                "trial_budget"
                if len(candidates) > limits.max_trials - 1
                else "candidates_exhausted"
            )
        if best is not None and result["exit_code"] != EXIT_TIMEOUT:
            check_baseline(plan)
            fresh = {}
            result["fresh_validation"] = fresh
            fresh = _trial(
                root,
                baseline,
                best[0],
                limits,
                store,
                runner,
                f"{result['optimization_id']}_fresh",
                fresh,
                save,
                source_workspace.workspace_id,
            )
            check_baseline(plan)
            result["fresh_validation"] = fresh
            if fresh["status"] == "passed":
                baseline_score = baseline_evidence["qor_score"]
                delta = fresh["qor_score"] - baseline_score if baseline_score is not None else None
                result.update(
                    status="complete",
                    exit_code=0,
                    score_delta=delta,
                    improved=delta > 0 if delta is not None else None,
                    comparison_status="available" if delta is not None else "insufficient_evidence",
                )
            else:
                result.update(
                    status="fresh_validation_failed",
                    exit_code=EXIT_TIMEOUT if fresh["status"] == "timeout" else EXIT_GATE_FAILED,
                )
        else:
            result["status"] = (
                "timeout" if result["exit_code"] == EXIT_TIMEOUT else "no_valid_candidate"
            )
            if result["exit_code"] != EXIT_TIMEOUT:
                result["exit_code"] = EXIT_GATE_FAILED
    except ExperienceError as exc:
        result.update(
            status="stopped",
            stop_reason=exc.code,
            reason=str(exc),
            exit_code=21 if exc.code == "experience_source_changed" else 1,
        )
    except KeyboardInterrupt:
        result.update(status="cancelled", stop_reason="user_interrupt", exit_code=130)
        for record in [*result["trials"], result["fresh_validation"]]:
            if record is not None and record.get("status") == "running":
                record.update(status="cancelled", exit_code=130)
    except OSError as exc:
        result.update(status="stopped", stop_reason="io_error", reason=str(exc), exit_code=1)
    finally:
        for record in [*result["trials"], result["fresh_validation"]]:
            if record is not None and record.get("status") == "running":
                record.update(status="stopped", exit_code=result["exit_code"])
            if record is not None:
                for command in record.get("commands", []):
                    if command.get("status") == "running":
                        command.update(status=result["status"], exit_code=result["exit_code"])
        save()
    return result
