import json
from pathlib import Path
from types import SimpleNamespace

from chipcompiler.data import StepEnum
from chipcompiler.tools.ecc_dreamplace.checklist import DreamplacePlacementChecklist


def _write(path, content="data"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _placement_checker(tmp_path, metrics):
    metrics_path = _write(
        tmp_path / "place_dreamplace" / "analysis" / "qor_metrics.json",
        json.dumps(metrics),
    )
    config_path = _write(
        tmp_path / "config" / "dreamplace.json",
        json.dumps({"target_density": 0.6, "stop_overflow": 0.1}),
    )
    output_dir = tmp_path / "place_dreamplace" / "output"
    log_path = _write(
        tmp_path / "place_dreamplace" / "log" / "place.log",
        "Start legalization\nlegalization takes 1 seconds\n",
    )
    plot_dir = tmp_path / "place_dreamplace" / "data" / "pl" / "gcd" / "plot"
    _write(plot_dir / "congestion.png")
    workspace = SimpleNamespace(
        config={"dreamplace": str(config_path)},
        design=SimpleNamespace(name="gcd"),
        home=SimpleNamespace(update_checklist=lambda **kwargs: None),
    )
    step = SimpleNamespace(
        name=StepEnum.PLACEMENT.value,
        analysis={"metrics": str(metrics_path)},
        feature={"db": str(tmp_path / "place_dreamplace" / "feature" / "place.db.json")},
        output={
            "def": str(_write(output_dir / "gcd_place.def.gz")),
            "verilog": str(_write(output_dir / "gcd_place.v.gz")),
            "gds": str(_write(output_dir / "gcd_place.gds")),
            "view_json": str(tmp_path / "place_dreamplace" / "output" / "gcd_place_view"),
        },
        data={StepEnum.PLACEMENT.value: str(tmp_path / "place_dreamplace" / "data" / "pl")},
        log={"file": str(log_path)},
        checklist={"path": str(tmp_path / "place_dreamplace" / "checklist.json")},
    )
    return DreamplacePlacementChecklist(workspace, step)


def _metric(metric_id, value):
    return {"id": metric_id, "value": value}


def test_placement_checklist_uses_v3_metrics_without_legacy_flat_keys(tmp_path):
    checker = _placement_checker(
        tmp_path,
        {
            "schema_version": 3,
            "metrics": [
                _metric("core_utilization", 0.55),
                _metric("place_congestion_egr_overflow_max", 0),
                _metric("place_congestion_egr_overflow_total", 0),
                _metric("place_hpwl", 123.4),
                _metric("place_lutrudy_utilization_max", 0.2),
                _metric("place_rudy_utilization_max", 0.1),
            ],
        },
    )

    assert checker.check() is True

    checklist = json.loads(
        Path(checker.workspace_step.checklist["path"]).read_text(encoding="utf-8")
    )
    density = next(
        item for item in checklist["checklist"] if item["item"] == "check target density"
    )
    assert density["state"] == "Passed"


def test_placement_checklist_reports_legacy_analysis_contract(tmp_path):
    checker = _placement_checker(tmp_path, {"schema_version": 2, "metrics": []})

    assert checker.check() is False

    checklist = json.loads(
        Path(checker.workspace_step.checklist["path"]).read_text(encoding="utf-8")
    )
    density = next(
        item for item in checklist["checklist"] if item["item"] == "check target density"
    )
    assert density["state"] == "Failed"
    assert density["info"] == "qor_metrics.json does not use schema_version 3"
