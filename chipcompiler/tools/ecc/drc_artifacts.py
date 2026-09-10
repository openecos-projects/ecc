"""Translation between iDRC output and ECC's DRC feature schema."""

from pathlib import Path

from chipcompiler.data import EccStep, StepEnum
from chipcompiler.utility import json_read, json_write


def save_drc_feature(step: EccStep) -> bool:
    data_dir = (step.data.steps or {}).get(StepEnum.DRC.value)
    feature_path = step.feature.step
    if data_dir is None or feature_path is None:
        return False

    violation_map_path = Path(data_dir) / "violation_map.json"
    violations = json_read(violation_map_path)
    if not violation_map_path.is_file() or not isinstance(violations, list):
        return False

    distribution = {}
    for violation in violations:
        if not isinstance(violation, dict):
            return False
        violation_type = violation.get("type")
        shape = violation.get("shape")
        if (
            not isinstance(violation_type, str)
            or not violation_type
            or not isinstance(shape, list)
            or len(shape) < 5
            or not isinstance(shape[4], str)
            or not shape[4]
        ):
            return False

        layers = distribution.setdefault(violation_type, {"layers": {}})["layers"]
        layer = layers.setdefault(shape[4], {"number": 0})
        layer["number"] += 1

    return json_write(
        feature_path,
        {"drc": {"number": len(violations), "distribution": distribution}},
    )
