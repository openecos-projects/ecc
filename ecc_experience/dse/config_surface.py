"""Describe the iteration config files that frozen DSE axes actually control.

DSE never patches a workspace JSON file directly. A reviewed parameter is
written through ``param apply``; the workspace refresh then atomically rewrites
the derived ``config/*.json`` files. This module keeps that provenance
inspectable so a plan or report can show which file and JSON path every axis
changes.
"""

import json
import math
from pathlib import Path
from typing import Final

from chipcompiler.data.parameter_schema import lookup_schema
from ecc_experience.files import digest
from ecc_experience.models import ExperienceError

SURFACE_SCHEMA: Final = "ecc-experience-dse-config-surface/1"
RECEIPT_SCHEMA: Final = "ecc-experience-dse-config-receipt/1"

_CONFIG_FILENAMES: Final[dict[str, str]] = {
    "CTS": "cts_ecc.json",
    "Floorplan": "floorplan_ecc.json",
    "RCX": "rcx_ecc.json",
    "dreamplace": "dreamplace_ecc.json",
    "emir": "emir_ecc.json",
    "filler": "filler_ecc.json",
    "route": "route_ecc.json",
    "sizer": "sizer_ecc.json",
    "sta": "sta_ecc.json",
}

# Parameters whose public key predates ConfigTarget. The workspace refresh
# expands these flat keys into the same tool JSON files as ConfigTarget
# parameters, so they remain valid search axes when the path is known.
_LEGACY_TARGETS: Final[dict[tuple[str, ...], tuple[str, tuple[tuple[str, ...], ...]]]] = {
    ("dreamplace", "target_density"): (
        "dreamplace_ecc.json",
        (("target_density",),),
    ),
    ("dreamplace", "stop_overflow"): (
        "dreamplace_ecc.json",
        (("stop_overflow",),),
    ),
    ("dreamplace", "cell_padding_x"): (
        "dreamplace_ecc.json",
        (("cell_padding_x",),),
    ),
    ("dreamplace", "routability_opt_flag"): (
        "dreamplace_ecc.json",
        (("routability_opt_flag",),),
    ),
    ("core", "utilitization"): (
        "floorplan_ecc.json",
        (("die_builder", "die_util", "utilization"),),
    ),
    ("core", "margin"): (
        "floorplan_ecc.json",
        (
            ("die_builder", "margin", "left_micron"),
            ("die_builder", "margin", "right_micron"),
            ("die_builder", "margin", "top_micron"),
            ("die_builder", "margin", "bottom_micron"),
        ),
    ),
    ("core", "aspect_ratio"): (
        "floorplan_ecc.json",
        (("die_builder", "die_util", "aspect_ratio"),),
    ),
    ("max_fanout",): (
        "cts_ecc.json",
        (("max_fanout",),),
    ),
    ("bottom_layer",): (
        "route_ecc.json",
        (("RT", "-bottom_routing_layer"),),
    ),
    ("top_layer",): (
        "route_ecc.json",
        (("RT", "-top_routing_layer"),),
    ),
}

# Several public keys still exist for one tool field. The value read back from
# a workspace can therefore contain both keys even when the candidate changed
# only the supported one. Comparison and warm-start matching must collapse the
# aliases or a valid trial looks like it changed an unauthorized parameter.
_PARAMETER_ALIASES: Final[dict[str, str]] = {
    "place.stop_overflow": "place.target_overflow",
    "place.routability_opt_flag": "place.routability_opt",
    "place.inflation_s5b1_enabled": "place.timing_opt_enabled",
    "place.inflation_s5b1_buffering_enabled": "place.timing_opt_buffering_enabled",
    "place.inflation_s5b1_max_windows": "place.timing_opt_max_windows",
    "place.inflation_s5b1_overflow_milestones": "place.timing_opt_overflow_milestones",
    "place.inflation_sizing_rounds": "place.timing_opt_sizing_rounds",
}


def describe_config_surface(parameters: dict | list[str]) -> dict:
    """Return the reviewed config-file targets for the given parameter keys."""
    entries: list[dict] = []
    files: dict[str, list[str]] = {}
    unmapped: list[str] = []
    for parameter in sorted(parameters):
        target = _config_target(parameter)
        if target is None:
            unmapped.append(parameter)
            continue
        config_file, json_paths, source = target
        entries.append(
            {
                "parameter": parameter,
                "config_file": config_file,
                "json_paths": [list(path) for path in json_paths],
                "source": source,
                "application": "workspace_param_apply",
                "receipt": "params.toml:workspace_param_overrides",
            }
        )
        files.setdefault(config_file, []).append(parameter)
    return {
        "schema": SURFACE_SCHEMA,
        "entries": entries,
        "files": {key: files[key] for key in sorted(files)},
        "unmapped": unmapped,
    }


def config_files(parameters: dict | list[str]) -> list[str]:
    return sorted(describe_config_surface(parameters)["files"])


def canonicalize_parameters(parameters: dict) -> dict:
    """Collapse documented aliases to the supported key for comparison."""
    canonical: dict = {}
    aliases: dict[str, object] = {}
    for key, value in parameters.items():
        target = _PARAMETER_ALIASES.get(key)
        if target is None:
            canonical[key] = value
        else:
            aliases[target] = value
    for key, value in aliases.items():
        canonical.setdefault(key, value)
    return canonical


