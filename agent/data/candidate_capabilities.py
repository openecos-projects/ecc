"""Stable capability metadata for controlled ECC candidate execution."""

from dataclasses import asdict
from typing import Any

from .candidate_registry import (
    CANDIDATE_TARGET_BACKENDS,
    candidate_capability_registry,
    candidate_registry_digest,
    candidate_target_backend,
)

CAPABILITIES_SCHEMA = "ecc.workspace.candidate_capabilities.v1"
CAPABILITIES_SCHEMA_VERSION = 1

EXCLUDED_CONFIGURATION_GROUPS = {
    "Floorplan": [
        "Floorplan.Auto place pin",
        "Floorplan.Tracks",
        "Macro Placement",
        "PDN.IO",
        "PDN.Global connect",
        "PDN.Grid",
        "PDN.Stripe",
        "PDN.Connect layers",
    ],
}


def export_candidate_capabilities(workspace: Any) -> dict[str, Any]:
    """Return the current workspace's candidate capability contract."""
    grouped = _group_knobs_by_target()
    return {
        "schema": CAPABILITIES_SCHEMA,
        "schema_version": CAPABILITIES_SCHEMA_VERSION,
        "registry_sha256": candidate_registry_digest(),
        "targets": [
            _target_payload(workspace, target_step, available_knobs, unavailable_knobs)
            for target_step, available_knobs, unavailable_knobs in grouped
        ],
    }


def _group_knobs_by_target() -> list[tuple[str, list[Any], list[Any]]]:
    knobs_by_target: dict[str, list[Any]] = {target: [] for target in CANDIDATE_TARGET_BACKENDS}
    for knob in candidate_capability_registry():
        knobs_by_target.setdefault(knob.target_step, []).append(knob)
    return [
        (
            target_step,
            sorted(
                (knob for knob in knobs_by_target[target_step] if knob.available),
                key=lambda knob: knob.knob_id,
            ),
            sorted(
                (knob for knob in knobs_by_target[target_step] if not knob.available),
                key=lambda knob: knob.knob_id,
            ),
        )
        for target_step in CANDIDATE_TARGET_BACKENDS
    ]


def _target_payload(
    workspace: Any,
    target_step: str,
    available_knobs: list[Any],
    unavailable_knobs: list[Any],
) -> dict[str, Any]:
    backend = candidate_target_backend(workspace, target_step)
    knob_payloads = [_knob_payload(knob) for knob in available_knobs]
    unavailable_payloads = [_knob_payload(knob) for knob in unavailable_knobs]
    if backend["available"] is not True:
        unavailable_payloads = [
            *_backend_unavailable_knobs(knob_payloads, backend["reason"]),
            *unavailable_payloads,
        ]
        knob_payloads = []
    return {
        "target_step": target_step,
        "candidate_generation": bool(backend["available"]),
        "backend": backend,
        "knobs": knob_payloads,
        "unavailable_knobs": unavailable_payloads,
        "excluded_configuration_groups": EXCLUDED_CONFIGURATION_GROUPS.get(target_step, []),
    }


def _knob_payload(knob: Any) -> dict[str, Any]:
    payload = asdict(knob)
    payload["json_path"] = list(knob.json_path)
    return payload


def _backend_unavailable_knobs(knobs: list[dict[str, Any]], reason: str) -> list[dict[str, Any]]:
    unavailable = []
    for knob in knobs:
        payload = dict(knob)
        payload["available"] = False
        payload["unavailable_reason"] = reason
        unavailable.append(payload)
    return unavailable
