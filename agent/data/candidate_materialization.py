"""Controlled, replayable config overlays for isolated ECC candidate workspaces."""

import math
import re
import shutil
from copy import deepcopy
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
    normalized_patch, knobs = _prepare_patch(workspace, target_step, patch)
    configs, config_paths, before_hashes = _load_configs(workspace, knobs)
    before_configs = deepcopy(configs)
    _apply_patch(configs, knobs, normalized_patch)
    if configs == before_configs:
        raise CandidateMaterializationError("candidate materialization patch did not change config")
    snapshots = _write_config_snapshots(
        workspace,
        candidate_id,
        config_paths,
        configs,
    )
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
        snapshots,
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
    if receipt["target_step"] != target_step:
        return None
    _validate_receipt_binding(workspace, target_step, receipt)
    _verify_config_snapshot_hashes(workspace, receipt["snapshots"])
    snapshots = {entry["config_key"]: entry for entry in receipt["snapshots"]}
    for entry in receipt["configs"]:
        config_key = entry["config_key"]
        after_path = Path(workspace.directory) / snapshots[config_key]["after_ref"]
        config_path = _config_path(workspace, config_key)
        shutil.copyfile(after_path, config_path)
        if config_key == "parameters" and hasattr(workspace, "parameters"):
            try:
                workspace.parameters.data = read_json_object(config_path, "candidate parameters")
            except ValueError as error:
                raise CandidateMaterializationError(str(error)) from error
    _verify_materialized_config_hashes(workspace, receipt["configs"])
    return receipt


def _normalize_patch(patch: Any) -> list[dict[str, Any]]:
    if not isinstance(patch, list) or not patch:
        raise CandidateMaterializationError("patch must be a non-empty list")
    if len(patch) != 1:
        raise CandidateMaterializationError("patch must contain exactly one knob")
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


def candidate_written_patch(
    workspace: Any,
    target_step: str,
    patch: Any,
) -> list[dict[str, Any]]:
    """Validate a surface patch and return the values written by L1."""
    return _prepare_patch(workspace, target_step, patch)[0]


def _prepare_patch(
    workspace: Any,
    target_step: str,
    patch: Any,
) -> tuple[list[dict[str, Any]], list[CandidateKnob]]:
    normalized = _normalize_patch(patch)
    knobs = _resolve_knobs(target_step, normalized, workspace)
    written = [dict(item) for item in normalized]
    if written[0]["knob_id"] == "place.cell_padding_x":
        written[0]["value"] *= _site_width_dbu(workspace)
    return written, knobs


