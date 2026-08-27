import json
import os
import re
import shutil
from hashlib import sha256
from pathlib import Path

from chipcompiler.runtime.operations import RuntimeOperationConflict
from chipcompiler.runtime.requests import WorkspaceIdRequest
from chipcompiler.runtime.workspace_api import (
    RuntimeApiError,
    WorkspaceRuntimeApi,
    _init_db_engine_for_workspace_step,
    _state_value,
)
from chipcompiler.utility.path import path_is_within

from .data import (
    FoundationExtractor,
    bind_candidate_input,
    export_candidate_capabilities,
    materialize_candidate_config,
    reapply_candidate_input_binding,
    validate_candidate_step_contract,
)
from .data.candidate_artifacts import sha256_path, validate_candidate_id, write_json_atomic
from .data.parameter_application_receipt import build_parameter_application_receipt
from .engine import AgentEngineFlow
from .requests import (
    CandidateBindInputRequest,
    CandidateMaterializeRequest,
    CandidateRerunRequest,
    WorkspaceExtractFoundationRequest,
)


def _stable_hash(value) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return f"sha256:{sha256(payload).hexdigest()}"


def _parameter_unit(knob_id: str) -> str:
    if knob_id.endswith("routability_opt"):
        return "boolean"
    if knob_id.endswith("cell_padding_x"):
        return "site"
    if knob_id.endswith("fanout"):
        return "fanout"
    if knob_id.endswith("density_weight"):
        return "objective_weight"
    return "ratio"


def build_agent_flow_for_workspace(workspace, *, create_step_workspaces: bool = True):
    import chipcompiler.rtl2gds as rtl2gds_api

    flow = AgentEngineFlow(workspace=workspace)
    if not flow.has_init():
        for step, tool, state in rtl2gds_api.build_harden_flow():
            flow.add_step(step=step, tool=tool, state=state)
    if create_step_workspaces:
        flow.create_step_workspaces()
    return flow


