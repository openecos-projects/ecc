"""Build a read-only, provenance-preserving manifest across experience stores."""

import json
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from ecc_experience.files import digest
from ecc_experience.knowledge.configuration import configuration_identity
from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.knowledge.summary import summarize_case
from ecc_experience.knowledge.verify import verify_case
from ecc_experience.models import ExperienceError

NORMALIZED_SCHEMA = "ecc-experience-normalized-manifest/1"
_QUALITY_ORDER = (
    "verified_pass",
    "verified_observation",
    "blocked",
    "qor_unknown",
    "incomplete",
    "evidence_invalid",
)


def normalize_stores(stores: Sequence[str | Path], output: str | Path) -> dict:
    if not stores:
        raise ExperienceError("At least one store is required", code="experience_normalize_invalid")
    repositories = sorted(
        {repository.root: repository for repository in map(ExperienceStore, stores)}.values(),
        key=lambda repository: str(repository.root),
    )
    destination = Path(output).expanduser().resolve()
    if any(destination.is_relative_to(repository.root) for repository in repositories):
        raise ExperienceError(
            "Normalization output must be outside every source store",
            code="experience_normalize_invalid",
        )
    if destination.exists() or Path(output).expanduser().is_symlink():
        raise ExperienceError(
            "Normalization output already exists", code="experience_normalize_conflict"
        )
    observations = []
    sources = []
    errors = []
    for repository in repositories:
        source, entries, failures = _read_store(repository)
        sources.append(source)
        observations.extend(entries)
        errors.extend(failures)
    cases = _merge_cases(observations)
    groups = _configuration_groups(cases)
    selections = _selections(cases, errors)
    quality = Counter(case["quality_class"] for case in cases)
    status = (
        "fail"
        if errors or selections["quarantine"]
        else "unknown"
        if not cases
        or any(source["changed_during_read"] for source in sources)
        or any(not case["release_eligible"] for case in cases)
        else "pass"
    )
    report = {
        "schema": NORMALIZED_SCHEMA,
        "status": status,
        "exit_code": 6 if status == "fail" else 7 if status == "unknown" else 0,
        "counts": {
            "stores": len(sources),
            "source_observations": len(observations),
            "unique_cases": len(cases),
            "exact_duplicate_observations": len(observations) - len(cases),
            "configuration_groups": len(groups),
            "quality": {name: quality[name] for name in _QUALITY_ORDER},
            "positive": len(selections["positive"]),
            "negative": len(selections["negative"]),
            "quarantined_sources": len(selections["quarantine"]),
            "read_errors": len(errors),
        },
        "stores": sources,
        "cases": cases,
        "configuration_groups": groups,
        "selections": selections,
        "errors": errors,
        "limitations": [
            "A manifest references original stores; it is not an evidence archive or release",
            "Reverify after writers stop; this scan is not a cross-store transaction",
            "Exact duplicate cases preserve every source and its individual verification",
            "Configuration groups require matching inputs, PDK, parameters, runtime and flow",
            "Incomplete configuration identity keeps distinct cases in distinct groups",
            "Repeated configurations are not proof of independent executions or parameter effects",
            "Negative observations may lack QoR but require otherwise passing verification",
            "Resource scope and attempt identity are preserved; costs are not summed",
            "Dataset and DSE commands still require their existing release and plan inputs",
        ],
    }
    report["manifest_id"] = f"normalized-{digest(report)}"
    _write_manifest(destination, report)
    return {**report, "output": str(destination)}


