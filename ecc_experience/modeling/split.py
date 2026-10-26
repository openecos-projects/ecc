"""Partition complete input groups before training; never split repeated observations."""

import math
import os
import shutil
import tempfile
from pathlib import Path

from ecc_experience.files import digest
from ecc_experience.modeling.dataset import read_dataset
from ecc_experience.modeling.validation import MATRIX_SCHEMA, invalid
from ecc_experience.models import ExperienceError
from ecc_experience.optimization.plan import write_plan


def split_dataset(
    dataset: str | Path,
    output: str | Path,
    *,
    by: str = "design",
    seed: str = "0",
    validation_fraction: float = 0.2,
    test_fraction: float = 0.2,
) -> dict:
    data = read_dataset(dataset)
    if by not in {"design", "family"}:
        raise invalid("Split grouping must be design or family")
    fractions = (validation_fraction, test_fraction)
    if (
        any(not math.isfinite(value) or not 0 < value < 1 for value in fractions)
        or sum(fractions) >= 1
    ):
        raise invalid("Validation and test fractions must be positive and sum to less than one")
    families = {}
    groups = {}
    for row in data["rows"]:
        fingerprint = row.get("input_content_fingerprint")
        family = row.get("group")
        if not isinstance(fingerprint, str) or not fingerprint:
            raise invalid("Split requires complete input fingerprints")
        if not isinstance(family, str) or not family:
            raise invalid("Split requires an explicit family for every row")
        if fingerprint in families and families[fingerprint] != family:
            raise invalid("One input fingerprint cannot belong to multiple families")
        families[fingerprint] = family
        key = fingerprint if by == "design" else family
        groups.setdefault(key, []).append(row)
    ordered = sorted(groups, key=lambda key: digest({"seed": seed, "group": key}))
    if len(ordered) < 3:
        return {
            "status": "unknown",
            "exit_code": 7,
            "reason": "At least three independent split groups are required",
            "group_count": len(ordered),
            "output_created": False,
        }
    validation_count = max(1, round(len(ordered) * validation_fraction))
    test_count = max(1, round(len(ordered) * test_fraction))
    if validation_count + test_count >= len(ordered):
        raise invalid("Split fractions leave no training group")
    assignments = {
        "validation": ordered[:validation_count],
        "test": ordered[validation_count : validation_count + test_count],
        "training": ordered[validation_count + test_count :],
    }
    if data["schema"] == "ecc-experience-model-dataset/2":
        family_partition = {}
        for name, keys in assignments.items():
            for key in keys:
                for row in groups[key]:
                    family = row["group"]
                    previous = family_partition.setdefault(family, name)
                    if previous != name:
                        raise ExperienceError(
                            "Split would leak one family across partitions",
                            code="experience_model_leakage",
                        )
    destination = Path(output).expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        raise invalid("Split output must be a new directory")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".dataset-split-", dir=destination.parent))
    try:
        partitions = {}
        for name, keys in assignments.items():
            rows = sorted(
                [row for key in keys for row in groups[key]], key=lambda row: row["case_id"]
            )
            subset = subset_dataset(data, rows)
            write_plan(staging / f"{name}.json", subset)
            partitions[name] = {
                "dataset": str(destination / f"{name}.json"),
                "dataset_id": subset["dataset_id"],
                "row_count": len(rows),
                "independent_input_count": len({row["input_content_fingerprint"] for row in rows}),
                "families": sorted({row["group"] for row in rows}),
            }
            if name != "training":
                write_matrix(staging, name, data, rows)
        result = {
            "schema": "ecc-experience-model-split/1",
            "source_dataset_id": data["dataset_id"],
            "by": by,
            "seed": seed,
            "validation_fraction": validation_fraction,
            "test_fraction": test_fraction,
            "partitions": partitions,
            "status": "complete",
            "exit_code": 0,
            "safe_to_apply": False,
        }
        result["split_id"] = f"split-{digest(result)}"
        write_plan(staging / "split.json", result)
        os.rename(staging, destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return result


def subset_dataset(data: dict, rows: list[dict]) -> dict:
    identity = {
        key: data[key]
        for key in (
            "schema",
            "feature_schema",
            "release_id",
            "release_sha256",
            "target",
            "through_step",
        )
    }
    identity.update(groups={row["case_id"]: row["group"] for row in rows}, rows=rows)
    return {
        **identity,
        "dataset_id": f"dataset-{digest(identity)}",
        "summary": {
            "row_count": len(rows),
            "independent_input_count": len({row["input_content_fingerprint"] for row in rows}),
            "group_count": len({row["group"] for row in rows}),
        },
        "excluded": [],
        "limitations": data.get("limitations", []),
    }


def write_matrix(root: Path, name: str, data: dict, rows: list[dict]) -> dict:
    designs = {}
    for row in rows:
        designs.setdefault(row["input_content_fingerprint"], []).append(row)
    entries = []
    for fingerprint, design_rows in sorted(designs.items()):
        relative = f"{name}-designs/{digest(fingerprint)}.json"
        write_plan(root / relative, subset_dataset(data, design_rows))
        entries.append({"path": relative, "design": fingerprint, "family": design_rows[0]["group"]})
    identity = {"schema": MATRIX_SCHEMA, "datasets": entries}
    matrix = {**identity, "matrix_id": f"matrix-{digest(identity)}"}
    write_plan(root / f"{name}-matrix.json", matrix)
    return matrix