def _site_width_dbu(workspace: Any) -> int:
    pdk = getattr(workspace, "pdk", None)
    tech = getattr(pdk, "tech", None)
    site_name = getattr(pdk, "site_core", None)
    if not tech or not isinstance(site_name, str) or not site_name:
        raise CandidateMaterializationError("workspace placement site is unavailable")
    try:
        text = Path(tech).read_text(encoding="utf-8")
    except OSError as error:
        raise CandidateMaterializationError("workspace tech LEF is unavailable") from error
    units = re.search(r"DATABASE\s+MICRONS\s+(\d+)", text, re.IGNORECASE)
    site = re.search(
        rf"SITE\s+{re.escape(site_name)}\b(?P<body>.*?)END\s+{re.escape(site_name)}\b",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    size = re.search(
        r"SIZE\s+([0-9]+(?:\.[0-9]+)?)\s+BY",
        site.group("body") if site else "",
        re.IGNORECASE,
    )
    width = round(float(units.group(1)) * float(size.group(1))) if units and size else 0
    if width <= 0:
        raise CandidateMaterializationError("workspace placement site width is unavailable")
    return width


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


def _load_parameters_config(path: Path) -> dict:
    """Load the canonical workspace parameters regardless of on-disk format."""
    from chipcompiler.data.parameter import load_parameter

    try:
        data = dict(load_parameter(path).data)
    except Exception as exc:
        raise ValueError(f"invalid candidate base config: {path}: {exc}") from exc
    if not data:
        # load_parameter returns {} when neither the canonical TOML nor a
        # legacy JSON exists; hashing {} would sail through the missing-base
        # guard and let the applied patch recreate a config holding only the
        # patch keys, dropping the workspace identity and other parameters.
        raise ValueError(f"missing candidate base config: {path}")
    return data


def _write_parameters_config(workspace: Any, path: Path, config: dict) -> Path:
    """Persist candidate parameters through the canonical save boundary
    (home/params.toml), keeping the workspace's [flow] section.

    Returns the path that was actually written: when the workspace still
    references a legacy parameters.json path, the save lands on the
    canonical home/params.toml target, and receipts must hash THAT file.
    """
    from chipcompiler.data.parameter import Parameters, save_parameter
    from chipcompiler.data.workspace_config import workspace_config_path

    parameters = Parameters()
    parameters.path = path
    parameters.data = dict(config)
    if hasattr(workspace, "parameters"):
        existing_flow = getattr(workspace.parameters, "data", {}).get("_flow")
        if existing_flow:
            parameters.data["_flow"] = existing_flow
    if not save_parameter(parameters):
        raise ValueError(f"failed to write candidate config: {path}")
    return workspace_config_path(workspace.directory)


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
            if knob.config_key == "parameters":
                configs[knob.config_key] = _load_parameters_config(path)
            else:
                configs[knob.config_key] = read_json_object(path, "candidate base config")
        except ValueError as error:
            raise CandidateMaterializationError(str(error)) from error
        before = sha256_bytes(canonical_json_bytes(configs[knob.config_key]))
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
        if config_key == "parameters":
            path = _write_parameters_config(workspace, path, config)
            config_paths[config_key] = path
        else:
            write_json_atomic(path, config)
        digest = sha256_path(path)
        if digest is None:
            raise CandidateMaterializationError(f"failed to write candidate config: {path}")
        hashes[config_key] = digest
        if config_key == "parameters" and hasattr(workspace, "parameters"):
            # Keep the flow target attached to the live parameters: the
            # candidate overlay never resets [flow].
            merged = dict(config)
            existing_flow = getattr(workspace.parameters, "data", {}).get("_flow")
            if existing_flow and "_flow" not in merged:
                merged["_flow"] = existing_flow
            workspace.parameters.data = merged
    return hashes


def _write_config_snapshots(
    workspace: Any,
    candidate_id: str,
    config_paths: dict[str, Path],
    after_configs: dict[str, dict[str, Any]],
) -> list[dict[str, str]]:
    snapshots: list[dict[str, str]] = []
    for config_key in sorted(after_configs):
        before_path = _snapshot_path(workspace, candidate_id, config_key, "before")
        after_path = _snapshot_path(workspace, candidate_id, config_key, "after")
        before_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(config_paths[config_key], before_path)
        write_json_atomic(after_path, after_configs[config_key])
        before_sha256 = sha256_path(before_path)
        after_sha256 = sha256_path(after_path)
        if before_sha256 is None or after_sha256 is None:
            raise CandidateMaterializationError("failed to write candidate config snapshots")
        snapshots.append(
            {
                "config_key": config_key,
                "before_ref": workspace_relative_ref(workspace.directory, before_path),
                "before_sha256": before_sha256,
                "after_ref": workspace_relative_ref(workspace.directory, after_path),
                "after_sha256": after_sha256,
            }
        )
    return snapshots


def _snapshot_path(workspace: Any, candidate_id: str, config_key: str, state: str) -> Path:
    return workspace_analysis_path(
        workspace.directory,
        f"candidate_config_snapshots.v1/{candidate_id}/{config_key}.{state}.json",
    )


def _build_receipt(
    workspace: Any,
    target_step: str,
    candidate_id: str,
    patch: list[dict[str, Any]],
    knobs: list[CandidateKnob],
    config_paths: dict[str, Path],
    before_hashes: dict[str, str],
    after_hashes: dict[str, str],
    snapshots: list[dict[str, str]],
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
        "snapshots": snapshots,
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
    receipt = validate_candidate_materialization_receipt(workspace, target_step)
    return receipt["candidate_id"] if receipt is not None else None


def validate_candidate_materialization_receipt(
    workspace: Any,
    target_step: str,
) -> dict[str, Any] | None:
    """Read and strictly bind an immutable L1 receipt to the current workspace."""
    receipt_path = _receipt_path(workspace)
    if not receipt_path.exists():
        return None
    receipt = _read_receipt(receipt_path)
    _validate_receipt_binding(workspace, target_step, receipt)
    _verify_materialized_config_hashes(workspace, receipt["configs"])
    _verify_config_snapshot_hashes(workspace, receipt["snapshots"])
    return receipt


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
    _validate_snapshot_receipts(receipt.get("snapshots"))
    receipt["candidate_id"] = candidate_id
    return receipt


def _validate_receipt_binding(
    workspace: Any,
    target_step: str,
    receipt: dict[str, Any],
) -> None:
    if receipt["target_step"] != target_step:
        raise CandidateMaterializationError("candidate materialization target step mismatch")
    knobs = _resolve_knobs(target_step, receipt["patch"], workspace)
    configs = _entries_by_config_key(receipt["configs"], "config")
    snapshots = _entries_by_config_key(receipt["snapshots"], "snapshot")
    expected_keys = {knob.config_key for knob in knobs}
    if set(configs) != expected_keys or set(snapshots) != expected_keys:
        raise CandidateMaterializationError(
            "candidate materialization configs and snapshots are incomplete"
        )
    for config_key in expected_keys:
        _validate_bound_config(workspace, receipt["candidate_id"], config_key, configs, snapshots)


def _entries_by_config_key(entries: list[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    keyed = {entry["config_key"]: entry for entry in entries}
    if len(keyed) != len(entries):
        raise CandidateMaterializationError(
            f"candidate materialization {label} keys are duplicated"
        )
    return keyed


def _validate_bound_config(
    workspace: Any,
    candidate_id: str,
    config_key: str,
    configs: dict[str, dict[str, Any]],
    snapshots: dict[str, dict[str, Any]],
) -> None:
    config = configs[config_key]
    snapshot = snapshots[config_key]
    expected_ref = workspace_relative_ref(workspace.directory, _config_path(workspace, config_key))
    if config["ref"] != expected_ref:
        raise CandidateMaterializationError(
            "candidate materialization config ref does not match registry"
        )
    if any(
        config[f"{state}_sha256"] != snapshot[f"{state}_sha256"] for state in ("before", "after")
    ):
        raise CandidateMaterializationError(
            "candidate materialization config snapshot hashes do not match"
        )
    for state in ("before", "after"):
        expected = workspace_relative_ref(
            workspace.directory,
            _snapshot_path(workspace, candidate_id, config_key, state),
        )
        if snapshot[f"{state}_ref"] != expected:
            raise CandidateMaterializationError(
                "candidate materialization snapshot ref does not match candidate"
            )


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
        if not all(_is_sha256(entry[key]) for key in ("before_sha256", "after_sha256")):
            raise CandidateMaterializationError("candidate materialization config hash is invalid")
        if entry["before_sha256"] == entry["after_sha256"]:
            raise CandidateMaterializationError(
                "candidate materialization patch did not change config"
            )


def _validate_snapshot_receipts(snapshots: Any) -> None:
    if not isinstance(snapshots, list) or not snapshots:
        raise CandidateMaterializationError("candidate config snapshots are invalid")
    for entry in snapshots:
        if not isinstance(entry, dict) or set(entry) != {
            "config_key",
            "before_ref",
            "before_sha256",
            "after_ref",
            "after_sha256",
        }:
            raise CandidateMaterializationError("candidate config snapshot receipt is invalid")
        if not isinstance(entry["config_key"], str) or not entry["config_key"]:
            raise CandidateMaterializationError("candidate config snapshot key is invalid")
        if not all(
            isinstance(entry[key], str) and entry[key] for key in ("before_ref", "after_ref")
        ):
            raise CandidateMaterializationError("candidate config snapshot ref is invalid")
        if not all(_is_sha256(entry[key]) for key in ("before_sha256", "after_sha256")):
            raise CandidateMaterializationError("candidate config snapshot hash is invalid")
        if entry["before_sha256"] == entry["after_sha256"]:
            raise CandidateMaterializationError("candidate config snapshot did not change config")


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


def _verify_config_snapshot_hashes(workspace: Any, snapshots: list[dict[str, str]]) -> None:
    root = Path(workspace.directory).expanduser().resolve()
    for entry in snapshots:
        for state in ("before", "after"):
            ref = entry[f"{state}_ref"]
            path = (root / ref).resolve()
            try:
                relative = workspace_relative_ref(root, path)
            except ValueError as error:
                raise CandidateMaterializationError(
                    "candidate config snapshot ref escapes workspace"
                ) from error
            if relative != ref or sha256_path(path) != entry[f"{state}_sha256"]:
                raise CandidateMaterializationError("candidate config snapshot drift")


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _receipt_digest(receipt: dict[str, Any]) -> str:
    payload = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    return sha256_bytes(canonical_json_bytes(payload))


def _validated_candidate_id(candidate_id: Any) -> str:
    try:
        return validate_candidate_id(candidate_id)
    except ValueError as error:
        raise CandidateMaterializationError(str(error)) from error
