"""Resume a failed materialized candidate in its existing workspace."""

import json
import os
import re
import tempfile
from pathlib import Path

from chipcompiler.runtime.operations import RuntimeOperationConflict, RuntimeOperationFailed
from chipcompiler.runtime.workspace_api import RuntimeApiError, _state_value
from chipcompiler.utility.path import path_is_within

from .data.candidate_artifacts import validate_candidate_id
from .data.candidate_materialization import (
    candidate_written_patch,
    reapply_materialized_candidate_config,
    validate_candidate_materialization_receipt,
)
from .requests import CandidateRerunRequest, CandidateResumeRequest
from .workspace_api import (
    _CANDIDATE_WORKSPACE_MANIFEST,
    _CANDIDATE_WORKSPACE_SCHEMA,
    _IDEMPOTENCY_KEY,
    _candidate_parent_binding,
    _candidate_rerun_result,
    _candidate_rerun_steps,
    _parent_workspace_root,
    _prepare_candidate_rerun,
    _reapply_candidate_input,
    _required_file_sha256,
    _run_candidate_step,
    _workspace_state_sha256,
)


def candidate_resume(api, request: CandidateResumeRequest) -> dict:
    _validate_candidate_resume_request(request)
    api.ecc_api._get_session(request.workspace_id)
    try:
        return api.ecc_api.operations.start(
            workspace_id=request.workspace_id,
            kind="candidate_resume",
            origin="agent",
            rerun=True,
            step="Harden",
            idempotency_key=request.idempotency_key,
            runner=lambda observer: api._with_workspace_lock(
                request.workspace_id,
                lambda session: _candidate_resume(api, session, request, observer),
            ),
        )
    except RuntimeOperationConflict as exc:
        raise RuntimeApiError("command_failed", str(exc)) from exc


def _candidate_resume(api, session, request: CandidateResumeRequest, observer) -> dict:
    candidate_workspace = flow = rerun_request = parent = None
    candidate_root_ref = f".agent/candidates/{request.candidate_id}"
    resume_step = None
    evidence_ready = False
    try:
        candidate_workspace, manifest, parent = _load_candidate_resume(
            api.ecc_api, session.workspace, request.candidate_id
        )
        flow = api._build_flow(candidate_workspace, create_step_workspaces=False)
        create_step_workspaces = getattr(flow, "create_step_workspaces", None)
        if callable(create_step_workspaces):
            create_step_workspaces(initialize_config=False)
        steps = _candidate_resume_steps(flow, manifest["target_step"])
        resume_step = steps[0].name
        patch = _validate_candidate_resume_binding(candidate_workspace, flow, manifest, request)
        rerun_request = _candidate_resume_rerun_request(manifest, request, patch)
        evidence_ready = True
        _prepare_candidate_rerun(candidate_workspace, flow, steps)
        _notify_candidate_resume_prepared(observer, steps, manifest["target_step"])
        for step in steps:
            _run_candidate_step(flow, step, observer=observer)
        result = _candidate_rerun_result(
            candidate_workspace,
            rerun_request,
            candidate_root_ref,
            parent,
            terminal_state="succeeded",
        )
        result["resumeStep"] = resume_step
        return result
    except Exception as exc:
        result = _candidate_resume_failure_result(
            request,
            candidate_workspace,
            rerun_request,
            candidate_root_ref,
            parent,
            resume_step,
            evidence_ready=evidence_ready,
        )
        raise RuntimeOperationFailed(
            str(exc), code=getattr(exc, "code", "command_failed"), result=result
        ) from exc
    finally:
        if flow is not None:
            api.ecc_api._close_transient_flow_db(flow)


def _candidate_resume_failure_result(
    request,
    workspace,
    rerun_request,
    candidate_root_ref: str,
    parent,
    resume_step,
    *,
    evidence_ready: bool,
) -> dict:
    result = {"candidateId": request.candidate_id, "candidateRootRef": candidate_root_ref}
    if not evidence_ready:
        return result
    try:
        result = _candidate_rerun_result(
            workspace,
            rerun_request,
            candidate_root_ref,
            parent,
            terminal_state="failed",
        )
        if resume_step is not None:
            result["resumeStep"] = resume_step
    except Exception as evidence_error:
        result["evidenceError"] = str(evidence_error)
    return result


