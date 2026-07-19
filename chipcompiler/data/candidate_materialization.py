"""Controlled, replayable config overlays for isolated ECC candidate workspaces."""

from __future__ import annotations

import math
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
from .candidate_registry import (
    CandidateKnob,
    candidate_knob_registry,
    candidate_registry_digest,
    candidate_target_backend,
)

MATERIALIZATION_SCHEMA = "ecc.workspace.candidate_materialization.v1"
MATERIALIZATION_SCHEMA_VERSION = 1
MATERIALIZATION_FILENAME = "candidate_materialization.v1.json"


class CandidateMaterializationError(ValueError):
    """A candidate patch is outside the ECC-controlled parameter contract."""


def materialize_candidate_config(
    workspace: Any,
    target_step: str,
    patch: Any,
    candidate_id: str,
) -> dict[str, Any]:
    candidate_id = _validated_candidate_id(candidate_id)
    normalized_patch = _normalize_patch(patch)
    knobs = _resolve_knobs(target_step, normalized_patch, workspace)
    configs, config_paths, before_hashes = _load_configs(workspace, knobs)
    _apply_patch(configs, knobs, normalized_patch)
    after_hashes = _write_configs(workspace, configs, config_paths)
    receipt = _build_receipt(
        workspace,
        target_step,
        candidate_id,
        normalized_patch,
        knobs,
        config_paths,
        before_hashes,
        after_hashes,
    )
    write_json_atomic(_receipt_path(workspace), receipt)
    return receipt


def reapply_materialized_candidate_config(
    workspace: Any,
    target_step: str,
) -> dict[str, Any] | None:
    receipt_path = _receipt_path(workspace)
    if not receipt_path.exists():
        return None
    receipt = _read_receipt(receipt_path)
    if receipt["target"]["step"] != target_step:
        return None
    normalized_patch = receipt["patch"]
    knobs = _resolve_knobs(target_step, normalized_patch, workspace)
    configs, config_paths, before_hashes = _load_configs(workspace, knobs)
    _apply_patch(configs, knobs, normalized_patch)
    after_hashes = _write_configs(workspace, configs, config_paths)
    updated = _build_receipt(
        workspace,
        target_step,
        receipt["candidate_id"],
        normalized_patch,
        knobs,
        config_paths,
        before_hashes,
        after_hashes,
    )
    write_json_atomic(receipt_path, updated)
    return updated


def _normalize_patch(patch: Any) -> list[dict[str, Any]]:
    if not isinstance(patch, list) or not patch:
        raise CandidateMaterializationError("patch must be a non-empty list")
    normalized: list[dict[str, Any]] = []
    knob_ids: set[str] = set()
    for item in patch:
        if not isinstance(item, dict) or set(item) != {"knob_id", "value"}:
            raise CandidateMaterializationError(
                "each patch item must contain only knob_id and value"
            )
        knob_id = item["knob_id"]
        if not isinstance(knob_id, str) or not knob_id:
            raise CandidateMaterializationError("knob_id must be a non-empty string")
        if knob_id in knob_ids:
            raise CandidateMaterializationError(f"duplicate knob_id: {knob_id}")
        try:
            canonical_json_bytes(item["value"])
        except (TypeError, ValueError) as error:
            raise CandidateMaterializationError(
                f"value for {knob_id} is not canonical JSON"
            ) from error
        knob_ids.add(knob_id)
        normalized.append({"knob_id": knob_id, "value": item["value"]})
    return sorted(normalized, key=lambda item: item["knob_id"])


def _resolve_knobs(
    target_step: str,
    patch: list[dict[str, Any]],
    workspace: Any,
) -> list[CandidateKnob]:
    _require_candidate_target_backend(workspace, target_step)
    registry = {knob.knob_id: knob for knob in candidate_knob_registry()}
    knobs: list[CandidateKnob] = []
    for item in patch:
        knob = registry.get(item["knob_id"])
        if knob is None:
            raise CandidateMaterializationError(f"unsupported candidate knob: {item['knob_id']}")
        if knob.target_step != target_step:
            raise CandidateMaterializationError(
                f"knob {knob.knob_id} is not valid for target step {target_step}"
            )
        _validate_value(knob, item["value"], workspace)
        knobs.append(knob)
    return knobs


