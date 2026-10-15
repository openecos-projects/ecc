"""Read current sweep evidence before exporting or selecting a Pareto front."""

import hashlib
import math
import re
from pathlib import Path

from chipcompiler.analysis.pareto import Objective, rank_points
from chipcompiler.analysis.qor.metric_registry import METRIC_REGISTRY
from chipcompiler.cli.experiments.candidate_evidence import candidate_evidence
from chipcompiler.cli.experiments.operations import _json_command, load_json
from chipcompiler.cli.inspection.project_artifacts import read_workspace_artifact
from chipcompiler.data.parameter_schema import parse_cli_overrides
from chipcompiler.engine.snapshot import read_engineering_snapshot_from_directory
from chipcompiler.engine.snapshot_limits import CHECKLIST_READ_MAX_BYTES


def sweep_pareto(project: Path, name: str, objective_arguments: list[str]) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*", name):
        raise ValueError("Sweep name must be a single safe component")
    objectives = []
    for argument in objective_arguments:
        parts = argument.split(":")
        if len(parts) != 3:
            raise ValueError("Use --objective ID:UNIT:minimize|maximize")
        direction = parts[2]
        if direction not in ("minimize", "maximize"):
            raise ValueError("Direction must be minimize or maximize")
        objective = Objective(parts[0], parts[1], direction)
        registered = METRIC_REGISTRY.get(objective.id)
        if objective.id == "qor_score":
            registered = ("score", "higher_is_better")
        polarity = "lower_is_better" if objective.direction == "minimize" else "higher_is_better"
        if registered != (objective.unit, polarity):
            raise ValueError("Objective ID, unit and direction must match the ECC registry")
        objectives.append(objective)
    rank_points({}, objectives)
    root = project / "experiments" / name
    plan = load_json(root / "sweep.json")
    if not isinstance(plan, dict) or not isinstance(plan.get("candidates"), list):
        raise ValueError("Sweep does not exist or has an invalid plan")
    rows = load_json(root / "results.json", {"results": []}).get("results", [])
    points, evidence, excluded = {}, {}, []
    for candidate in plan["candidates"]:
        identity = candidate["id"]
        if not re.fullmatch(r"[A-Za-z0-9_-]+", identity):
            raise ValueError("Invalid sweep candidate identity")
        found = [row for row in rows if row.get("id") == identity]
        try:
            if len(found) != 1 or found[0].get("status") != "passed":
                raise ValueError("Candidate has no unique passed execution")
            row = found[0]
            workspace = (root / "candidates" / identity / "project" / identity).resolve()
            if Path(row["workspace"]).resolve() != workspace or not workspace.is_relative_to(
                project.resolve()
            ):
                raise ValueError("Candidate workspace differs from sweep binding")
            before = (workspace / "home/engineering-snapshot.json").read_bytes()
            facts = read_engineering_snapshot_from_directory(workspace)
            parameters, errors = parse_cli_overrides(
                [f"{key}={value}" for key, value in candidate["parameters"].items()]
            )
            if errors or any(
                facts["workspaceSpec"]["parameters"].get(key) != value
                for key, value in parameters.items()
            ):
                raise ValueError("Candidate parameters differ from committed configuration")
            status_code, _status = _json_command(workspace.parent, workspace, "status")
            signoff_code, signoff = _json_command(workspace.parent, workspace, "signoff check")
            checked = candidate_evidence(
                facts["flow"],
                facts["checklist"],
                facts["qorSnapshotExtension"],
                exit_code=row["exit_code"],
                status_code=status_code,
                signoff_code=signoff_code,
                signoff_payload=signoff,
            )
            if checked["status"] != "passed" or checked["violation_count"] != 0:
                raise ValueError("Current full-flow signoff or checker evidence is not clean")
            measurements = [_measurement(workspace, facts, objective) for objective in objectives]
            if (workspace / "home/engineering-snapshot.json").read_bytes() != before:
                raise ValueError("Candidate snapshot changed while inspecting")
            points[identity] = [item["value"] for item in measurements]
            evidence[identity] = {
                "parameters": parameters,
                "workspace": str(workspace),
                "snapshot_sha256": hashlib.sha256(before).hexdigest(),
                "objectives": measurements,
            }
        except (OSError, ValueError, KeyError, TypeError) as exc:
            excluded.append({"candidate": identity, "reason": str(exc)})
    ranked = rank_points(points, objectives)
    return {
        "schema": "ecc-explore-pareto/1",
        "sweep": name,
        "objectives": [vars(item) for item in objectives],
        "front": [{**record, **evidence[record["id"]]} for record in ranked if record["rank"] == 0],
        "ranking": ranked,
        "excluded": excluded,
        "safe_to_apply": False,
        "scope": "current_full_flow_signoff_and_observed_metric_files",
    }


