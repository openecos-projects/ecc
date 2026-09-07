"""Explicit, persisted floorplan mode overrides for isolated Agent candidates."""

import math
import re
from pathlib import Path

from chipcompiler.runtime.workspace_api import RuntimeApiError

from .data.candidate_artifacts import (
    canonical_json_bytes,
    read_json_object,
    sha256_bytes,
    sha256_path,
    write_json_atomic,
)

FLOORPLAN_MODE_REF = "analysis/floorplan_mode.v1.json"
_SCHEMA = "ecc.agent.floorplan_mode.v1"
_MODES = ("die_util", "die_size")


def validate_floorplan_mode_request(request) -> None:
    mode = request.floorplan_mode
    if mode is not None and (mode not in _MODES or request.target_step != "Floorplan"):
        raise RuntimeApiError(
            "invalid_request", "floorplan_mode must be die_util or die_size at Floorplan"
        )


def _local_path(workspace, path) -> Path:
    root = Path(workspace.directory).absolute()
    path = Path(path).absolute()
    if root.resolve() != root or path.resolve() != path or not path.is_relative_to(root):
        raise ValueError("floorplan mode path is unsafe")
    return path


def _isolated_root(workspace) -> Path:
    root = _local_path(workspace, workspace.directory)
    if root.parent.name != "candidates" or root.parent.parent.name != ".agent":
        raise ValueError("floorplan mode requires an isolated candidate workspace")
    return root


def _positive_number(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def _validate_size(size) -> None:
    if (
        not isinstance(size, dict)
        or set(size) != {"width_micron", "height_micron"}
        or not all(_positive_number(value) for value in size.values())
    ):
        raise ValueError("die_size requires finite positive width and height")


def read_floorplan_mode(workspace, *, inherited=False) -> dict | None:
    path = _local_path(workspace, Path(workspace.directory) / FLOORPLAN_MODE_REF)
    if not path.exists():
        return None
    root = _isolated_root(workspace)
    receipt = read_json_object(path, "floorplan mode receipt")
    payload = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    if receipt.get("receipt_sha256") != sha256_bytes(canonical_json_bytes(payload)):
        raise ValueError("floorplan mode receipt hash is invalid")
    if (
        receipt.get("schema") != _SCHEMA
        or receipt.get("mode") not in _MODES
        or receipt.get("previous_mode") not in _MODES
        or (not inherited and receipt.get("candidate_id") != root.name)
        or type(receipt.get("seed")) is not int
        or not isinstance(receipt.get("target_step"), str)
        or not isinstance(receipt.get("patch"), list)
        or len(receipt["patch"]) > 1
    ):
        raise ValueError("floorplan mode receipt binding is invalid")
    for field in ("context_sha256", "parameter_card_sha256", "source_config_sha256"):
        if not isinstance(receipt.get(field), str) or not re.fullmatch(
            r"sha256:[0-9a-f]{64}", receipt[field]
        ):
            raise ValueError("floorplan mode receipt context is invalid")
    if receipt["mode"] == "die_size":
        _validate_size(receipt.get("die_size"))
    elif receipt.get("die_size") is not None:
        raise ValueError("die_util cannot bind a fixed die size")
    return receipt


def prepare_floorplan_mode(workspace, request) -> None:
    inherited = read_floorplan_mode(workspace, inherited=True)
    if request.floorplan_mode is None and inherited is None:
        return
    root = _isolated_root(workspace)
    if root.name != request.candidate_id:
        raise ValueError("floorplan mode candidate identity is invalid")
    config_path = _local_path(workspace, workspace.config["Floorplan"])
    config = read_json_object(config_path, "floorplan config")
    builder = config.get("die_builder")
    if not isinstance(builder, dict) or builder.get("mode") not in _MODES:
        raise ValueError("floorplan die_builder mode is invalid")
    mode = request.floorplan_mode if request.floorplan_mode is not None else inherited["mode"]
    if mode not in _MODES:
        raise ValueError("floorplan mode is invalid")
    size = None
    if mode == "die_size":
        size = (
            inherited["die_size"]
            if inherited and inherited["mode"] == mode
            else builder.get("die_size")
        )
        _validate_size(size)
    receipt = {
        "schema": _SCHEMA,
        "candidate_id": request.candidate_id,
        "target_step": request.target_step,
        "mode": mode,
        "previous_mode": inherited["mode"] if inherited else builder["mode"],
        "die_size": size,
        "patch": request.patch,
        "context_sha256": request.context_sha256,
        "parameter_card_sha256": request.parameter_card_sha256,
        "seed": request.seed,
        "source_config_sha256": sha256_path(config_path),
    }
    receipt["receipt_sha256"] = sha256_bytes(canonical_json_bytes(receipt))
    write_json_atomic(root / FLOORPLAN_MODE_REF, receipt)
    apply_floorplan_mode(workspace, "Floorplan")


def apply_floorplan_mode(workspace, step_name: str) -> None:
    if step_name != "Floorplan":
        return
    receipt = read_floorplan_mode(workspace)
    if receipt is None:
        return
    path = _local_path(workspace, workspace.config["Floorplan"])
    config = read_json_object(path, "floorplan config")
    builder = config.get("die_builder")
    if not isinstance(builder, dict):
        raise ValueError("floorplan die_builder is invalid")
    builder["mode"] = receipt["mode"]
    if receipt["mode"] == "die_size":
        builder["die_size"] = receipt["die_size"]
    write_json_atomic(path, config)


def validate_floorplan_mode_result(workspace, terminal_state: str) -> None:
    receipt = read_floorplan_mode(workspace)
    if receipt is None or terminal_state != "succeeded":
        return
    path = _local_path(workspace, workspace.config["Floorplan"])
    builder = read_json_object(path, "floorplan config").get("die_builder", {})
    if builder.get("mode") != receipt["mode"] or (
        receipt["mode"] == "die_size" and builder.get("die_size") != receipt["die_size"]
    ):
        raise ValueError("terminal floorplan mode does not match the isolated request")


def validate_floorplan_mode_resume(workspace, request) -> dict | None:
    receipt = read_floorplan_mode(workspace)
    if receipt is not None and any(
        receipt[field] != getattr(request, field)
        for field in ("candidate_id", "context_sha256", "parameter_card_sha256", "seed")
    ):
        raise ValueError("candidate resume floorplan mode context is invalid")
    return receipt
