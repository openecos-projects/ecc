import time
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from chipcompiler.project.manifest import load_manifest
from ecc_experience.adapters.chipcompiler_reader import read_workspace_observation
from ecc_experience.adapters.process_context import process_context
from ecc_experience.benchmark.evidence import collect_trial
from ecc_experience.benchmark.preparation import runtime_identity
from ecc_experience.dse.evidence import stage_acceptance
from ecc_experience.dse.plan import (
    DseLimits,
    invalid,
    project_configuration,
    validate_parameter_boundary,
)
from ecc_experience.models import ExperienceError, WorkspaceObservation
from ecc_experience.optimization.evidence import check_trial_configuration, inspect_workspace
from ecc_experience.optimization.process import CliRunner


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
) -> None:
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
        record.update(
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
    commands = [["workspace", "derive", plan["source_workspace_id"], workspace_id, "--no-wait"]]
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
    try:
        baseline = check_source(plan)
        for index, arguments in enumerate(commands):
            if arguments[0] == "run":
                check_trial_configuration(workspace, baseline, candidate["parameters"])
            expected = [*arguments, "--project", str(root), "--plain"]
            if index < len(record["commands"]):
                command = record["commands"][index]
                if command["arguments"] != arguments:
                    raise invalid("DSE command sequence changed")
                if command["status"] != "complete":
                    from ecc_experience.dse.receipts import recover_command

                    recover_command(command, expected, runner.output)
                record["exit_code"] = command["exit_code"]
                save()
                if command["exit_code"] != 0:
                    break
                continue
            command = {"arguments": arguments, "status": "running"}
            record["commands"].append(command)
            save()
            if runner.durable_receipts:

                def prepared(metadata, target=command):
                    target.update(metadata)
                    save()

                result = runner.invoke(expected, deadline=deadline, on_prepared=prepared)
            else:
                result = runner.invoke(expected, deadline=deadline)
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
        if record["exit_code"] == 124:
            record["status"] = "timeout"
            return
        marker = f"ECC run {run_id} started\n".encode()
        log = workspace / "log" / f"{run_id}.log"
        executed = False
        if log.is_file():
            with log.open("rb") as stream:
                executed = stream.read(len(marker)) == marker
        if not executed:
            record.update(status="failed", reason="run_not_started")
            return
        check_source(plan)
        facts = deepcopy(baseline.facts)
        facts["workspaceSpec"]["parameters"].update(candidate["parameters"])
        requested = replace(baseline, facts=facts)
        context = {
            "schema": "ecc-experience-execution-context/1",
            "attempt_id": run_id,
            "runtime": plan["runtime"],
            "process": plan["process"],
            "scope": "dse_runtime_and_selected_pdk_content_checked_before_and_after",
        }
        record["collection_status"] = "pending"
        collected = collect_trial(
            workspace, plan["store"], requested, run_id, execution_context=context
        )
        record.update(collected, collection_status="collected")
        if mode == "screen":
            record.update(
                stage_acceptance(
                    record["case_id"], plan["store"], plan, exit_code=record["exit_code"]
                )
            )
        else:
            evidence = inspect_workspace(
                root, workspace, runner, deadline, exit_code=record["exit_code"]
            )
            record.update(evidence, validation_scope="full_flow")
            if record["status"] == "passed" and record["verification"]["status"] != "pass":
                record.update(status="unknown", reason="case_verification_not_passed")
            if 124 in (evidence["workspace_status_exit_code"], evidence["signoff_exit_code"]):
                record.update(status="timeout", exit_code=124)
    except KeyboardInterrupt:
        record.update(status="cancelled", exit_code=130, reason="user_interrupt")
        raise
    except (ExperienceError, OSError) as exc:
        if isinstance(exc, ExperienceError) and exc.code == "experience_workspace_busy":
            record.update(status="running", reason=str(exc))
            raise
        record.update(status="failed", reason=str(exc), exit_code=record["exit_code"] or 1)
        if record["collection_status"] == "pending":
            record["collection_status"] = "failed"
        if isinstance(exc, ExperienceError) and exc.code == "experience_source_changed":
            record["exit_code"] = 21
            raise
    finally:
        record["elapsed_seconds"] = round(elapsed + time.monotonic() - started, 3)
        for command in record["commands"]:
            if command["status"] == "running":
                command.update(status="interrupted", exit_code=record["exit_code"])
        save()
