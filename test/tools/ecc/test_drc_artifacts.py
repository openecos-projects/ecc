import json

from chipcompiler.data import EccData, EccFeature, EccStep, StepEnum
from chipcompiler.tools.ecc.drc_artifacts import save_drc_feature


def test_save_drc_feature_groups_native_violations_by_rule_and_layer(tmp_path):
    data_dir = tmp_path / "drc_ecc" / "data" / "drc"
    feature_path = tmp_path / "drc_ecc" / "feature" / "drc.step.json"
    data_dir.mkdir(parents=True)
    feature_path.parent.mkdir(parents=True)
    (data_dir / "violation_map.json").write_text(
        json.dumps(
            [
                {"type": "MinimumSpacing", "shape": [1, 2, 3, 4, "MET3"]},
                {"type": "MinimumSpacing", "shape": [5, 6, 7, 8, "MET3"]},
                {"type": "Short", "shape": [9, 10, 11, 12, "MET2"]},
            ]
        ),
        encoding="utf-8",
    )
    step = EccStep(
        name=StepEnum.DRC.value,
        data=EccData(steps={StepEnum.DRC.value: data_dir}),
        feature=EccFeature(step=feature_path),
    )

    assert save_drc_feature(step) is True
    assert json.loads(feature_path.read_text(encoding="utf-8")) == {
        "drc": {
            "number": 3,
            "distribution": {
                "MinimumSpacing": {"layers": {"MET3": {"number": 2}}},
                "Short": {"layers": {"MET2": {"number": 1}}},
            },
        }
    }
