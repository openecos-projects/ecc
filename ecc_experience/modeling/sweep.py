"""Convert digest-checked advisory rankings into native, unexecuted sweep plans."""

import os
import re
import shutil
import tempfile
import time
from pathlib import Path

from chipcompiler.cli.experiments.operations import payload_fingerprint
from chipcompiler.data.parameter_schema import parse_cli_overrides
from chipcompiler.project.manifest import CONFIG_FILENAME, MANIFEST_FILENAME
from ecc_experience.files import digest, read_json, safe_child
from ecc_experience.modeling.predict import ADVICE_SCHEMA, read_model_release
from ecc_experience.modeling.validation import invalid
from ecc_experience.optimization.plan import write_plan
from ecc_experience.optimization.policy import SUPPORTED_PARAMETERS


def seed_sweep(
    project: str | Path, advice: str | Path, model_release: str | Path, name: str
) -> dict:
    root = Path(project).expanduser().resolve()
    if not (root / CONFIG_FILENAME).is_file() and not (root / MANIFEST_FILENAME).is_file():
        raise invalid("Sweep target must be an ECC project")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", name):
        raise invalid("Sweep name must be a single safe path component")
    payload = read_json(Path(advice).expanduser())
    release = read_model_release(model_release)
    identity = {key: value for key, value in payload.items() if key != "advice_id"}
    if (
        payload.get("schema") != ADVICE_SCHEMA
        or payload.get("advice_id") != f"advice-{digest(identity)}"
        or payload.get("safe_to_apply") is not False
        or payload.get("model_release_id") != release["release_id"]
        or payload.get("model_id") != release["model_id"]
    ):
        raise invalid("Advice fingerprint or model release binding is invalid")
    selected = payload.get("candidates")
    if not isinstance(selected, list) or not 1 <= len(selected) <= 1000:
        raise invalid("Advice must contain between 1 and 1000 candidates")
    candidates = []
    seen = set()
    sources = []
    parameters = {}
    for item in selected:
        values = item.get("parameters") if isinstance(item, dict) else None
        if not isinstance(values, dict):
            raise invalid("Advice candidate parameters are invalid")
        retained = {key: value for key, value in values.items() if key in SUPPORTED_PARAMETERS}
        if not retained:
            raise invalid("Advice contains no reviewed floorplan, placement or CTS parameters")
        arguments = [f"{key}={value}" for key, value in sorted(retained.items())]
        parsed, errors = parse_cli_overrides(arguments)
        if errors or parsed != retained:
            raise invalid("Advice contains invalid parameter values")
        fingerprint = digest(parsed)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        normalized = {key: str(value) for key, value in sorted(parsed.items())}
        candidate_id = f"candidate_{len(candidates) + 1:04d}"
        candidates.append({"id": candidate_id, "parameters": normalized})
        sources.append(
            {
                "candidate": candidate_id,
                "case_id": item.get("case_id"),
                "prediction": item.get("prediction"),
                "excluded_parameter_keys": sorted(set(values) - set(retained)),
            }
        )
        for key, value in normalized.items():
            if value not in parameters.setdefault(key, []):
                parameters[key].append(value)
    plan = {
        "schema_version": 1,
        "name": name,
        "parameters": parameters,
        "candidates": candidates,
        "created_at": int(time.time()),
        "source": {
            "kind": ADVICE_SCHEMA,
            "advice_id": payload["advice_id"],
            "model_release_id": release["release_id"],
            "candidates": sources,
        },
    }
    plan["plan_fingerprint"] = payload_fingerprint(
        {key: value for key, value in plan.items() if key != "created_at"}
    )
    destination = safe_child(root, f"experiments/{name}")
    if destination.exists():
        raise invalid("Sweep already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".model-sweep-", dir=destination.parent))
    try:
        write_plan(staging / "sweep.json", plan)
        os.rename(staging, destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return {
        "status": "created",
        "name": name,
        "candidate_count": len(candidates),
        "safe_to_apply": False,
    }