def _measurement(workspace: Path, facts: dict, objective: Objective) -> dict:
    if objective.id == "qor_score":
        extension = facts["qorSnapshotExtension"]
        value = extension.get("score") if extension.get("status") == "available" else None
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
        ):
            raise ValueError("QoR is unavailable")
        return {
            "id": objective.id,
            "unit": objective.unit,
            "value": value,
            "source": "engineering-snapshot",
        }
    matching = []
    for artifact in facts["artifacts"]:
        if artifact.get("kind") != "qor_metrics" or artifact.get("availability") != "available":
            continue
        path = workspace / artifact["reference"]
        result = read_workspace_artifact(workspace, path, CHECKLIST_READ_MAX_BYTES)
        if result.status != "available":
            continue
        payload = result.data
        if not isinstance(payload, dict):
            continue
        integrity = payload.get("integrity", {})
        if (
            not isinstance(integrity, dict)
            or payload.get("schema_version") != 3
            or payload.get("status") != "success"
            or not isinstance(integrity.get("invalid_metric_source_ids", []), list)
            or integrity.get("status") != "pass"
            or objective.id in integrity.get("invalid_metric_source_ids", [])
        ):
            continue
        for metric in payload.get("metrics", []):
            value = metric.get("value")
            if (
                metric.get("id") == objective.id
                and metric.get("unit") == objective.unit
                and type(value) in (int, float)
                and math.isfinite(value)
            ):
                matching.append(
                    {
                        "id": objective.id,
                        "unit": objective.unit,
                        "value": value,
                        "source": artifact["reference"],
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "scope": metric.get("scope"),
                        "corner": metric.get("corner"),
                    }
                )
    if len(matching) != 1:
        raise ValueError(f"Objective is unavailable or ambiguous: {objective.id}")
    return matching[0]


def select_front(report: dict, candidate: str | None, weights: str | None) -> str | None:
    front = report["front"]
    if candidate and weights:
        raise ValueError("Use either an explicit candidate or weights")
    if candidate:
        if candidate not in {row["id"] for row in front}:
            raise ValueError("Selected candidate must belong to the verified Pareto front")
        return candidate
    if weights is None:
        return None
    parsed = [float(value) for value in weights.split(",")]
    if (
        len(parsed) != len(report["objectives"])
        or any(not math.isfinite(value) or value < 0 for value in parsed)
        or sum(parsed) <= 0
    ):
        raise ValueError(
            "Weights require one finite non-negative value per objective and a positive sum"
        )
    if not front:
        return None

    def utility(row):
        total = 0.0
        for index, (weight, objective) in enumerate(zip(parsed, report["objectives"], strict=True)):
            values = [point["objectives"][index]["value"] for point in front]
            low, high = min(values), max(values)
            value = row["objectives"][index]["value"]
            normalized = (value - low) / (high - low) if high > low else 0.0
            total += weight * (normalized if objective["direction"] == "minimize" else -normalized)
        return total, row["id"]

    return min(front, key=utility)["id"]
