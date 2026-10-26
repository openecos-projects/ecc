"""Validate optimizer outputs using the existing CLI quality-gate contract."""

import json
from contextlib import suppress
from pathlib import Path

from chipcompiler.cli.experiments.candidate_evidence import candidate_evidence
from ecc_experience.adapters.chipcompiler_reader import read_workspace_observation
from ecc_experience.collection.collect import collect_committed_case
from ecc_experience.files import SMALL_EVIDENCE_LIMIT, read_json
from ecc_experience.knowledge.recommend import _input_fingerprint, _sanitize
from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.knowledge.verify import verify_case
from ecc_experience.models import ExperienceError, WorkspaceObservation, parameter_evidence_level
from ecc_experience.optimization.policy import configuration_differences
from ecc_experience.optimization.process import CliRunner


def inspect_workspace(
    project: Path,
    workspace: Path,
    runner: CliRunner,
    deadline: float,
    *,
    exit_code: int = 0,
) -> dict:
    status = runner.invoke(
        ["status", "--project", str(project), "--workspace", str(workspace), "--json"],
        deadline=deadline,
    )
    signoff = runner.invoke(
        ["signoff", "check", "--project", str(project), "--workspace", str(workspace), "--json"],
        deadline=deadline,
    )
    payload = None
    if signoff.stdout.exists() and signoff.stdout.stat().st_size <= SMALL_EVIDENCE_LIMIT:
        with suppress(ValueError, UnicodeError):
            payload = json.loads(signoff.stdout.read_text())
    home = workspace / "home"
    return candidate_evidence(
        read_json(home / "flow.json"),
        read_json(home / "checklist.json"),
        read_json(home / "qor_report.json"),
        exit_code=exit_code,
        status_code=status.exit_code,
        signoff_code=signoff.exit_code,
        signoff_payload=payload,
    )


def check_trial_configuration(
    workspace: Path,
    baseline: WorkspaceObservation,
    parameters: dict,
) -> WorkspaceObservation:
    observation = read_workspace_observation(workspace)
    baseline_spec = baseline.facts["workspaceSpec"]
    trial_spec = observation.facts["workspaceSpec"]
    if _input_fingerprint(baseline.facts, baseline.inputs) != _input_fingerprint(
        observation.facts, observation.inputs
    ):
        raise ExperienceError(
            "Trial input content differs from baseline", code="experience_source_changed"
        )
    if any(trial_spec.get(key) != baseline_spec.get(key) for key in ("design", "pdk", "flow")):
        raise ExperienceError(
            "Trial design, PDK or flow differs from baseline", code="experience_source_changed"
        )
    expected = {**_sanitize(baseline_spec["parameters"]), **parameters}
    if configuration_differences(expected, _sanitize(trial_spec["parameters"])):
        raise ExperienceError(
            "Trial parameters differ from the authorized configuration",
            code="experience_source_changed",
        )
    return observation


def validate_trial(
    workspace: Path,
    store: str | Path,
    baseline: WorkspaceObservation,
    parameters: dict,
    run_id: str,
    *,
    execution_context: dict | None = None,
    parameter_evidence: dict | None = None,
) -> dict:
    observation = check_trial_configuration(workspace, baseline, parameters)
    baseline_qor = baseline.facts.get("qorSnapshotExtension", {})
    trial_qor = observation.facts.get("qorSnapshotExtension", {})
    if any(trial_qor.get(key) != baseline_qor.get(key) for key in ("scoringEngine", "profile")):
        raise ExperienceError(
            "Trial QoR scoring configuration changed", code="experience_source_changed"
        )
    repository = ExperienceStore(store)
    collected = collect_committed_case(
        workspace,
        repository,
        read_workspace_observation,
        attempt_id=run_id,
        expected_snapshot_digest=observation.source.snapshot_digest,
        execution_context=execution_context,
        parameter_evidence=parameter_evidence,
    )
    verification = verify_case(collected.case, repository.case_directory(collected.case.case_id))
    return {
        "case_id": collected.case.case_id,
        "verification": verification.model_dump(),
        "snapshot_digest": observation.source.snapshot_digest,
        "parameter_evidence": parameter_evidence_level(collected.case),
    }
