import json
from pathlib import Path

from chipcompiler.data import Workspace
from chipcompiler.engine.signoff.collector import SignoffPackageCollector


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_qor_summary_issues_reads_v4_failed_gates(tmp_path):
    workspace = Workspace(directory=tmp_path)
    _write(
        tmp_path / "sta_ecc" / "analysis" / "qor_summary.json",
        {
            "schema_version": 4,
            "analysis_revision": "quality-gates-v4",
            "analysis_status": "valid",
            "quality_status": "blocked",
            "gates": [
                {
                    "id": "qor.sta.hold_closed",
                    "title": "STA hold closure",
                    "state": "failed",
                    "blocking": True,
                    "metrics": [
                        {
                            "id": "sta_hold_wns",
                            "actual": -0.121,
                            "operator": ">=",
                            "expected": 0,
                        }
                    ],
                    "evidence": [],
                }
            ],
            "missing_metrics": [],
        },
    )

    issues = SignoffPackageCollector(workspace)._qor_summary_issues(
        tmp_path,
        {"steps": [{"name": "sta", "state": "Success"}]},
    )

    assert [(issue.label, issue.required, issue.kind) for issue in issues] == [
        ("qor.sta.hold_closed", True, "analysis")
    ]
    assert issues[0].reason == "sta_hold_wns=-0.121 (required >= 0)"


def test_qor_summary_issues_keeps_v3_compatibility(tmp_path):
    workspace = Workspace(directory=tmp_path)
    _write(
        tmp_path / "drc_ecc" / "analysis" / "qor_summary.json",
        {
            "schema_version": 3,
            "analysis_revision": "quality-gates-v3",
            "status": "blocked",
            "hard_gates": [
                {
                    "id": "drc_clean",
                    "metric": "drc_count",
                    "actual": 2,
                    "threshold": 0,
                    "passed": False,
                }
            ],
            "blocking_issues": [],
            "missing_metrics": [],
        },
    )

    issues = SignoffPackageCollector(workspace)._qor_summary_issues(
        tmp_path,
        {"steps": [{"name": "drc", "state": "Success"}]},
    )

    assert [(issue.label, issue.kind) for issue in issues] == [("drc_clean", "analysis")]