def _read_store(repository: ExperienceStore) -> tuple[dict, list[dict], list[dict]]:
    directory = str(repository.root)
    source = {"store": directory, "cases": 0, "changed_during_read": False}
    entries = []
    errors = []
    try:
        locked = (repository.root / ".write-lock").exists()
        identifiers = repository.list_ids()
        source["cases"] = len(identifiers)
        for case_id in identifiers:
            try:
                case = repository.read(case_id)
                case_directory = repository.case_directory(case_id)
                verification = verify_case(case, case_directory)
                row = summarize_case(case, verification)
                entries.append(
                    {
                        **row,
                        "configuration": configuration_identity(case),
                        "provenance": {
                            "store": directory,
                            "case_id": case_id,
                            "case_path": str(case_directory / "case.json"),
                            "collected_at": case.collected_at,
                            "source": case.source.model_dump(),
                            "verification": row["verification"],
                            "integrity": row["integrity"],
                            "quality_class": row["quality_class"],
                            "release_eligible": row["release_eligible"],
                            "negative_eligible": row["quality_class"] == "blocked"
                            and all(finding["check"] == "qor" for finding in row["findings"]),
                            "findings": row["findings"],
                            "finding_counts": row["finding_counts"],
                            "changed_during_read": False,
                        },
                    }
                )
            except (ExperienceError, OSError) as exc:
                errors.append({"store": directory, "case_id": case_id, "reason": str(exc)})
        source["changed_during_read"] = (
            locked
            or (repository.root / ".write-lock").exists()
            or identifiers != repository.list_ids()
        )
    except (ExperienceError, OSError) as exc:
        errors.append({"store": directory, "case_id": None, "reason": str(exc)})
        source["changed_during_read"] = True
    if source["changed_during_read"]:
        for entry in entries:
            entry["release_eligible"] = False
            entry["provenance"].update(
                {
                    "release_eligible": False,
                    "negative_eligible": False,
                    "changed_during_read": True,
                }
            )
    return source, entries, errors


def _merge_cases(observations: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for observation in observations:
        grouped.setdefault(observation["case_id"], []).append(observation)
    result = []
    for case_id, entries in sorted(grouped.items()):
        representative = min(
            entries,
            key=lambda entry: (
                not entry["release_eligible"],
                not entry["provenance"]["negative_eligible"],
                _QUALITY_ORDER.index(entry["quality_class"]),
                entry["provenance"]["store"],
            ),
        )
        result.append(
            {
                **representative,
                "case_id": case_id,
                "provenance": [entry["provenance"] for entry in entries],
            }
        )
    return result


def _configuration_groups(cases: list[dict]) -> list[dict]:
    groups = {}
    for case in cases:
        configuration = case["configuration"]
        group = groups.setdefault(
            configuration["key"],
            {
                "group_id": configuration["key"],
                "identity_complete": configuration["complete"],
                "missing_identity": configuration["missing_identity"],
                "case_ids": [],
                "source_observations": 0,
            },
        )
        group["case_ids"].append(case["case_id"])
        group["source_observations"] += len(case["provenance"])
    return [groups[key] for key in sorted(groups)]


def _selections(cases: list[dict], errors: list[dict]) -> dict:
    selections = {"positive": [], "negative": [], "qor_missing": [], "other": [], "quarantine": []}
    for case in cases:
        sources = case["provenance"]
        positive = next((source for source in sources if source["release_eligible"]), None)
        negative = next((source for source in sources if source["negative_eligible"]), None)
        selected = positive or negative or sources[0]
        reference = {key: selected[key] for key in ("case_id", "store", "case_path")}
        category = (
            "positive"
            if positive
            else "negative"
            if negative
            else "qor_missing"
            if case["qor_status"] != "available"
            else "other"
        )
        if case["quality_class"] != "evidence_invalid":
            selections[category].append(reference)
        for source in sources:
            if source["quality_class"] == "evidence_invalid":
                selections["quarantine"].append(
                    {
                        **{key: source[key] for key in ("case_id", "store", "case_path")},
                        "integrity": source["integrity"],
                        "verification": source["verification"],
                        "findings": source["findings"],
                    }
                )
    selections["quarantine"].extend({**error, "verification": "unreadable"} for error in errors)
    return selections


def _write_manifest(destination: Path, report: dict) -> None:
    try:
        destination.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise ExperienceError(
            "Normalization output already exists", code="experience_normalize_conflict"
        ) from exc
    (destination / "normalized-manifest.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"
    )
    counts = report["counts"]
    lines = [
        "# ECC normalized experience manifest",
        "",
        f"Status: {report['status']}",
        "",
        f"Stores: {counts['stores']}",
        f"Source observations: {counts['source_observations']}",
        f"Unique cases: {counts['unique_cases']}",
        f"Exact duplicate observations: {counts['exact_duplicate_observations']}",
        f"Configuration groups: {counts['configuration_groups']}",
        "",
        "| Selection | Count |",
        "| --- | ---: |",
        *[f"| {name} | {len(values)} |" for name, values in report["selections"].items()],
        "",
        *report["limitations"],
        "",
    ]
    (destination / "normalized-manifest.md").write_text("\n".join(lines), encoding="utf-8")