def _validate_candidate_resume_request(request: CandidateResumeRequest) -> None:
    if not isinstance(request.workspace_id, str) or not request.workspace_id.strip():
        raise RuntimeApiError("invalid_request", "candidate resume workspace_id is invalid")
    try:
        validate_candidate_id(request.candidate_id)
    except ValueError as exc:
        raise RuntimeApiError(
            "invalid_request", "candidate resume candidate_id is invalid"
        ) from exc
    if not isinstance(request.idempotency_key, str) or not _IDEMPOTENCY_KEY.fullmatch(
        request.idempotency_key
    ):
        raise RuntimeApiError("invalid_request", "candidate resume idempotency key is invalid")
    if (
        not isinstance(request.context_sha256, str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", request.context_sha256) is None
    ):
        raise RuntimeApiError("invalid_request", "candidate resume context_sha256 is invalid")
    if (
        not isinstance(request.parameter_card_sha256, str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", request.parameter_card_sha256) is None
    ):
        raise RuntimeApiError(
            "invalid_request", "candidate resume parameter_card_sha256 is invalid"
        )
    if type(request.seed) is not int:
        raise RuntimeApiError("invalid_request", "candidate resume seed is invalid")


def _candidate_resume_steps(flow, target_step: str) -> list:
    steps = _candidate_rerun_steps(flow, target_step, "Harden", "full_flow")
    for index, step in enumerate(steps):
        record = flow.get_step(step.name, step.tool)
        if record is None:
            raise RuntimeApiError("command_failed", f"candidate flow state is missing: {step.name}")
        if _state_value(record.get("state")) != "Success":
            return steps[index:]
    raise RuntimeApiError("command_failed", "failed candidate has no resumable step")


def _load_candidate_resume(ecc_api, workspace, candidate_id: str):
    workspace_root = _parent_workspace_root(workspace)
    candidate_root_ref = f".agent/candidates/{validate_candidate_id(candidate_id)}"
    candidate_root = workspace_root / candidate_root_ref
    if (
        candidate_root.is_symlink()
        or not candidate_root.is_dir()
        or candidate_root.resolve() != candidate_root.absolute()
    ):
        raise RuntimeApiError("command_failed", "candidate resume workspace is unavailable")
    manifest_path = candidate_root / "analysis" / _CANDIDATE_WORKSPACE_MANIFEST
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeApiError("command_failed", "candidate resume manifest is invalid") from exc
    _validate_candidate_resume_manifest(
        workspace_root, candidate_root, candidate_root_ref, manifest
    )
    parent = _candidate_parent_binding(workspace_root, manifest.get("parent_candidate_root_ref"))
    _validate_candidate_resume_parent(manifest, parent)
    candidate_workspace = ecc_api._load_workspace(str(candidate_root))
    if Path(candidate_workspace.directory).resolve() != candidate_root:
        raise RuntimeApiError("command_failed", "candidate resume workspace escaped its root")
    return candidate_workspace, manifest, parent


def _validate_candidate_resume_manifest(
    workspace_root: Path, candidate_root: Path, candidate_root_ref: str, manifest: object
) -> None:
    expected = {
        "schema": _CANDIDATE_WORKSPACE_SCHEMA,
        "schema_version": 1,
        "candidate_id": Path(candidate_root_ref).name,
        "candidate_root_ref": candidate_root_ref,
        "terminal_state": "failed",
        "end_step": "Harden",
        "execution_scope": "full_flow",
        "candidate_flow_sha256": _required_file_sha256(
            candidate_root / "home" / "flow.json", "resume flow"
        ),
        "candidate_state_sha256": _workspace_state_sha256(candidate_root),
    }
    if not isinstance(manifest, dict) or any(
        manifest.get(key) != value for key, value in expected.items()
    ):
        raise RuntimeApiError("command_failed", "candidate resume manifest binding is invalid")
    if not isinstance(manifest.get("target_step"), str) or not manifest["target_step"]:
        raise RuntimeApiError("command_failed", "candidate resume target step is invalid")
    _validate_candidate_resume_artifacts(candidate_root, manifest.get("artifacts"))
    try:
        candidate_root.relative_to(workspace_root)
    except ValueError as exc:
        raise RuntimeApiError(
            "command_failed", "candidate resume workspace escaped its parent"
        ) from exc


def _validate_candidate_resume_artifacts(candidate_root: Path, artifacts: object) -> None:
    required = {
        "candidate_materialization": "analysis/candidate_materialization.v1.json",
        "candidate_input_binding": "analysis/candidate_input_binding.v1.json",
    }
    if not isinstance(artifacts, dict) or any(
        not isinstance(artifacts.get(key), dict) or artifacts[key].get("ref") != ref
        for key, ref in required.items()
    ):
        raise RuntimeApiError("command_failed", "candidate resume receipt is missing")
    for name, artifact in artifacts.items():
        if not isinstance(name, str) or not isinstance(artifact, dict):
            raise RuntimeApiError("command_failed", "candidate resume artifact binding is invalid")
        ref = artifact.get("ref")
        path = candidate_root / ref if isinstance(ref, str) else candidate_root.parent
        if (
            not isinstance(ref, str)
            or Path(ref).is_absolute()
            or not path_is_within(path.resolve(), candidate_root)
            or artifact.get("sha256") != _required_file_sha256(path, "resume artifact")
        ):
            raise RuntimeApiError("command_failed", "candidate resume artifact binding is invalid")


def _validate_candidate_resume_parent(manifest: dict, parent: dict) -> None:
    expected = {
        "parent_candidate_root_ref": parent["root_ref"],
        "parent_manifest_ref": parent["manifest_ref"],
        "parent_manifest_sha256": parent["manifest_sha256"],
        "parent_flow_sha256": parent["flow_sha256"],
        "parent_state_sha256": parent["state_sha256"],
    }
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise RuntimeApiError("command_failed", "candidate resume parent binding is invalid")


def _candidate_resume_rerun_request(
    manifest: dict, request: CandidateResumeRequest, patch: list[dict]
) -> CandidateRerunRequest:
    return CandidateRerunRequest(
        workspace_id=request.workspace_id,
        target_step=manifest["target_step"],
        end_step="Harden",
        candidate_id=request.candidate_id,
        patch=patch,
        execution_scope="full_flow",
        idempotency_key=request.idempotency_key,
        context_sha256=request.context_sha256,
        parameter_card_sha256=request.parameter_card_sha256,
        seed=request.seed,
        parent_candidate_root_ref=manifest["parent_candidate_root_ref"],
    )


def _validate_candidate_resume_binding(
    workspace, flow, manifest: dict, request: CandidateResumeRequest
) -> list[dict]:
    backups = _candidate_resume_config_backups(workspace)
    try:
        return _validated_candidate_resume_patch(workspace, flow, manifest, request)
    except Exception:
        try:
            _restore_candidate_resume_configs(workspace, backups)
        except OSError as rollback_error:
            raise RuntimeApiError(
                "command_failed", "candidate resume config rollback failed"
            ) from rollback_error
        raise


def _validated_candidate_resume_patch(
    workspace, flow, manifest: dict, request: CandidateResumeRequest
) -> list[dict]:
    target_step = manifest["target_step"]
    try:
        reapply_materialized_candidate_config(workspace, target_step)
        materialization = validate_candidate_materialization_receipt(workspace, target_step)
        if materialization is None or materialization["candidate_id"] != request.candidate_id:
            raise ValueError("candidate materialization receipt is missing or mismatched")
        _reapply_candidate_input(workspace, flow, target_step)
    except ValueError as exc:
        raise RuntimeApiError(
            "command_failed", f"candidate resume receipt binding is invalid: {exc}"
        ) from exc
    dreamplace_path = Path(workspace.config["dreamplace"])
    try:
        dreamplace = json.loads(dreamplace_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeApiError("command_failed", "candidate resume seed binding is invalid") from exc
    if not isinstance(dreamplace, dict) or dreamplace.get("random_seed") != request.seed:
        raise RuntimeApiError("command_failed", "candidate resume seed binding is invalid")
    requested_patch = _candidate_resume_requested_patch(
        workspace, manifest, request, materialization["patch"], target_step
    )
    try:
        written_patch = candidate_written_patch(workspace, target_step, requested_patch)
    except ValueError as exc:
        raise RuntimeApiError(
            "command_failed", "candidate resume requested patch binding is invalid"
        ) from exc
    if written_patch != materialization["patch"]:
        raise RuntimeApiError(
            "command_failed", "candidate resume requested patch binding is invalid"
        )
    return requested_patch


def _candidate_resume_requested_patch(
    workspace,
    manifest: dict,
    request: CandidateResumeRequest,
    materialized_patch: list[dict],
    target_step: str,
) -> list[dict]:
    application = manifest["artifacts"].get("parameter_application_receipt")
    if application is None:
        return materialized_patch
    try:
        receipt = json.loads(
            (Path(workspace.directory) / application["ref"]).read_text(encoding="utf-8")
        )
        context = receipt["context"]
        requested = receipt["requested"]
    except (KeyError, OSError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeApiError(
            "command_failed", "candidate resume context binding is invalid"
        ) from exc
    if (
        context.get("context_sha256") != request.context_sha256
        or context.get("parameter_card_sha256") != request.parameter_card_sha256
        or context.get("seed") != request.seed
        or context.get("run_id") != request.candidate_id
        or context.get("stage") != target_step
    ):
        raise RuntimeApiError("command_failed", "candidate resume context binding is invalid")
    return [{"knob_id": requested.get("knob_id"), "value": requested.get("value")}]


def _candidate_resume_config_backups(workspace) -> dict[Path, bytes]:
    root = Path(workspace.directory)
    relatives = (
        "home/parameters.json",
        "config/floorplan_ecc.json",
        "config/cts_ecc.json",
        "config/dreamplace_ecc.json",
        "config/dreamplace.json",
    )
    paths = [root / relative for relative in relatives]
    if any(path.is_symlink() for path in paths):
        raise RuntimeApiError("command_failed", "candidate resume config path is unsafe")
    return {path: path.read_bytes() for path in paths if path.is_file()}


def _restore_candidate_resume_configs(workspace, backups: dict[Path, bytes]) -> None:
    for path, content in backups.items():
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
            temporary.write(content)
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)
    parameters = getattr(workspace, "parameters", None)
    parameters_path = getattr(parameters, "path", None)
    if parameters_path and Path(parameters_path) in backups:
        parameters.data = json.loads(backups[Path(parameters_path)])


def _notify_candidate_resume_prepared(observer, steps: list, target_step: str) -> None:
    callback = getattr(observer, "on_rerun_prepared", None)
    if callable(callback):
        callback(
            affected_steps=[str(step.name) for step in steps],
            scope="full_flow",
            target_step=target_step,
        )
