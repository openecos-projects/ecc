"""Execute one isolated baseline using public ECC commands and committed evidence."""

import time
from collections.abc import Callable
from pathlib import Path

from chipcompiler.project.manifest import CONFIG_FILENAME
from ecc_experience.adapters.process_context import process_context
from ecc_experience.benchmark.evidence import collect_trial
from ecc_experience.benchmark.preparation import PreparedDesign, runtime_identity
from ecc_experience.models import ExperienceError
from ecc_experience.optimization.evidence import (
    check_trial_configuration,
    inspect_workspace,
)
from ecc_experience.optimization.plan import write_plan
from ecc_experience.optimization.process import CliRunner


def execute_trial(
    source: PreparedDesign,
    directory: Path,
    store: str,
    timeout: int,
    record: dict,
    save: Callable[[], None],
    check_inputs: Callable[[], None],
) -> None:
    started = time.monotonic()
    deadline = started + timeout
    runner = CliRunner(directory, deadline, durable_receipts=True)
    project = directory / "project"
    workspace = project / record["workspace"]
    run_log = workspace / "log" / f"{record['run_id']}.log"
    run_invoked = False
    record.update(project=str(project), workspace_path=str(workspace), flow_log=str(run_log))

    def invoke(arguments: list[str]) -> int:
        command = {"arguments": arguments, "status": "running"}
        record["commands"].append(command)
        save()

        def prepared(metadata: dict) -> None:
            command.update(metadata)
            save()

        result = runner.invoke(arguments, deadline=deadline, on_prepared=prepared)
        command.update(
            status="complete",
            exit_code=result.exit_code,
            stdout=str(result.stdout),
            stderr=str(result.stderr),
        )
        save()
        return result.exit_code

    try:
        commands = [
            ["init", str(project), "--design-name", source.design_name, "--plain"],
            [
                "workspace",
                "import",
                "source",
                "--path",
                str(source.workspace),
                "--project",
                str(project),
                "--no-wait",
                "--plain",
            ],
            [
                "workspace",
                "derive",
                "source",
                record["workspace"],
                "--project",
                str(project),
                "--no-wait",
                "--plain",
            ],
            [
                "run",
                "--workspace",
                record["workspace"],
                "--run-id",
                record["run_id"],
                "--project",
                str(project),
                "--no-wait",
                "--plain",
            ],
        ]
        for command in commands:
            check_inputs()
            if command[0] == "run":
                check_trial_configuration(workspace, source.observation, {})
                record["execution_status"] = "running"
                run_invoked = True
            record["exit_code"] = invoke(command)
            if record["exit_code"] != 0:
                break
            if command[0] == "init":
                (project / CONFIG_FILENAME).unlink()
        record["execution_status"] = "complete" if record["exit_code"] == 0 else "failed"
        record["status"] = "fail"
        if record["exit_code"] == 124:
            record.update(execution_status="timeout", reason="trial_timeout")
            return
        check_inputs()
        if run_invoked:
            complete_trial(source, directory, store, record, runner, deadline)
    except KeyboardInterrupt:
        record.update(
            status="cancelled", execution_status="cancelled", exit_code=130, reason="user_interrupt"
        )
        raise
    except (ExperienceError, OSError) as exc:
        record.update(status="fail", reason=str(exc))
        if record["collection_status"] == "pending":
            record["collection_status"] = "failed"
        if isinstance(exc, ExperienceError) and exc.code == "experience_source_changed":
            record.update(exit_code=21, reason=exc.code)
            raise
        if isinstance(exc, ExperienceError) and exc.code == "experience_workspace_busy":
            record.update(status="blocked", exit_code=20, reason=exc.code)
            raise
    finally:
        record["elapsed_seconds"] = round(time.monotonic() - started, 3)
        for command in record["commands"]:
            if command["status"] == "running":
                command.update(status="interrupted", exit_code=record["exit_code"])
        save()


def complete_trial(
    source: PreparedDesign,
    directory: Path,
    store: str,
    record: dict,
    runner: CliRunner,
    deadline: float,
) -> None:
    project = Path(record["project"])
    workspace = Path(record["workspace_path"])
    run_log = Path(record["flow_log"])
    marker = f"ECC run {record['run_id']} started\n".encode()
    executed = False
    if run_log.is_file():
        with run_log.open("rb") as stream:
            executed = stream.read(len(marker)) == marker
    if not executed:
        record["reason"] = "run_not_started"
        return
    evidence = inspect_workspace(
        project, workspace, runner, deadline, exit_code=record["exit_code"]
    )
    record["acceptance"] = evidence
    if 124 in (evidence["signoff_exit_code"], evidence["workspace_status_exit_code"]):
        record.update(exit_code=124, execution_status="timeout", reason="trial_timeout")
        return
    record["collection_status"] = "pending"
    context = None
    if record.get("execution_runtime") is not None:
        if (
            runtime_identity() != record["execution_runtime"]
            or process_context(source.observation.facts) != source.process_context
        ):
            raise ExperienceError(
                "Execution runtime or PDK changed", code="experience_source_changed"
            )
        context = {
            "schema": "ecc-experience-execution-context/1",
            "attempt_id": record["run_id"],
            "runtime": record["execution_runtime"],
            "process": source.process_context,
            "scope": "campaign_runtime_and_selected_pdk_content_checked_before_and_after",
        }
    collected = collect_trial(
        workspace, store, source.observation, record["run_id"], execution_context=context
    )
    verification = collected["verification"]
    verification_path = directory / "case-verification.json"
    write_plan(verification_path, verification)
    record.update(
        {
            **collected,
            "verification": {key: verification[key] for key in ("case_id", "status", "integrity")},
            "verification_file": str(verification_path),
        }
    )
    record["collection_status"] = "collected"
    record["status"] = {
        "passed": "pass",
        "failed": "fail",
        "blocked": "blocked",
        "unknown": "blocked",
    }[evidence["status"]]
    if record["status"] == "pass" and record.get("verification", {}).get("status") != "pass":
        record["status"] = "blocked"
    record["reason"] = None if record["status"] == "pass" else "acceptance_not_passed"