def _require_candidate_target_backend(workspace: Any, target_step: str) -> None:
    backend = candidate_target_backend(workspace, target_step)
    if backend["available"] is not True:
        reason = backend.get("reason", "backend is unavailable")
        raise CandidateMaterializationError(
            f"candidate target {target_step} is not candidate-capable: {reason}"
        )


def _validate_value(knob: CandidateKnob, value: Any, workspace: Any) -> None:
    if knob.value_type == "bool":
        if type(value) is not bool:
            raise CandidateMaterializationError(f"{knob.knob_id} must be a boolean")
        return
    if knob.value_type == "number":
        _validate_number(knob, value)
        return
    if knob.value_type == "number_pair":
        _validate_number_pair(knob, value)
        return
    if knob.value_type == "uint":
        _validate_uint(knob, value)
        return
    if knob.value_type == "uint_list":
        _validate_uint_list(knob, value)
        return
    if knob.value_type == "string_list":
        _validate_string_list(knob, value, workspace)
        return
    if knob.value_type == "string":
        _validate_string(knob, value)
        return
    if knob.value_type == "pdk_string":
        _validate_pdk_string(knob, value, workspace)
        return
    if knob.value_type == "bool_int":
        if type(value) is not bool:
            raise CandidateMaterializationError(f"{knob.knob_id} must be a boolean")
        return
    raise CandidateMaterializationError(f"unsupported value type for {knob.knob_id}")


def _validate_number(knob: CandidateKnob, value: Any) -> None:
    if type(value) not in {int, float} or not math.isfinite(value):
        raise CandidateMaterializationError(f"{knob.knob_id} must be a finite number")
    if knob.minimum is not None and value < knob.minimum:
        raise CandidateMaterializationError(f"{knob.knob_id} must be >= {knob.minimum}")
    if knob.maximum is not None and value > knob.maximum:
        raise CandidateMaterializationError(f"{knob.knob_id} must be <= {knob.maximum}")


def _validate_number_pair(knob: CandidateKnob, value: Any) -> None:
    if not isinstance(value, list) or len(value) != 2:
        raise CandidateMaterializationError(f"{knob.knob_id} must be a two-value list")
    for item in value:
        _validate_number(knob, item)


def _validate_uint(knob: CandidateKnob, value: Any) -> None:
    if type(value) is not int:
        raise CandidateMaterializationError(f"{knob.knob_id} must be an integer")
    if knob.minimum is not None and value < knob.minimum:
        raise CandidateMaterializationError(f"{knob.knob_id} must be >= {knob.minimum}")


def _validate_uint_list(knob: CandidateKnob, value: Any) -> None:
    if not isinstance(value, list) or not value:
        raise CandidateMaterializationError(f"{knob.knob_id} must be a non-empty integer list")
    if any(type(item) is not int or item < (knob.minimum or 0) for item in value):
        raise CandidateMaterializationError(f"{knob.knob_id} contains an invalid layer")
    if len(set(value)) != len(value):
        raise CandidateMaterializationError(f"{knob.knob_id} must not contain duplicate values")


def _validate_string_list(knob: CandidateKnob, value: Any, workspace: Any) -> None:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item for item in value)
    ):
        raise CandidateMaterializationError(f"{knob.knob_id} must be a non-empty string list")
    if len(set(value)) != len(value):
        raise CandidateMaterializationError(f"{knob.knob_id} must not contain duplicate values")
    allowed = set(getattr(getattr(workspace, "pdk", None), knob.pdk_attribute or "", []) or [])
    if not allowed or not set(value).issubset(allowed):
        raise CandidateMaterializationError(
            f"{knob.knob_id} must be a subset of the workspace PDK cells"
        )