class FlowAgentRuntimeApi:
    """Optional Flow Agent RPC handlers over one ECC workspace runtime."""

    def __init__(self, ecc_api: WorkspaceRuntimeApi):
        self.ecc_api = ecc_api

    def extract_foundation(self, request: WorkspaceExtractFoundationRequest) -> dict:
        def extract(session):
            workspace_dir = Path(session.workspace.directory).resolve()
            FoundationExtractor(str(workspace_dir), profile="iccd_full_v1").extract(
                include_raw_refs=False,
                materialize_audit_tables=True,
                route_detail_level="full",
            )
            return _foundation_receipt(workspace_dir)

        return self._with_workspace_lock(request.workspace_id, extract)

    def export_candidate_capabilities(self, request: WorkspaceIdRequest) -> dict:
        return self._with_workspace_lock(
            request.workspace_id,
            lambda session: export_candidate_capabilities(session.workspace),
        )

    def bind_candidate_input(self, request: CandidateBindInputRequest) -> dict:
        def bind(session):
            flow = build_agent_flow_for_workspace(session.workspace)
            return bind_candidate_input(
                session.workspace,
                flow,
                request.target_step,
                request.source_step,
                request.candidate_id,
            )

        return self._with_workspace_lock(request.workspace_id, bind)

    def materialize_candidate(self, request: CandidateMaterializeRequest) -> dict:
        return self._with_workspace_lock(
            request.workspace_id,
            lambda session: materialize_candidate_config(
                session.workspace,
                request.target_step,
                request.patch,
                request.candidate_id,
            ),
        )

    def candidate_rerun(self, request: CandidateRerunRequest) -> dict:
        _validate_candidate_rerun_request(request)
        self.ecc_api._get_session(request.workspace_id)
        try:
            return self.ecc_api.operations.start(
                workspace_id=request.workspace_id,
                kind="candidate_rerun",
                origin="agent",
                rerun=True,
                step=request.target_step,
                idempotency_key=request.idempotency_key,
                runner=lambda observer: self._with_workspace_lock(
                    request.workspace_id,
                    lambda session: self._candidate_rerun(session, request, observer),
                ),
            )
        except RuntimeOperationConflict as exc:
            raise RuntimeApiError("command_failed", str(exc)) from exc

    def _candidate_rerun(self, session, request: CandidateRerunRequest, observer) -> dict:
        (
            candidate_workspace,
            candidate_root_ref,
            parent_flow_sha256,
            parent_state_sha256,
        ) = _create_candidate_workspace(
            self.ecc_api,
            session.workspace,
            request.candidate_id,
            request.parent_candidate_root_ref,
        )
        flow = self._build_flow(candidate_workspace, create_step_workspaces=False)
        try:
            if request.patch:
                _materialize_candidate_rerun(candidate_workspace, flow, request)
            create_step_workspaces = getattr(flow, "create_step_workspaces", None)
            if callable(create_step_workspaces):
                create_step_workspaces()
            steps = _candidate_rerun_steps(
                flow,
                request.target_step,
                request.end_step,
                request.execution_scope,
            )
            _prepare_candidate_rerun(candidate_workspace, flow, steps)
            _notify_candidate_rerun_prepared(observer, steps, request)
            if request.patch:
                _reapply_candidate_input(candidate_workspace, flow, request.target_step)
            for step in steps:
                _run_candidate_step(flow, step, observer=observer)
            parameter_receipt = None
            materialization_path = (
                Path(candidate_workspace.directory)
                / "analysis"
                / "candidate_materialization.v1.json"
            )
            if materialization_path.is_file():
                parameter_receipt = _candidate_parameter_receipt(
                    candidate_workspace,
                    request,
                    candidate_root_ref,
                    materialization_path,
                    parent_flow_sha256,
                )
            result = {
                "candidateId": request.candidate_id,
                **_candidate_workspace_receipt(
                    candidate_workspace,
                    candidate_root_ref,
                    request.candidate_id,
                    parent_flow_sha256,
                    request.parent_candidate_root_ref,
                    request.target_step,
                    request.end_step,
                    request.execution_scope,
                    parent_state_sha256,
                ),
                "endStep": request.end_step,
                "executionScope": request.execution_scope,
                "targetStep": request.target_step,
            }
            if parameter_receipt is not None:
                result["parameterApplicationReceipt"] = parameter_receipt
            return result
        finally:
            self.ecc_api._close_transient_flow_db(flow)

    def _build_flow(self, workspace, *, create_step_workspaces: bool = True):
        try:
            flow = build_agent_flow_for_workspace(
                workspace, create_step_workspaces=create_step_workspaces
            )
        except TypeError as exc:
            if "create_step_workspaces" not in str(exc):
                raise
            flow = build_agent_flow_for_workspace(workspace)
        return flow

    def _with_workspace_lock(self, workspace_id: str, operation):
        return self.ecc_api._with_session_mutation_lock(workspace_id, operation)


def _foundation_receipt(workspace_dir: Path) -> dict:
    manifest = workspace_dir / "foundation_data/ecc/manifest.json"
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeApiError("command_failed", f"foundation extraction failed: {exc}") from exc
    if payload.get("contract_name") != "foundation_data/ecc":
        raise RuntimeApiError(
            "command_failed", "foundation extractor produced an unsupported contract"
        )
    return {
        "manifestRef": "foundation_data/ecc/manifest.json",
        "manifestSha256": sha256(manifest.read_bytes()).hexdigest(),
        "contractName": payload["contract_name"],
        "schemaVersion": payload.get("schema_version"),
    }


def _candidate_rerun_steps(flow, target_step: str, end_step: str, execution_scope: str) -> list:
    if execution_scope not in {"single_step", "full_flow"}:
        raise RuntimeApiError("invalid_request", "candidate rerun execution scope is invalid")
    steps = list(getattr(flow, "workspace_steps", ()))
    target_index = next(
        (index for index, step in enumerate(steps) if step.name == target_step), None
    )
    end_index = next((index for index, step in enumerate(steps) if step.name == end_step), None)
    if target_index is None or end_index is None:
        raise RuntimeApiError(
            "command_failed", f"rerun step not found: {target_step} or {end_step}"
        )
    if execution_scope == "single_step":
        if target_step != end_step:
            raise RuntimeApiError(
                "invalid_request", "single-step rerun end step must match the target step"
            )
        return [steps[target_index]]
    if end_index < target_index:
        raise RuntimeApiError("invalid_request", "rerun end step precedes the target step")
    return steps[target_index : end_index + 1]


