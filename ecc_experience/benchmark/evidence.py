"""Recognize geometry outputs written back by the existing ECC tool runner."""

from math import isclose, isfinite
from pathlib import Path
from typing import TypeGuard

from chipcompiler.cli.inspection.step_view import build_step_detail_records
from ecc_experience.adapters.chipcompiler_reader import read_workspace_observation
from ecc_experience.files import file_digest, read_json, safe_child
from ecc_experience.models import WorkspaceObservation
from ecc_experience.optimization.evidence import validate_trial
from ecc_experience.optimization.policy import configuration_differences


def collect_trial(
    workspace: Path,
    store: str,
    baseline: WorkspaceObservation,
    run_id: str,
) -> dict:
    observation = read_workspace_observation(workspace)
    requested = baseline.facts["workspaceSpec"]["parameters"]
    observed = observation.facts["workspaceSpec"]["parameters"]
    changed = configuration_differences(requested, observed)
    geometry_fields = {
        "floorplan.aspect_ratio",
        "floorplan.die_builder.die_size.width_micron",
        "floorplan.die_builder.die_size.height_micron",
    }
    updates = {}
    evidence = {}
    if changed & geometry_fields:
        report = _geometry_report(workspace, observation)
        if report is not None:
            reference, geometry = report
            width = geometry.get("die_bounding_width")
            height = geometry.get("die_bounding_height")
            if _positive(width) and _positive(height):
                values = {
                    "floorplan.aspect_ratio": width / height,
                    "floorplan.die_builder.die_size.width_micron": width,
                    "floorplan.die_builder.die_size.height_micron": height,
                }
                for key in changed & geometry_fields:
                    value = observed.get(key)
                    if _positive(value) and isclose(value, values[key], rel_tol=1e-12):
                        updates[key] = value
                        evidence[key] = {
                            "requested": requested.get(key),
                            "observed": value,
                            "source": reference,
                            "source_sha256": file_digest(safe_child(workspace, reference))[0],
                        }
    result = validate_trial(workspace, store, baseline, updates, run_id)
    return {**result, "runtime_parameter_updates": evidence}


def _positive(value: object) -> TypeGuard[int | float]:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and isfinite(value)
        and value > 0
    )


def _geometry_report(workspace: Path, observation: WorkspaceObservation) -> tuple[str, dict] | None:
    for step in reversed(observation.facts["flow"]["steps"]):
        if step.get("tool") != "ecc" or step.get("state") != "Success":
            continue
        records = build_step_detail_records(str(workspace), step["name"], ("feature",)) or []
        references = {
            record["source"]
            for record in records
            if record.get("section") == "feature"
            and isinstance(record.get("source"), str)
            and record["source"].endswith(".db.json")
        }
        for reference in sorted(references):
            layout = read_json(safe_child(workspace, reference)).get("Design Layout")
            if isinstance(layout, dict):
                return reference, layout
    return None