def _validate_string(knob: CandidateKnob, value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise CandidateMaterializationError(f"{knob.knob_id} must be a non-empty string")


def _validate_pdk_string(knob: CandidateKnob, value: Any, workspace: Any) -> None:
    _validate_string(knob, value)
    allowed = set(getattr(getattr(workspace, "pdk", None), knob.pdk_attribute or "", []) or [])
    if value not in allowed:
        raise CandidateMaterializationError(f"{knob.knob_id} must be a workspace PDK cell")


def _load_configs(
    workspace: Any,
    knobs: list[CandidateKnob],
) -> tuple[dict[str, dict[str, Any]], dict[str, Path], dict[str, str]]:
    configs: dict[str, dict[str, Any]] = {}
    config_paths: dict[str, Path] = {}
    before_hashes: dict[str, str] = {}
    for knob in knobs:
        if knob.config_key in configs:
            continue
        path = _config_path(workspace, knob.config_key)
        config_paths[knob.config_key] = path
        try:
            configs[knob.config_key] = read_json_object(path, "candidate base config")
        except ValueError as error:
            raise CandidateMaterializationError(str(error)) from error
        before = sha256_path(path)
        if before is None:
            raise CandidateMaterializationError(f"missing candidate base config: {path}")
        before_hashes[knob.config_key] = before
    return configs, config_paths, before_hashes


def _config_path(workspace: Any, config_key: str) -> Path:
    if config_key == "parameters":
        parameter_path = getattr(getattr(workspace, "parameters", None), "path", None)
        if not parameter_path:
            raise CandidateMaterializationError("workspace has no parameters path")
        path = Path(parameter_path)
    else:
        config = getattr(workspace, "config", {}) or {}
        path = config.get(config_key)
    if not path:
        raise CandidateMaterializationError(f"workspace has no config for {config_key}")
    try:
        workspace_relative_ref(workspace.directory, Path(path))
    except ValueError as error:
        raise CandidateMaterializationError(str(error)) from error
    return Path(path).expanduser().resolve()


def _apply_patch(
    configs: dict[str, dict[str, Any]],
    knobs: list[CandidateKnob],
    patch: list[dict[str, Any]],
) -> None:
    values = {item["knob_id"]: item["value"] for item in patch}
    for knob in knobs:
        current = configs[knob.config_key]
        for key in knob.json_path[:-1]:
            child = current.get(key)
            if not isinstance(child, dict):
                child = {}
                current[key] = child
            current = child
        value = values[knob.knob_id]
        current[knob.json_path[-1]] = int(value) if knob.value_type == "bool_int" else value


def _write_configs(
    workspace: Any,
    configs: dict[str, dict[str, Any]],
    config_paths: dict[str, Path],
) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for config_key, config in configs.items():
        path = config_paths[config_key]
        write_json_atomic(path, config)
        digest = sha256_path(path)
        if digest is None:
            raise CandidateMaterializationError(f"failed to write candidate config: {path}")
        hashes[config_key] = digest
        if config_key == "parameters" and hasattr(workspace, "parameters"):
            workspace.parameters.data = config
    return hashes


def _build_receipt(
    workspace: Any,
    target_step: str,
    candidate_id: str,
    patch: list[dict[str, Any]],
    knobs: list[CandidateKnob],
    config_paths: dict[str, Path],
    before_hashes: dict[str, str],
    after_hashes: dict[str, str],
) -> dict[str, Any]:
    configs = [
        {
            "config_key": key,
            "ref": workspace_relative_ref(workspace.directory, config_paths[key]),
            "before_sha256": before_hashes[key],
            "after_sha256": after_hashes[key],
        }
        for key in sorted(config_paths)
    ]
    receipt = {
        "schema": MATERIALIZATION_SCHEMA,
        "schema_version": MATERIALIZATION_SCHEMA_VERSION,
        "candidate_id": candidate_id,
        "target_step": target_step,
        "target": {"step": target_step},
        "registry_sha256": _registry_digest(),
        "patch": patch,
        "patch_sha256": sha256_bytes(canonical_json_bytes(patch)),
        "configs": configs,
    }
    receipt["receipt_sha256"] = _receipt_digest(receipt)
    return receipt


def _receipt_path(workspace: Any) -> Path:
    return workspace_analysis_path(workspace.directory, MATERIALIZATION_FILENAME)


def _registry_digest() -> str:
    return candidate_registry_digest()


def materialized_candidate_id(workspace: Any, target_step: str) -> str | None:
    return validate_materialized_candidate_config(workspace, target_step)


def validate_materialized_candidate_config(workspace: Any, target_step: str) -> str | None:
    """Verify the materialized config still matches its immutable receipt."""
    receipt_path = _receipt_path(workspace)
    if not receipt_path.exists():
        return None
    receipt = _read_receipt(receipt_path)
    if receipt["target_step"] != target_step:
        return None
    _require_candidate_target_backend(workspace, target_step)
    _verify_materialized_config_hashes(workspace, receipt["configs"])
    return receipt["candidate_id"]


def _read_receipt(path: Path) -> dict[str, Any]:
    try:
        receipt = read_json_object(path, "candidate materialization receipt")
    except ValueError as error:
        raise CandidateMaterializationError(str(error)) from error
    if receipt.get("schema") != MATERIALIZATION_SCHEMA:
        raise CandidateMaterializationError("candidate materialization receipt schema is invalid")
    if receipt.get("schema_version") != MATERIALIZATION_SCHEMA_VERSION:
        raise CandidateMaterializationError(
            "candidate materialization receipt schema version is invalid"
        )
    try:
        candidate_id = validate_candidate_id(receipt.get("candidate_id"))
    except ValueError as error:
        raise CandidateMaterializationError(str(error)) from error
    target = receipt.get("target")
    patch = receipt.get("patch")
    if not isinstance(target, dict) or not isinstance(target.get("step"), str):
        raise CandidateMaterializationError("candidate materialization receipt target is invalid")
    if receipt.get("target_step") != target["step"]:
        raise CandidateMaterializationError(
            "candidate materialization receipt target step is invalid"
        )
    normalized_patch = _normalize_patch(patch)
    if normalized_patch != patch:
        raise CandidateMaterializationError(
            "candidate materialization receipt patch is not canonical"
        )
    if receipt.get("patch_sha256") != sha256_bytes(canonical_json_bytes(patch)):
        raise CandidateMaterializationError(
            "candidate materialization receipt patch hash is invalid"
        )
    if receipt.get("registry_sha256") != _registry_digest():
        raise CandidateMaterializationError("candidate materialization receipt registry is stale")
    if receipt.get("receipt_sha256") != _receipt_digest(receipt):
        raise CandidateMaterializationError("candidate materialization receipt hash is invalid")
    _validate_config_receipts(receipt.get("configs"))
    receipt["candidate_id"] = candidate_id
    return receipt


def _validate_config_receipts(configs: Any) -> None:
    if not isinstance(configs, list) or not configs:
        raise CandidateMaterializationError("candidate materialization receipt configs are invalid")
    for entry in configs:
        if not isinstance(entry, dict) or set(entry) != {
            "config_key",
            "ref",
            "before_sha256",
            "after_sha256",
        }:
            raise CandidateMaterializationError(
                "candidate materialization config receipt is invalid"
            )
        if not isinstance(entry["config_key"], str) or not entry["config_key"]:
            raise CandidateMaterializationError("candidate materialization config key is invalid")
        if not isinstance(entry["ref"], str) or not entry["ref"]:
            raise CandidateMaterializationError("candidate materialization config ref is invalid")
        if not all(
            isinstance(entry[key], str) and entry[key].startswith("sha256:")
            for key in ("before_sha256", "after_sha256")
        ):
            raise CandidateMaterializationError("candidate materialization config hash is invalid")


def _verify_materialized_config_hashes(workspace: Any, configs: list[dict[str, Any]]) -> None:
    root = Path(workspace.directory).expanduser().resolve()
    for entry in configs:
        path = (root / entry["ref"]).resolve()
        try:
            relative = workspace_relative_ref(root, path)
        except ValueError as error:
            raise CandidateMaterializationError(
                "candidate materialization config ref escapes workspace"
            ) from error
        if relative != entry["ref"] or sha256_path(path) != entry["after_sha256"]:
            raise CandidateMaterializationError("materialized candidate config drift")


def _receipt_digest(receipt: dict[str, Any]) -> str:
    payload = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    return sha256_bytes(canonical_json_bytes(payload))


def _validated_candidate_id(candidate_id: Any) -> str:
    try:
        return validate_candidate_id(candidate_id)
    except ValueError as error:
        raise CandidateMaterializationError(str(error)) from error
