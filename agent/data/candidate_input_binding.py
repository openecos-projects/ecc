"""Controlled input bindings for isolated ECC candidate workspace steps."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .candidate_artifacts import (
    canonical_json_bytes,
    read_json_object,
    sha256_bytes,
    sha256_path,
    validate_candidate_id,
    workspace_analysis_path,
    workspace_relative_ref,
    write_json_atomic,
)

INPUT_BINDING_SCHEMA = "ecc.workspace.candidate_input_binding.v1"
INPUT_BINDING_SCHEMA_VERSION = 1
INPUT_BINDING_FILENAME = "candidate_input_binding.v1.json"
CANONICAL_INPUT_EDGES = frozenset(
    {
        ("Floorplan", "initial"),
        ("fixFanout", "Floorplan"),
        ("place", "fixFanout"),
        ("CTS", "place"),
        ("legalization", "CTS"),
        ("route", "legalization"),
        ("place", "CTS"),
        ("legalization", "place"),
        ("CTS", "legalization"),
    }
)


class CandidateInputBindingError(ValueError):
    """A candidate input binding is outside the declared physical-flow edges."""


def bind_candidate_input(
    workspace: Any,
    engine_flow: Any,
    target_step: str,
    source_step: str,
    candidate_id: str,
) -> dict[str, Any]:
    candidate_id = _validated_candidate_id(candidate_id)
    _validate_edge(target_step, source_step)
    target = _step_or_error(engine_flow, target_step, "target")
    inputs = _source_inputs(workspace, engine_flow, source_step)
    receipt = _build_receipt(workspace, target_step, source_step, candidate_id, inputs)
    write_json_atomic(_receipt_path(workspace), receipt)
    _set_target_inputs(target, inputs)
    return receipt


def reapply_candidate_input_binding(
    workspace: Any,
    engine_flow: Any,
    target_step: str,
) -> dict[str, Any] | None:
    receipt_path = _receipt_path(workspace)
    if not receipt_path.exists():
        return None
    receipt = _read_receipt(receipt_path)
    if receipt["target_step"] != target_step:
        return None
    source_step = receipt["source"]["step"]
    _validate_edge(target_step, source_step)
    target = _step_or_error(engine_flow, target_step, "target")
    inputs = _source_inputs(workspace, engine_flow, source_step)
    actual = _build_receipt(
        workspace,
        target_step,
        source_step,
        receipt["candidate_id"],
        inputs,
    )
    if receipt != actual:
        raise CandidateInputBindingError("candidate input binding source artifacts are stale")
    _set_target_inputs(target, inputs)
    return actual


def _validate_edge(target_step: str, source_step: str) -> None:
    if (target_step, source_step) not in CANONICAL_INPUT_EDGES:
        raise CandidateInputBindingError(
            f"unsupported candidate input edge: {source_step} -> {target_step}"
        )


def _step_or_error(engine_flow: Any, step_name: str, role: str) -> Any:
    step = engine_flow.get_workspace_step(step_name)
    if step is None:
        raise CandidateInputBindingError(f"candidate {role} step is unavailable: {step_name}")
    return step


def _source_inputs(workspace: Any, engine_flow: Any, source_step: str) -> dict[str, Path | None]:
    if source_step == "initial":
        design = getattr(workspace, "design", None)
        source = {
            "def": getattr(design, "origin_def", None),
            "verilog": getattr(design, "origin_verilog", None),
            "db": None,
        }
    else:
        source = _step_or_error(engine_flow, source_step, "source").output
    inputs = {key: _path_or_none(_group_value(source, key)) for key in ("def", "verilog", "db")}
    _validate_source_inputs(source_step, inputs)
    return inputs


def _group_value(group: Any, key: str) -> Any:
    if isinstance(group, dict):
        return group.get(key)
    return getattr(group, "def_" if key == "def" else key, None)


def _set_target_inputs(target: Any, inputs: dict[str, Path | None]) -> None:
    if isinstance(target.input, dict):
        target.input = dict(inputs)
        return
    for key, value in inputs.items():
        setattr(target.input, "def_" if key == "def" else key, value)


def _path_or_none(value: Any) -> Path | None:
    if not value:
        return None
    return Path(value).expanduser().resolve()


def _validate_source_inputs(source_step: str, inputs: dict[str, Path | None]) -> None:
    def_hash = sha256_path(inputs["def"]) if inputs["def"] else None
    verilog_hash = sha256_path(inputs["verilog"]) if inputs["verilog"] else None
    if source_step != "initial" and def_hash is None:
        raise CandidateInputBindingError(f"candidate source {source_step} has no DEF checkpoint")
    if def_hash is None and verilog_hash is None:
        raise CandidateInputBindingError(f"candidate source {source_step} has no design checkpoint")


def _build_receipt(
    workspace: Any,
    target_step: str,
    source_step: str,
    candidate_id: str,
    inputs: dict[str, Path | None],
) -> dict[str, Any]:
    receipt = {
        "schema": INPUT_BINDING_SCHEMA,
        "schema_version": INPUT_BINDING_SCHEMA_VERSION,
        "candidate_id": candidate_id,
        "target_step": target_step,
        "target": {"step": target_step},
        "source": {"step": source_step},
        "inputs": _input_receipts(workspace, inputs),
    }
    receipt["receipt_sha256"] = _receipt_digest(receipt)
    return receipt


def _input_receipts(
    workspace: Any,
    inputs: dict[str, Path | None],
) -> dict[str, dict[str, str] | None]:
    receipts: dict[str, dict[str, str] | None] = {}
    for name, path in inputs.items():
        if path is None:
            receipts[name] = None
            continue
        digest = sha256_path(path)
        if digest is None:
            receipts[name] = None
            continue
        try:
            ref = workspace_relative_ref(workspace.directory, path)
        except ValueError as error:
            raise CandidateInputBindingError(str(error)) from error
        receipts[name] = {"ref": ref, "sha256": digest}
    return receipts


def _receipt_path(workspace: Any) -> Path:
    return workspace_analysis_path(workspace.directory, INPUT_BINDING_FILENAME)


def input_binding_candidate_id(workspace: Any, target_step: str) -> str | None:
    receipt_path = _receipt_path(workspace)
    if not receipt_path.exists():
        return None
    receipt = _read_receipt(receipt_path)
    if receipt["target_step"] != target_step:
        return None
    return receipt["candidate_id"]


def _read_receipt(path: Path) -> dict[str, Any]:
    try:
        receipt = read_json_object(path, "candidate input binding receipt")
    except ValueError as error:
        raise CandidateInputBindingError(str(error)) from error
    if receipt.get("schema") != INPUT_BINDING_SCHEMA:
        raise CandidateInputBindingError("candidate input binding receipt schema is invalid")
    if receipt.get("schema_version") != INPUT_BINDING_SCHEMA_VERSION:
        raise CandidateInputBindingError(
            "candidate input binding receipt schema version is invalid"
        )
    try:
        candidate_id = validate_candidate_id(receipt.get("candidate_id"))
    except ValueError as error:
        raise CandidateInputBindingError(str(error)) from error
    target = receipt.get("target")
    source = receipt.get("source")
    inputs = receipt.get("inputs")
    if not isinstance(target, dict) or not isinstance(target.get("step"), str):
        raise CandidateInputBindingError("candidate input binding target is invalid")
    if receipt.get("target_step") != target["step"]:
        raise CandidateInputBindingError("candidate input binding target step is invalid")
    if not isinstance(source, dict) or not isinstance(source.get("step"), str):
        raise CandidateInputBindingError("candidate input binding source is invalid")
    if not isinstance(inputs, dict) or set(inputs) != {"def", "verilog", "db"}:
        raise CandidateInputBindingError("candidate input binding inputs are invalid")
    expected = _receipt_digest(receipt)
    if receipt.get("receipt_sha256") != expected:
        raise CandidateInputBindingError("candidate input binding receipt hash is invalid")
    receipt["candidate_id"] = candidate_id
    return receipt


def _receipt_digest(receipt: dict[str, Any]) -> str:
    payload = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    return sha256_bytes(canonical_json_bytes(payload))


def _validated_candidate_id(candidate_id: Any) -> str:
    try:
        return validate_candidate_id(candidate_id)
    except ValueError as error:
        raise CandidateInputBindingError(str(error)) from error
