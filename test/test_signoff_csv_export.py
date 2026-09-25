"""Unit tests for signoff CSV spec / gate evaluate / projection / manifest.

NOTE: remove it next version — lit gates under ``test/lit/`` own this contract;
keep this pytest only until the next cleanup.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from csv_gates.compare import (
    compare_values,
    evaluate_checklist_gate,
    evaluate_metric_gate,
)
from csv_gates.manifest import MANIFEST_SCHEMA_VERSION, build_run_manifest
from csv_gates.projection import projection_lines
from csv_gates.spec import (
    ChecklistItemSpec,
    CsvSpecError,
    MetricSpec,
    load_csv_spec,
)


def _write_spec(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "spec.yml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


class TestLoadCsvSpec:
    def test_parses_metric_ops_and_checklist(self, tmp_path: Path):
        path = _write_spec(
            tmp_path,
            {
                "version": 1,
                "metrics": [{"id": "drc_count", "reference": 0, "op": "=="}],
                "checklist": [
                    {"id": "quality.drc.clean", "require_state": "pass", "require_blocked": False}
                ],
            },
        )
        spec = load_csv_spec(str(path))
        assert spec.version == 1
        assert spec.metrics == (MetricSpec(id="drc_count", reference=0, op="=="),)
        assert spec.checklist[0].id == "quality.drc.clean"
        assert spec.checklist[0].require_blocked is False

    def test_rejects_unknown_version(self, tmp_path: Path):
        path = _write_spec(tmp_path, {"version": 99, "metrics": ["drc_count"]})
        with pytest.raises(CsvSpecError, match="unsupported"):
            load_csv_spec(str(path))

    def test_rejects_bad_op(self, tmp_path: Path):
        path = _write_spec(tmp_path, {"metrics": [{"id": "x", "op": "~~", "reference": 1}]})
        with pytest.raises(CsvSpecError, match="op"):
            load_csv_spec(str(path))

    def test_rejects_duplicate_metric(self, tmp_path: Path):
        path = _write_spec(tmp_path, {"metrics": ["drc_count", "drc_count"]})
        with pytest.raises(CsvSpecError, match="duplicate"):
            load_csv_spec(str(path))

    def test_checklist_null_require_means_skip(self, tmp_path: Path):
        path = _write_spec(
            tmp_path,
            {"checklist": [{"id": "x", "require_state": None, "require_blocked": None}]},
        )
        spec = load_csv_spec(str(path))
        assert spec.checklist[0].require_state is None
        assert spec.checklist[0].require_blocked is None


class TestCompareValues:
    @pytest.mark.parametrize(
        "op,actual,ref,expected",
        [
            ("==", 0, 0, True),
            ("==", 1, 0, False),
            (">=", 0.05, 0.0, True),
            ("<", 1, 2, True),
            ("!=", "a", "b", True),
            (">", "na", 1, False),
            ("==", "", "", True),
            ("==", "", 0, False),
            (">=", "", 0, False),
            ("==", "nan", "nan", True),
            (">=", "nan", 0, False),
            ("==", True, True, True),
            (">=", True, 1, False),
            ("==", "0", 0, True),
        ],
    )
    def test_ops(self, op, actual, ref, expected):
        assert compare_values(op, actual, ref) is expected


class TestEvaluateGates:
    def test_metric_missing_is_fail(self):
        spec = MetricSpec(id="drc_count", reference=0, op="==")
        assert evaluate_metric_gate({"present": "false", "value": ""}, spec) == "fail"

    def test_metric_value_mismatch_is_fail(self):
        spec = MetricSpec(id="drc_count", reference=0, op="==")
        assert evaluate_metric_gate({"present": "true", "value": "3"}, spec) == "fail"

    def test_metric_pass(self):
        spec = MetricSpec(id="drc_count", reference=0, op="==")
        assert evaluate_metric_gate({"present": True, "value": 0}, spec) == "pass"

    def test_checklist_blocked_is_fail(self):
        spec = ChecklistItemSpec(
            id="quality.drc.clean", require_state="pass", require_blocked=False
        )
        assert (
            evaluate_checklist_gate({"present": "true", "state": "fail", "blocked": "true"}, spec)
            == "fail"
        )

    def test_checklist_pass(self):
        spec = ChecklistItemSpec(
            id="quality.drc.clean", require_state="pass", require_blocked=False
        )
        assert (
            evaluate_checklist_gate({"present": "true", "state": "pass", "blocked": "false"}, spec)
            == "pass"
        )


class TestProjection:
    def test_projection_emits_gate_lines(self, tmp_path: Path):
        csv_dir = tmp_path / "csv"
        csv_dir.mkdir()
        (csv_dir / "qor_metrics.csv").write_text(
            "step,metric_name,value,unit,scope,corner,project_role,reference,present\n"
            ",drc_count,0,,,,,,0,true\n",
            encoding="utf-8",
        )
        (csv_dir / "checklist.csv").write_text(
            "id,step,category,title,state,policy,blocked,summary,evidence,present\n"
            "quality.drc.clean,,,,pass,,false,,,true\n",
            encoding="utf-8",
        )
        spec_path = _write_spec(
            tmp_path,
            {
                "version": 1,
                "metrics": [{"id": "drc_count", "reference": 0, "op": "=="}],
                "checklist": [
                    {"id": "quality.drc.clean", "require_state": "pass", "require_blocked": False}
                ],
            },
        )
        spec = load_csv_spec(str(spec_path))
        lines = projection_lines(csv_dir, "gcd", spec=spec)
        assert any("gate metric drc_count status=pass" in line for line in lines)
        assert any("gate checklist quality.drc.clean status=pass" in line for line in lines)


class TestManifest:
    def test_schema_and_run_id(self, tmp_path: Path):
        spec = tmp_path / "s.yml"
        spec.write_text("version: 1\n", encoding="utf-8")
        manifest = build_run_manifest(
            design="gcd",
            workspace=tmp_path / "default",
            spec_path=spec,
            gates_total=2,
            gates_failed=1,
            run_id="fixed-id",
        )
        assert manifest.schema_version == MANIFEST_SCHEMA_VERSION
        assert manifest.run_id == "fixed-id"
        assert manifest.workspace_id == "default"
        assert manifest.gates_failed == 1
        assert manifest.tools["ecc"]
        assert manifest.spec_sha256
