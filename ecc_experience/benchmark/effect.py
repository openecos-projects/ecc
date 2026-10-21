"""Compare measured candidate trials with same-design baselines."""

import json
import math
from pathlib import Path


def compare(
    report: str | Path,
    output: str | Path,
    baselines: dict[str, str] | None = None,
) -> dict:
    source = Path(report).expanduser()
    if source.is_dir():
        source /= "matrix.json"
    payload = _read_report(source)
    destination = Path(output).expanduser().absolute()
    if destination.exists():
        raise ValueError("Effect report output must be new")
    rows = payload["rows"]
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        design = row.get("design_id")
        if not isinstance(design, str):
            raise ValueError("Campaign report has an invalid design ID")
        grouped.setdefault(design, []).append(row)
    pairs = []
    for design, design_rows in grouped.items():
        baseline = _select_baseline(design, design_rows, baselines or {})
        for candidate in design_rows:
            if candidate is baseline:
                continue
            pairs.append(_pair(design, baseline, candidate))
    valid = [item for item in pairs if item["status"] == "available"]
    result = {
        "schema": "ecc-experience-campaign-effect/1",
        "campaign_id": payload.get("campaign_id"),
        "status": "available" if valid else "unknown",
        "exit_code": 0 if valid else 7,
        "pairs": pairs,
        "available_pair_count": len(valid),
        "improvement_count": sum(item.get("qor_delta", 0) > 0 for item in valid),
        "generalization_status": "unproven",
        "safe_to_apply": False,
        "limitations": [
            "QoR effects are paired only within the same design and campaign",
            "A positive score delta is an observation, not a general PPA improvement",
            "Missing signoff, QoR or resource evidence remains unknown",
            "The first recorded trial is the implicit baseline unless explicitly selected",
        ],
    }
    destination.mkdir(parents=True)
    (destination / "effect.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    lines = [
        "# ECC campaign parameter effects",
        "",
        f"Status: {result['status']}; pairs: {len(pairs)}; available: {len(valid)}",
        "",
        "| Design | Baseline | Candidate | Status | QoR delta | Parameter changes |",
        "| --- | --- | --- | --- | ---: | --- |",
    ]
    for item in pairs:
        lines.append(
            "| {design} | {baseline} | {candidate} | {status} | {delta} | {changes} |".format(
                design=item["design"],
                baseline=item["baseline_trial"],
                candidate=item["candidate_trial"],
                status=item["status"],
                delta=item.get("qor_delta", "unknown"),
                changes=json.dumps(item["parameter_changes"], sort_keys=True),
            )
        )
    lines.extend(["", *result["limitations"], ""])
    (destination / "effect.md").write_text("\n".join(lines), encoding="utf-8")
    return result


def _read_report(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid campaign report: {path}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != "ecc-experience-campaign-report/1":
        raise ValueError("Invalid campaign report schema")
    if not isinstance(payload.get("rows"), list):
        raise ValueError("Campaign report rows are invalid")
    return payload


def _select_baseline(design: str, rows: list[dict], baselines: dict[str, str]) -> dict:
    requested = baselines.get(design)
    if requested is None:
        return rows[0]
    for row in rows:
        if row.get("trial_id") == requested:
            return row
    raise ValueError(f"Baseline trial does not exist: {design}/{requested}")


def _pair(design: str, baseline: dict, candidate: dict) -> dict:
    baseline_score = _score(baseline)
    candidate_score = _score(candidate)
    available = _valid(baseline) and _valid(candidate) and baseline_score is not None
    delta = candidate_score - baseline_score if available else None
    return {
        "design": design,
        "baseline_trial": baseline.get("trial_id"),
        "candidate_trial": candidate.get("trial_id"),
        "status": "available" if available else "unknown",
        "baseline_qor_score": baseline_score,
        "candidate_qor_score": candidate_score,
        "qor_delta": delta,
        "parameter_changes": _changes(baseline.get("parameters"), candidate.get("parameters")),
        "signoff": {
            "baseline": baseline.get("signoff", {}),
            "candidate": candidate.get("signoff", {}),
        },
        "resources": _resource_effect(baseline.get("steps", []), candidate.get("steps", [])),
    }


def _valid(row: dict) -> bool:
    return (
        row.get("status") in {"pass", "success"}
        and row.get("verification") == "pass"
        and row.get("integrity") == "pass"
        and _score(row) is not None
    )


def _score(row: dict) -> float | None:
    value = row.get("qor_score")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return float(value)
    return None


def _changes(baseline: object, candidate: object) -> dict:
    if not isinstance(baseline, dict) or not isinstance(candidate, dict):
        return {"status": "unknown", "changed": {}}
    keys = sorted(set(baseline) | set(candidate))
    changed = {
        key: {"baseline": baseline.get(key), "candidate": candidate.get(key)}
        for key in keys
        if baseline.get(key) != candidate.get(key)
    }
    return {"status": "available", "changed": changed}


def _resource_effect(baseline: object, candidate: object) -> dict:
    if not isinstance(baseline, list) or not isinstance(candidate, list):
        return {"status": "unknown", "steps": {}}
    base = {item.get("name"): item for item in baseline if isinstance(item, dict)}
    result = {}
    for item in candidate:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        previous = base.get(item["name"], {})
        old = previous.get("resource_observation")
        new = item.get("resource_observation")
        if (
            not isinstance(old, dict)
            or not isinstance(new, dict)
            or old.get("scope") != new.get("scope")
        ):
            result[item["name"]] = {"status": "unknown", "scope": None}
            continue
        result[item["name"]] = {
            "status": "available",
            "scope": old.get("scope"),
            "elapsed_seconds_delta": _delta(old.get("elapsed_seconds"), new.get("elapsed_seconds")),
            "peak_rss_bytes_delta": _delta(old.get("peak_rss_bytes"), new.get("peak_rss_bytes")),
        }
    return {"status": "available" if result else "unknown", "steps": result}


def _delta(old: object, new: object) -> float | None:
    if isinstance(old, (int, float)) and isinstance(new, (int, float)):
        return float(new) - float(old)
    return None
