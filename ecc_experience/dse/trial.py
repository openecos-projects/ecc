import time
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from threading import RLock
from uuid import uuid4

from chipcompiler.project.manifest import load_manifest
from ecc_experience.adapters.chipcompiler_reader import read_workspace_observation
from ecc_experience.adapters.process_context import process_context
from ecc_experience.benchmark.evidence import collect_trial
from ecc_experience.benchmark.preparation import runtime_identity
from ecc_experience.dse.config_surface import (
    parameter_evidence_from_config_receipt,
    verify_applied_config,
)
from ecc_experience.dse.evidence import stage_acceptance
from ecc_experience.dse.plan import (
    DseLimits,
    invalid,
    project_configuration,
    validate_parameter_boundary,
)
from ecc_experience.models import ExperienceError, WorkspaceObservation
from ecc_experience.optimization.evidence import check_trial_configuration, inspect_workspace
from ecc_experience.optimization.policy import reviewed_parameter_effects
from ecc_experience.optimization.process import CliRunner

COLLECTION_RETRY_DELAYS = (0.25, 0.5, 1.0)


def check_source(plan: dict) -> WorkspaceObservation:
    manifest = load_manifest(plan["project"])
    entry = manifest.find_workspace(plan["source_workspace_id"])
    if entry is None or Path(entry.workspace_path).resolve() != Path(plan["baseline_workspace"]):
        raise ExperienceError("DSE source registration changed", code="experience_source_changed")
    observation = read_workspace_observation(plan["baseline_workspace"])
    names = [step["name"] for step in observation.facts["flow"]["steps"]]
    if not names or plan["first_step"] != names[0] or plan["through_step"] not in names:
        raise invalid("DSE plan has an invalid execution boundary")
    boundary = plan.get("parameter_boundary", plan["through_step"])
    for candidate in plan["candidates"]:
        validate_parameter_boundary(
            list(candidate["parameters"]), names[: names.index(boundary) + 1]
        )
    if (
        observation.source.snapshot_digest != plan["snapshot_digest"]
        or process_context(observation.facts) != plan["process"]
        or runtime_identity() != plan["runtime"]
        or project_configuration(Path(plan["project"])) != plan["project_configuration"]
    ):
        raise ExperienceError(
            "DSE frozen source or environment changed", code="experience_source_changed"
        )
    from ecc_experience.knowledge.recommend import _input_fingerprint

    if (
        _input_fingerprint(observation.facts, observation.inputs)
        != plan["input_content_fingerprint"]
    ):
        raise ExperienceError("DSE declared inputs changed", code="experience_source_changed")
    return observation


def requested_observation(baseline: WorkspaceObservation, parameters: dict) -> WorkspaceObservation:
    """Build the effective configuration authorized for a DSE candidate."""
    facts = deepcopy(baseline.facts)
    facts["workspaceSpec"]["parameters"].update(reviewed_parameter_effects(parameters))
    return replace(baseline, facts=facts)


def _collect_trial_with_stability_retry(*args, **kwargs) -> dict:
    """Re-read a settled workspace across a brief flow/snapshot write-back race.

    Collection runs immediately after a detached ``ecc run``. A completed
    workspace can briefly expose a flow projection newer than its committed
    snapshot while the final write-back is still draining. The retry only
    absorbs that bounded source-change window; genuine input or snapshot
    changes remain failures after the retries are exhausted.
    """
    for attempt, delay in enumerate((0.0, *COLLECTION_RETRY_DELAYS)):
        if delay:
            time.sleep(delay)
        try:
            return collect_trial(*args, **kwargs)
        except ExperienceError as exc:
            if exc.code != "experience_source_changed" or attempt == len(COLLECTION_RETRY_DELAYS):
                raise
    raise AssertionError("unreachable collection retry state")


