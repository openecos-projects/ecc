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
    for candidate in plan["candidates"]:
        validate_parameter_boundary(
            list(candidate["parameters"]), names[: names.index(plan["through_step"]) + 1]
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
) -> None:
    started = time.monotonic()
    deadline = min(runner.deadline, started + limits.trial_timeout_seconds)
    workspace_id = f"dse_{uuid4().hex[:16]}"
    root = Path(plan["project"])
    workspace = root / workspace_id
    run_id = str(uuid4())
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
        for arguments in commands:
            if arguments[0] == "run":
                check_trial_configuration(workspace, baseline, candidate["parameters"])
            command = {"arguments": arguments, "status": "running"}
            record["commands"].append(command)
            save()
            result = runner.invoke(
                [*arguments, "--project", str(root), "--plain"], deadline=deadline
            )
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
        record.update(status="failed", reason=str(exc))
        if record["collection_status"] == "pending":
            record["collection_status"] = "failed"
        if isinstance(exc, ExperienceError) and exc.code == "experience_source_changed":
            record["exit_code"] = 21
            raise
    finally:
        record["elapsed_seconds"] = round(time.monotonic() - started, 3)
        for command in record["commands"]:
            if command["status"] == "running":
                command.update(status="interrupted", exit_code=record["exit_code"])
        save()