_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


def _validate_candidate_rerun_request(request: CandidateRerunRequest) -> None:
    for name in ("workspace_id", "target_step", "end_step", "candidate_id"):
        value = getattr(request, name)
        if not isinstance(value, str) or not value.strip():
            raise RuntimeApiError("invalid_request", f"candidate rerun {name} is invalid")
    try:
        validate_candidate_id(request.candidate_id)
    except ValueError as exc:
        raise RuntimeApiError("invalid_request", "candidate rerun candidate_id is invalid") from exc
    if request.execution_scope != "full_flow":
        raise RuntimeApiError(
            "invalid_request", "candidate rerun execution scope must be full_flow"
        )
    if not isinstance(request.patch, list) or len(request.patch) != 1:
        raise RuntimeApiError("invalid_request", "candidate rerun requires exactly one patch item")
    patch_item = request.patch[0]
    if not isinstance(patch_item, dict) or set(patch_item) != {"knob_id", "value"}:
        raise RuntimeApiError(
            "invalid_request", "candidate rerun patch item must contain only knob_id and value"
        )
    if not isinstance(patch_item["knob_id"], str) or not patch_item["knob_id"]:
        raise RuntimeApiError("invalid_request", "candidate rerun knob_id is invalid")
    try:
        json.dumps(patch_item["value"], allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise RuntimeApiError("invalid_request", "candidate rerun value is not JSON") from exc
    if not isinstance(request.idempotency_key, str) or not _IDEMPOTENCY_KEY.fullmatch(
        request.idempotency_key
    ):
        raise RuntimeApiError("invalid_request", "candidate rerun idempotency key is invalid")
    if request.parent_candidate_root_ref is not None:
        _validate_parent_candidate_root_ref(request.parent_candidate_root_ref)


def _notify_candidate_rerun_prepared(observer, steps: list, request: CandidateRerunRequest) -> None:
    callback = getattr(observer, "on_rerun_prepared", None)
    if callable(callback):
        callback(
            affected_steps=[str(step.name) for step in steps],
            scope=request.execution_scope,
            target_step=request.target_step,
        )


_CANDIDATE_WORKSPACE_SCHEMA = "ecc.workspace.candidate_workspace.v1"
_CANDIDATE_WORKSPACE_MANIFEST = "candidate_workspace.v1.json"


def _create_candidate_workspace(
    ecc_api, workspace, candidate_id: str, parent_candidate_root_ref: str | None = None
):
    workspace_root = _parent_workspace_root(workspace)
    source_root = _candidate_parent_root(workspace_root, parent_candidate_root_ref)
    _reject_workspace_symlinks(source_root)
    candidate_root = _candidate_workspace_root(workspace_root, candidate_id)
    parent_flow_sha256 = _required_file_sha256(source_root / "home" / "flow.json", "flow")
    parent_state_sha256 = _workspace_state_sha256(source_root)
    candidate_root.parent.mkdir(parents=True, exist_ok=True)
    try:
        candidate_root.parent.resolve().relative_to(workspace_root)
    except ValueError as exc:
        raise RuntimeApiError(
            "command_failed", "candidate workspace root escaped its parent"
        ) from exc
    if candidate_root.exists() or candidate_root.is_symlink():
        raise RuntimeApiError("command_failed", "candidate workspace already exists")
    try:
        shutil.copytree(source_root, candidate_root, ignore=shutil.ignore_patterns(".agent"))
    except OSError as exc:
        _remove_failed_candidate_workspace(candidate_root)
        raise RuntimeApiError("command_failed", f"candidate workspace clone failed: {exc}") from exc
    candidate_workspace = ecc_api._load_workspace(str(candidate_root))
    if Path(candidate_workspace.directory).resolve() != candidate_root:
        raise RuntimeApiError("command_failed", "candidate workspace load escaped its root")
    return (
        candidate_workspace,
        candidate_root.relative_to(workspace_root).as_posix(),
        parent_flow_sha256,
        parent_state_sha256,
    )


def _workspace_state_sha256(root: Path) -> str:
    relative_files = (
        "home/flow.json",
        "home/parameters.json",
        "config/floorplan_ecc.json",
        "config/fixfanout_ecc.json",
        "config/dreamplace_ecc.json",
    )
    hashes = {
        relative: _required_file_sha256(root / relative, relative)
        for relative in relative_files
        if (root / relative).is_file() and not (root / relative).is_symlink()
    }
    if not hashes:
        raise RuntimeApiError("command_failed", "candidate parent state is unavailable")
    return _stable_hash(hashes)


def _parent_workspace_root(workspace) -> Path:
    directory = Path(workspace.directory).expanduser()
    if directory.is_symlink() or not directory.is_dir():
        raise RuntimeApiError("command_failed", "candidate parent workspace is invalid")
    return directory.resolve()


def _validate_parent_candidate_root_ref(value: object) -> str:
    if not isinstance(value, str):
        raise RuntimeApiError(
            "invalid_request", "candidate rerun parent_candidate_root_ref is invalid"
        )
    parts = Path(value).parts
    if len(parts) != 3 or parts[:2] != (".agent", "candidates"):
        raise RuntimeApiError(
            "invalid_request", "candidate rerun parent_candidate_root_ref is invalid"
        )
    try:
        validate_candidate_id(parts[2])
    except ValueError as exc:
        raise RuntimeApiError(
            "invalid_request", "candidate rerun parent_candidate_root_ref is invalid"
        ) from exc
    return value


def _candidate_parent_root(workspace_root: Path, candidate_root_ref: str | None) -> Path:
    if candidate_root_ref is None:
        return workspace_root
    source = workspace_root / _validate_parent_candidate_root_ref(candidate_root_ref)
    resolved = source.resolve()
    if source.is_symlink() or not source.is_dir() or resolved != source.absolute():
        raise RuntimeApiError("command_failed", "candidate parent workspace is invalid")
    return resolved


def _reject_workspace_symlinks(workspace_root: Path) -> None:
    for directory, directories, files in os.walk(workspace_root, followlinks=False):
        for name in directories + files:
            if (Path(directory) / name).is_symlink():
                raise RuntimeApiError(
                    "command_failed", "candidate parent workspace has a symbolic link"
                )
        if Path(directory) == workspace_root:
            directories[:] = [name for name in directories if name != ".agent"]


def _candidate_workspace_root(parent_root: Path, candidate_id: str) -> Path:
    try:
        validate_candidate_id(candidate_id)
    except ValueError as exc:
        raise RuntimeApiError("invalid_request", "candidate rerun candidate_id is invalid") from exc
    root = parent_root / ".agent" / "candidates" / candidate_id
    if root.exists() or root.is_symlink():
        raise RuntimeApiError("command_failed", "candidate workspace already exists")
    return root


def _required_file_sha256(path: Path, label: str) -> str:
    if path.is_symlink() or not path.is_file() or (digest := sha256_path(path)) is None:
        raise RuntimeApiError("command_failed", f"candidate {label} is missing or unsafe")
    return digest


def _remove_failed_candidate_workspace(candidate_root: Path) -> None:
    if candidate_root.is_dir() and not candidate_root.is_symlink():
        shutil.rmtree(candidate_root)


def _candidate_workspace_receipt(
    workspace,
    candidate_root_ref: str,
    candidate_id: str,
    parent_flow_sha256: str,
    parent_candidate_root_ref: str | None,
    target_step: str,
    end_step: str,
    execution_scope: str,
    parent_state_sha256: str,
) -> dict:
    candidate_root = Path(workspace.directory).resolve()
    manifest_path = candidate_root / "analysis" / _CANDIDATE_WORKSPACE_MANIFEST
    if manifest_path.parent.is_symlink():
        raise RuntimeApiError("command_failed", "candidate manifest path is unsafe")
    candidate_flow_sha256 = _required_file_sha256(candidate_root / "home" / "flow.json", "flow")
    manifest = {
        "schema": _CANDIDATE_WORKSPACE_SCHEMA,
        "schema_version": 1,
        "candidate_id": candidate_id,
        "candidate_root_ref": candidate_root_ref,
        "parent_candidate_root_ref": parent_candidate_root_ref,
        "parent_flow_sha256": parent_flow_sha256,
        "parent_state_sha256": parent_state_sha256,
        "candidate_flow_sha256": candidate_flow_sha256,
        "target_step": target_step,
        "end_step": end_step,
        "execution_scope": execution_scope,
    }
    artifacts = {}
    for key, relative in (
        ("candidate_materialization", "analysis/candidate_materialization.v1.json"),
        ("candidate_input_binding", "analysis/candidate_input_binding.v1.json"),
        ("parameter_runtime_report", "analysis/parameter_runtime_report.v1.json"),
        ("parameter_application_receipt", "analysis/parameter_application_receipt.v1.json"),
    ):
        artifact = candidate_root / relative
        if artifact.is_file() and not artifact.is_symlink():
            artifacts[key] = {
                "ref": relative,
                "sha256": _required_file_sha256(artifact, key),
            }
    if artifacts:
        manifest["artifacts"] = artifacts
    replay_path = candidate_root / "analysis" / "candidate_execution_receipt.v1.json"
    replay = {
        "schema": "ecc.candidate_execution_receipt.v1",
        "candidate_id": candidate_id,
        "candidate_root_ref": candidate_root_ref,
        "parent_candidate_root_ref": parent_candidate_root_ref,
        "parent_flow_sha256": parent_flow_sha256,
        "parent_state_sha256": parent_state_sha256,
        "target_step": target_step,
        "end_step": end_step,
        "execution_scope": execution_scope,
        "candidate_manifest_sha256": None,
    }
    try:
        write_json_atomic(replay_path, replay)
    except OSError as exc:
        raise RuntimeApiError(
            "command_failed", f"candidate replay receipt write failed: {exc}"
        ) from exc
    artifacts["candidate_execution_receipt"] = {
        "ref": "analysis/candidate_execution_receipt.v1.json",
        "sha256": _required_file_sha256(replay_path, "candidate replay receipt"),
    }
    try:
        write_json_atomic(manifest_path, manifest)
    except OSError as exc:
        raise RuntimeApiError("command_failed", f"candidate manifest write failed: {exc}") from exc
    manifest_sha256 = _required_file_sha256(manifest_path, "manifest")
    return {
        "candidateRootRef": candidate_root_ref,
        "candidateManifestRef": f"{candidate_root_ref}/analysis/{_CANDIDATE_WORKSPACE_MANIFEST}",
        "candidateManifestSha256": manifest_sha256,
    }


def _candidate_parameter_receipt(
    workspace,
    request,
    candidate_root_ref: str,
    materialization_path: Path,
    parent_flow_sha256: str | None = None,
) -> dict:
    materialization = json.loads(materialization_path.read_text(encoding="utf-8"))
    configs = materialization.get("configs") or [{}]
    config = configs[0]
    patch = request.patch[0]
    knob_id = patch["knob_id"]
    unit = _parameter_unit(knob_id)
    h = sha256(materialization_path.read_bytes()).hexdigest()
    digest = f"sha256:{h}"
    runtime_report_path = (
        Path(workspace.directory) / "analysis" / "parameter_runtime_report.v1.json"
    )
    try:
        runtime_report = json.loads(runtime_report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        runtime_report = {
            "application_status": "unknown",
            "activation": {"status": "unknown", "consumers": []},
            "effective_initial": {"value": None, "unit": unit},
            "effective_final": {"value": None, "unit": unit},
        }
    tool_name = (
        "ECC-Floorplan"
        if knob_id.startswith("floorplan.")
        else "ECC-fixFanout"
        if knob_id == "synth.max_fanout"
        else "DREAMPlace"
    )
    receipt_path = Path(workspace.directory) / "analysis" / "parameter_application_receipt.v1.json"
    context = (
        _parameter_receipt_context(workspace, request, parent_flow_sha256)
        if parent_flow_sha256 is not None
        else {
            "run_id": request.candidate_id,
            "stage": request.target_step,
            "lattice_version": "ecos.optimization_lattice.v1",
        }
    )
    requested_value = patch["value"]
    if knob_id == "place.cell_padding_x":
        site_width = context.get("site_width_dbu")
        if type(site_width) is not int or site_width <= 0 or requested_value % site_width:
            raise RuntimeApiError("command_failed", "cell padding surface unit is unavailable")
        requested_value //= site_width
    return build_parameter_application_receipt(
        receipt_id=f"parameter-receipt-{request.candidate_id}",
        tool={"name": tool_name, "revision": "bound"},
        context=context,
        requested={"knob_id": knob_id, "value": requested_value, "unit": unit},
        materialization={
            "receipt_ref": "analysis/candidate_materialization.v1.json",
            "receipt_sha256": materialization.get("receipt_sha256", digest),
            "registry_sha256": materialization.get("registry_sha256", digest),
            "patch_sha256": materialization.get("patch_sha256", digest),
            "candidate_ref": candidate_root_ref,
            "workspace_ref": candidate_root_ref,
            "config_before_sha256": config.get("before_sha256", digest),
            "config_after_sha256": config.get("after_sha256", digest),
            "written_value": patch["value"],
            "unit": unit,
        },
        runtime_report=runtime_report,
        destination=receipt_path,
    )


def _parameter_receipt_context(workspace, request, parent_flow_sha256: str) -> dict[str, object]:
    root = Path(workspace.directory)
    origin = root / "origin"
    rtl_files = sorted(path for path in (origin / "rtl").glob("*") if path.is_file())
    sdc_files = sorted(origin.glob("*.sdc"))
    if not rtl_files or not sdc_files:
        raise RuntimeApiError("command_failed", "candidate input fingerprints are unavailable")
    try:
        parameters = json.loads((root / "home" / "parameters.json").read_text(encoding="utf-8"))
        pdk_root = Path(parameters["PDK Root"])
        tech_lef = pdk_root / "prtech" / "techLEF" / "N551P6M_ecos.lef"
        pdk_sha256 = f"sha256:{sha256(tech_lef.read_bytes()).hexdigest()}"
        lef_text = tech_lef.read_text(encoding="utf-8")
        units_match = re.search(r"DATABASE\s+MICRONS\s+(\d+)", lef_text, re.IGNORECASE)
        site_match = re.search(
            r"SITE\s+(?:core7|CoreSite)\b(?P<body>.*?)END\s+(?:core7|CoreSite)",
            lef_text,
            re.IGNORECASE | re.DOTALL,
        )
        size_match = re.search(
            r"SIZE\s+([0-9]+(?:\.[0-9]+)?)\s+BY",
            site_match.group("body") if site_match else "",
            re.IGNORECASE,
        )
        if not units_match or not size_match:
            raise ValueError("site width is unavailable")
        site_width_dbu = round(float(units_match.group(1)) * float(size_match.group(1)))
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeApiError("command_failed", "candidate PDK fingerprint is unavailable") from exc
    rtl_hashes = [f"sha256:{sha256(path.read_bytes()).hexdigest()}" for path in rtl_files]
    sdc_hashes = [f"sha256:{sha256(path.read_bytes()).hexdigest()}" for path in sdc_files]
    filelist = origin / "filelist.f"
    if not filelist.is_file():
        raise RuntimeApiError("command_failed", "candidate filelist fingerprint is unavailable")
    filelist_sha256 = f"sha256:{sha256(filelist.read_bytes()).hexdigest()}"
    design_sha256 = _stable_hash(
        {
            "rtl_sha256": rtl_hashes[0],
            "filelist_sha256": filelist_sha256,
            "sdc_sha256": sdc_hashes[0],
        }
    )
    knob_name = str(request.patch[0].get("knob_id"))
    unit = _parameter_unit(knob_name)
    context = {
        "run_id": request.candidate_id,
        "design_sha256": design_sha256,
        "stage": request.target_step,
        "backend": "ecc",
        "lattice_version": "ecos.optimization_lattice.v1",
        "rtl_sha256": (
            rtl_hashes[0] if len(rtl_hashes) == 1 else _stable_hash({"files": rtl_hashes})
        ),
        "filelist_sha256": filelist_sha256,
        "sdc_sha256": (
            sdc_hashes[0] if len(sdc_hashes) == 1 else _stable_hash({"files": sdc_hashes})
        ),
        "pdk_sha256": pdk_sha256,
        "parent_lineage_sha256": parent_flow_sha256,
        "seed": 0,
        "site_width_dbu": site_width_dbu,
        "tool_revision": "bound",
        "unit": unit,
    }
    return context


def _materialize_candidate_rerun(workspace, flow, request: CandidateRerunRequest) -> None:
    source_step = _candidate_source_step(flow, request.target_step)
    bind_candidate_input(
        workspace,
        flow,
        request.target_step,
        source_step,
        request.candidate_id,
    )
    materialize_candidate_config(
        workspace,
        request.target_step,
        request.patch,
        request.candidate_id,
    )


def _candidate_source_step(flow, target_step: str) -> str:
    steps = flow.workspace.flow.data.get("steps", [])
    for index, step in enumerate(steps):
        if step.get("name") == target_step and index:
            source = steps[index - 1].get("name")
            if isinstance(source, str):
                return source
    raise RuntimeApiError("invalid_request", f"candidate target has no predecessor: {target_step}")


def _reapply_candidate_input(workspace, flow, target_step: str) -> None:
    try:
        candidate_id = validate_candidate_step_contract(workspace, target_step)
        if candidate_id is not None:
            reapply_candidate_input_binding(workspace, flow, target_step)
    except ValueError as error:
        raise RuntimeApiError(
            "command_failed", f"candidate contract is invalid for {target_step}: {error}"
        ) from error


def _prepare_candidate_rerun(workspace, flow, steps: list) -> None:
    workspace_root = Path(workspace.directory).resolve()
    for step in steps:
        for directory in _candidate_step_artifact_dirs(step):
            _clear_candidate_artifact_dir(workspace_root, directory, step.name)
        record = flow.get_step(step.name, step.tool)
        if record is None:
            raise RuntimeApiError("command_failed", f"candidate flow state is missing: {step.name}")
        record.update({"state": "Unstart", "runtime": "", "peak memory (mb)": 0})
    flow.save()


def _candidate_step_artifact_dirs(step) -> tuple[Path, ...]:
    directories = []
    for field in ("output", "data", "feature", "analysis", "report", "log"):
        value = getattr(step, field, {})
        directory = value.get("dir") if isinstance(value, dict) else getattr(value, "dir", None)
        if directory:
            directories.append(Path(directory))
    return tuple(dict.fromkeys(directories))


def _clear_candidate_artifact_dir(workspace_root: Path, directory: Path, step_name: str) -> None:
    resolved = directory.resolve()
    if (
        resolved == workspace_root
        or not path_is_within(resolved, workspace_root)
        or directory.is_symlink()
    ):
        raise RuntimeApiError(
            "command_failed", f"candidate artifact escapes workspace: {step_name}"
        )
    if directory.exists():
        if not directory.is_dir():
            raise RuntimeApiError(
                "command_failed", f"candidate artifact is not a directory: {step_name}"
            )
        shutil.rmtree(directory)
    directory.mkdir(parents=True, exist_ok=True)


def _run_candidate_step(flow, step, *, observer) -> None:
    _init_db_engine_for_workspace_step(flow, step)
    state = flow.run_step(step, rerun=True, observer=observer)
    if _state_value(state) != "Success":
        raise RuntimeApiError(
            "command_failed",
            f"candidate rerun step {step.name} failed with state {_state_value(state)}",
        )