def validate_config_surface(parameters: dict | list[str]) -> dict:
    """Reject axes that cannot change a tool configuration file."""
    surface = describe_config_surface(parameters)
    if surface["unmapped"]:
        listed = ", ".join(surface["unmapped"])
        raise ExperienceError(
            f"DSE parameters have no iteration config-file effect: {listed}",
            code="experience_plan_invalid",
        )
    return surface


def verify_applied_config(workspace: str | Path, parameters: dict) -> dict:
    """Check that ``param apply`` reached the iteration config JSON files."""
    surface = describe_config_surface(parameters)
    root = Path(workspace)
    checks: list[dict] = []
    files: set[str] = set()
    unavailable: list[str] = []
    for entry in surface["entries"]:
        parameter = entry["parameter"]
        config_file = entry["config_file"]
        path = root / "config" / config_file
        files.add(config_file)
        try:
            with path.open(encoding="utf-8") as stream:
                config = json.load(stream)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            unavailable.append(f"{config_file}: {exc}")
            continue
        expected_values = expected_config_values(
            parameter, parameters[parameter], entry["json_paths"]
        )
        for json_path, expected in zip(entry["json_paths"], expected_values, strict=True):
            observed = _nested_value(config, json_path)
            checks.append(
                {
                    "parameter": parameter,
                    "config_file": config_file,
                    "json_path": list(json_path),
                    "expected": expected,
                    "observed": observed,
                    "match": _same_value(expected, observed),
                }
            )
    mismatches = [item for item in checks if not item["match"]]
    if unavailable:
        status = "unavailable"
        reason = "; ".join(unavailable)
    elif mismatches:
        status = "mismatch"
        reason = "Applied parameters differ from the iteration config files"
    else:
        status = "applied"
        reason = None
    return {
        "schema": RECEIPT_SCHEMA,
        "status": status,
        "reason": reason,
        "workspace": str(root),
        "files": sorted(files),
        "checks": checks,
        "mismatches": mismatches,
        "unmapped": surface["unmapped"],
    }


def _config_target(parameter: str) -> tuple[str, tuple[tuple[str, ...], ...], str] | None:
    schema = lookup_schema(parameter)
    if schema is None:
        return None
    if schema.config_target is not None:
        config_file = _CONFIG_FILENAMES.get(schema.config_target.config_key)
        if config_file is None:
            return None
        return config_file, (tuple(schema.config_target.json_path),), "config_target"
    if schema.maps_to is None:
        return None
    legacy = _LEGACY_TARGETS.get(_mapping_key(schema.maps_to))
    if legacy is None:
        return None
    config_file, json_paths = legacy
    return config_file, json_paths, "legacy_mapping"


def _mapping_key(maps_to: str | dict) -> tuple[str, ...]:
    if isinstance(maps_to, str):
        return (maps_to,)
    if len(maps_to) == 1:
        parent, child = next(iter(maps_to.items()))
        return (parent, child)
    return tuple(sorted(maps_to))


def expected_config_values(parameter: str, value: object, json_paths: list[list[str]]) -> list:
    if (
        parameter == "floorplan.core_margin"
        and isinstance(value, (list, tuple))
        and len(value) >= 2
    ):
        # The public list is [horizontal, vertical]; the config stores each side.
        return [value[0], value[0], value[1], value[1]]
    return [value] * len(json_paths)


def _nested_value(config: object, path: list[str]) -> object:
    current = config
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def _same_value(expected: object, observed: object) -> bool:
    if (
        isinstance(expected, (int, float))
        and not isinstance(expected, bool)
        and isinstance(observed, (int, float))
        and not isinstance(observed, bool)
    ):
        return math.isclose(float(expected), float(observed), rel_tol=1e-9, abs_tol=1e-12)
    return expected == observed


def parameter_evidence_from_config_receipt(
    receipt: object,
    parameters: dict,
    *,
    candidate_id: str | None = None,
    stage: str | None = None,
) -> dict | None:
    """Convert a DSE iteration-config receipt into materialization evidence.

    This proves that a reviewed parameter reached the tool configuration file.
    It deliberately does not claim that the tool consumed the value or that the
    value caused any QoR change.
    """
    if not isinstance(receipt, dict) or receipt.get("status") != "applied":
        return None
    checks = receipt.get("checks")
    if not isinstance(checks, list) or not checks:
        return None
    if any(
        not isinstance(check, dict)
        or check.get("match") is not True
        or not isinstance(check.get("parameter"), str)
        for check in checks
    ):
        return None
    applications = []
    for parameter in sorted(parameters):
        selected = [check for check in checks if check["parameter"] == parameter]
        if not selected:
            return None
        observed = [check.get("observed") for check in selected]
        applications.append(
            {
                "knob_id": parameter,
                "value": parameters[parameter],
                "actual_value": observed[0] if len(observed) == 1 else observed,
                "unit": None,
                "status": "unknown",
                "candidate_id": candidate_id,
                "stage": stage,
            }
        )
    return {
        "level": "materialized",
        "receipt_sha256": digest(receipt),
        "receipt_status": "valid",
        "applied_parameters": applications,
        "limitations": [
            "DSE config receipt proves parameter materialization into the iteration "
            "tool configuration, not runtime consumption or a QoR effect"
        ],
    }