def execute_trial(
    plan: dict,
    candidate: dict,
    limits: DseLimits,
    runner: CliRunner,
    record: dict,
    save,
    *,
    mode: str,
    resume: bool = False,
    store_lock=None,
    source_lock=None,
    derive_lock=None,
    concurrency: dict | None = None,
    state_lock=None,
) -> None:
    lock = state_lock or RLock()

    def update(values: dict | None = None, **keywords) -> None:
        merged = {**(values or {}), **keywords}
        with lock:
            record.update(merged)

    started = time.monotonic()
    elapsed = record.get("elapsed_seconds", 0.0) if resume else 0.0
    if resume and record.get("budget_started_at") is not None:
        elapsed = max(elapsed, time.time() - record["budget_started_at"])
    deadline = min(runner.deadline, started + max(0, limits.trial_timeout_seconds - elapsed))
    workspace_id = record["workspace_id"] if resume else f"dse_{uuid4().hex[:16]}"
    root = Path(plan["project"])
    workspace = root / workspace_id
    run_id = record["run_id"] if resume else str(uuid4())
    if resume and (
        record.get("workspace") != str(workspace)
        or record.get("parameters") != candidate["parameters"]
        or record.get("candidate_id") != candidate["candidate_id"]
        or record.get("mode") != mode
        or not workspace_id.startswith("dse_")
        or Path(workspace_id).name != workspace_id
    ):
        raise invalid("DSE recovery record does not match its frozen candidate")
    if not resume:
        update(
            trial_id=workspace_id,
            candidate_id=candidate["candidate_id"],
            mode=mode,
            workspace=str(workspace),
            workspace_id=workspace_id,
            run_id=run_id,
            parameters=candidate["parameters"],
            status="running",
            exit_code=1,
            commands=[],
            collection_status="not_attempted",
            budget_started_at=time.time(),
        )
    save()
    commands = [["workspace", "derive", plan["source_workspace_id"], workspace_id]]
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
    run = ["run", "--workspace", workspace_id, "--run-id", run_id, "--no-wait"]
    if mode == "screen":
        run.extend(["--from", plan["first_step"], "--to", plan["through_step"]])
    commands.append(run)
    runner.set_environment(_concurrency_environment(concurrency))
    try:
        if source_lock is None:
            baseline = check_source(plan)
        else:
            with source_lock:
                baseline = check_source(plan)
        for index, arguments in enumerate(commands):
            if arguments[0] == "run":
                check_trial_configuration(
                    workspace,
                    baseline,
                    candidate["parameters"],
                    require_effects=False,
                )
            expected = [*arguments, "--project", str(root), "--plain"]
            if index < len(record["commands"]):
                command = record["commands"][index]
                if command["arguments"] != arguments:
                    raise invalid("DSE command sequence changed")
                if command["status"] != "complete":
                    from ecc_experience.dse.receipts import recover_command

                    recover_command(command, expected, runner.output)
                update(exit_code=command["exit_code"])
                save()
                if command["exit_code"] != 0:
                    break
                _check_config_receipt(record, candidate, workspace, arguments, runner, update)
                continue
            command = {"arguments": arguments, "status": "running"}
            with lock:
                record["commands"].append(command)
            save()
            is_derive = arguments[:2] == ["workspace", "derive"]
            with (
                derive_lock if is_derive and derive_lock is not None else nullcontext(),
                source_lock if is_derive and source_lock is not None else nullcontext(),
            ):
                if runner.durable_receipts:

                    def prepared(metadata, target=command):
                        target.update(metadata)
                        save()

                    result = runner.invoke(expected, deadline=deadline, on_prepared=prepared)
                else:
                    result = runner.invoke(expected, deadline=deadline)
            with lock:
                command.update(
                    status="complete",
                    exit_code=result.exit_code,
                    stdout=str(result.stdout),
                    stderr=str(result.stderr),
                )
                record["exit_code"] = result.exit_code
            save()
            if result.exit_code != 0:
                break
            _check_config_receipt(record, candidate, workspace, arguments, runner, update)
        if record["exit_code"] == 124:
            update(status="timeout")
            return
        marker = f"ECC run {run_id} started\n".encode()
        log = workspace / "log" / f"{run_id}.log"
        executed = False
        if log.is_file():
            with log.open("rb") as stream:
                executed = stream.read(len(marker)) == marker
        if not executed:
            update(status="failed", reason="run_not_started")
            return
        if source_lock is None:
            check_source(plan)
        else:
            with source_lock:
                check_source(plan)
        requested = requested_observation(baseline, candidate["parameters"])
        context = {
            "schema": "ecc-experience-execution-context/1",
            "attempt_id": run_id,
            "runtime": plan["runtime"],
            "process": plan["process"],
            "scope": "dse_runtime_and_selected_pdk_content_checked_before_and_after",
        }
        update(collection_status="pending")
        parameter_evidence = parameter_evidence_from_config_receipt(
            record.get("config_receipt"),
            candidate["parameters"],
            candidate_id=candidate["candidate_id"],
            stage=plan["through_step"],
        )
        if store_lock is None:
            collected = _collect_trial_with_stability_retry(
                workspace,
                plan["store"],
                requested,
                run_id,
                execution_context=context,
                parameter_evidence=parameter_evidence,
            )
        else:
            with store_lock:
                collected = _collect_trial_with_stability_retry(
                    workspace,
                    plan["store"],
                    requested,
                    run_id,
                    execution_context=context,
                    parameter_evidence=parameter_evidence,
                )
        update(**collected, collection_status="collected")
        if mode == "screen":
            update(
                stage_acceptance(
                    record["case_id"], plan["store"], plan, exit_code=record["exit_code"]
                )
            )
        else:
            evidence = inspect_workspace(
                root, workspace, runner, deadline, exit_code=record["exit_code"]
            )
            update(**evidence, validation_scope="full_flow")
            if record["status"] == "passed" and record["verification"]["status"] != "pass":
                update(status="unknown", reason="case_verification_not_passed")
            if 124 in (evidence["workspace_status_exit_code"], evidence["signoff_exit_code"]):
                update(status="timeout", exit_code=124)
    except KeyboardInterrupt:
        update(status="cancelled", exit_code=130, reason="user_interrupt")
        raise
    except (ExperienceError, OSError) as exc:
        if isinstance(exc, ExperienceError) and exc.code == "experience_workspace_busy":
            update(status="running", reason=str(exc))
            raise
        update(status="failed", reason=str(exc), exit_code=record["exit_code"] or 1)
        if record["collection_status"] == "pending":
            update(collection_status="failed")
        if isinstance(exc, ExperienceError) and exc.code == "experience_source_changed":
            update(exit_code=21)
            raise
    finally:
        runner.clear_environment()
        with lock:
            record["elapsed_seconds"] = round(elapsed + time.monotonic() - started, 3)
            for command in record["commands"]:
                if command["status"] == "running":
                    command.update(status="interrupted", exit_code=record["exit_code"])
        save()


def _concurrency_environment(value: dict | None) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    environment = {}
    for key, variable in (
        ("current_flows", "ECC_EXPERIENCE_CURRENT_FLOWS"),
        ("max_concurrent", "ECC_EXPERIENCE_MAX_CONCURRENT"),
        ("trial_threads", "ECC_EXPERIENCE_TRIAL_THREADS"),
    ):
        item = value.get(key)
        if item is not None:
            environment[variable] = str(item)
    return environment or None


def _check_config_receipt(record, candidate, workspace, arguments, runner, update) -> None:
    if not runner.durable_receipts or arguments[0] != "param":
        return
    existing = record.get("config_receipt")
    if isinstance(existing, dict) and existing.get("status") == "applied":
        return
    receipt = verify_applied_config(workspace, candidate["parameters"])
    update(config_receipt=receipt)
    if receipt["status"] == "mismatch":
        raise invalid(f"Applied parameters did not reach the iteration config: {receipt['reason']}")
