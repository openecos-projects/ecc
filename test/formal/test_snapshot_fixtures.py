"""Canonical Engineering Snapshot fixtures (ADR-0005).

The valid fixture is the cross-language contract: ECC asserts that a snapshot
generated from the deterministic synthetic workspace below matches it byte for
byte; the GUI consumes the same files read-only through the submodule pin and
asserts its validator accepts the valid fixture and rejects every invalid one.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from chipcompiler.engine.snapshot import (
    SNAPSHOT_SCHEMA_VERSION,
    EngineeringSnapshotError,
    create_engineering_snapshot,
    read_engineering_snapshot,
)

FIXTURES = Path(__file__).parent / "fixtures" / "snapshot"
VALID_FIXTURE = FIXTURES / "v6-valid.json"
INVALID_FIXTURES = {
    "v6-invalid-schema-version.json": "snapshot_rebuild_required",
    "v6-invalid-missing-workspace-id.json": "invalid Engineering Snapshot",
    "v6-invalid-artifact-absolute-reference.json": "artifact reference",
    "v6-invalid-artifact-parent-reference.json": "artifact reference",
    "v6-invalid-artifact-availability.json": "artifact reference",
}

FIXTURE_WORKSPACE_ID = "workspace-fixture-v6"


def build_fixture_workspace(root: Path) -> SimpleNamespace:
    """Deterministic synthetic workspace behind the canonical valid fixture."""
    (root / "home").mkdir(parents=True)
    steps = [
        {"name": "Synthesis", "tool": "yosys", "state": "Success"},
        {"name": "sta", "tool": "ecc", "state": "Success"},
    ]
    workspace = SimpleNamespace(
        directory=root,
        flow=SimpleNamespace(data={"steps": steps}),
        home=SimpleNamespace(data={}),
        parameters=SimpleNamespace(data={"design": "gcd", "frequency_mhz": 100.0}),
        design=SimpleNamespace(name="gcd"),
    )
    _write_json(
        root / "Synthesis_yosys" / "analysis" / "qor_metrics.json",
        {
            "schema_version": 3,
            "metrics": [
                _metric_record("synthesis_cell_area", 4200.0, "area_cost", "lower_is_better"),
                _metric_record("synthesis_power_dynamic_uw", 18.5, "power_integrity", "trend_only"),
            ],
        },
    )
    _write_json(
        root / "Synthesis_yosys" / "analysis" / "qor_summary.json",
        {
            "schema_version": 4,
            "analysis_status": "valid",
            "quality_status": "pass",
            "gates": [],
            "missing_metrics": [],
        },
    )
    _write_json(
        root / "Synthesis_yosys" / "analysis" / "qor_hotspots.json",
        {"schema_version": 3, "hotspots": []},
    )
    (root / "Synthesis_yosys" / "report").mkdir(parents=True)
    (root / "Synthesis_yosys" / "report" / "Synthesis_stat.json").write_text(
        '{"cells": 128}', encoding="utf-8"
    )
    _write_json(
        root / "sta_ecc" / "analysis" / "qor_metrics.json",
        {
            "schema_version": 3,
            "metrics": [_metric_record("sta_wns_ns", -0.05, "timing", "higher_is_better")],
        },
    )
    _write_json(
        root / "sta_ecc" / "analysis" / "qor_summary.json",
        {
            "schema_version": 4,
            "analysis_status": "valid",
            "quality_status": "fail",
            "gates": [],
            "missing_metrics": [],
        },
    )
    _write_json(
        root / "sta_ecc" / "analysis" / "qor_hotspots.json",
        {
            "schema_version": 3,
            "hotspots": [
                {
                    "kind": "routing_overflow",
                    "severity": "critical",
                    "metric_id": "route_la_total_overflow",
                    "display_name": "Route LA Overflow",
                    "value": 3,
                    "unit": "count",
                    "category": "routability_physical",
                    "source": {"kind": "metrics"},
                    "description": "Route layer assignment overflow is present.",
                },
                {
                    "kind": "congestion",
                    "severity": "warning",
                    "metric_id": "place_rudy_utilization_max",
                    "display_name": "RUDY Utilization Max",
                    "value": 0.9,
                    "unit": "ratio",
                    "category": "routability_physical",
                    "source": {"kind": "metrics"},
                    "description": "Placement RUDY utilization peak is present.",
                },
            ],
        },
    )
    _write_json(
        root / "sta_ecc" / "analysis" / "sta_timing_issues.json",
        {
            "schema_version": 1,
            "tool": "ecc",
            "step": "sta",
            "design": "gcd",
            "issues": [
                _timing_issue(slack, f"path-{index}")
                for index, slack in enumerate([-0.4, -0.3, -0.2, -0.05, -0.02, 0.01, 0.03])
            ],
        },
    )
    _write_json(
        root / "home" / "checklist.json",
        {
            "schema_version": 3,
            "kind": "signoff_checklist",
            "status": "blocked",
            "checklist": [
                {
                    "id": "synthesis.netlist",
                    "step": "Synthesis",
                    "category": "report",
                    "owner": "checklist",
                    "policy": "block",
                    "state": "pass",
                    "blocked": False,
                    "title": "Netlist generated",
                    "summary": "Synthesis netlist is available",
                    "source": {"path": "Synthesis_yosys/output/gcd_Synthesis.v"},
                    "evidence": [],
                },
                {
                    "id": "sta.timing_signoff",
                    "step": "sta",
                    "category": "timing",
                    "owner": "qor",
                    "policy": "block",
                    "state": "failed",
                    "blocked": True,
                    "title": "Timing signoff",
                    "summary": "Setup violations remain",
                    "source": {"path": "sta_ecc/analysis/sta_timing_issues.json"},
                    "evidence": [{"kind": "file", "path": "sta_ecc/report/sta.rpt"}],
                },
            ],
            "summary": {"passed": 1, "blocked": 1, "attention": 0, "unavailable": 0},
        },
    )
    return workspace


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _metric_record(metric_id, value, category, direction):
    return {
        "id": metric_id,
        "display_name": metric_id.replace("_", " ").title(),
        "value": value,
        "category": category,
        "direction": direction,
        "scope": "workspace",
        "corner": None,
        "analysis_group": "fixture_metrics",
        "rating": {"gate": False, "score": True, "trend": False},
        "project_role": "final",
        "step_role": "primary",
        "confidence": "high",
        "source": {},
    }


def _timing_issue(slack, path_id):
    return {
        "issue_id": f"sta_timing:MAX_125/RCworst:setup:{path_id}",
        "severity": "critical" if slack < 0 else "warning",
        "corner": "MAX_125/RCworst",
        "analysis_type": "setup",
        "path_group": "clk",
        "start_point": "reg_a/Q",
        "end_point": "reg_b/D",
        "launch_clock": "clk",
        "capture_clock": "clk",
        "check_type": "setup",
        "slack_ns": slack,
        "arrival_ns": 1.0,
        "required_ns": 0.5,
        "cppr_ns": 0.0,
        "launch_clock_network_delay_ns": 0.1,
        "capture_clock_network_delay_ns": 0.1,
        "clock_network_delay_delta_ns": 0.0,
        "source_file": "feature/MAX_125/RCworst/timing_paths.json",
        "dominant_stages": [{"pin": "reg_a/Q", "incremental_delay_ns": 0.4}],
    }


def test_generated_snapshot_matches_valid_fixture(tmp_path):
    workspace = build_fixture_workspace(tmp_path / "workspace")

    snapshot = create_engineering_snapshot(workspace, workspace_id=FIXTURE_WORKSPACE_ID)

    fixture_bytes = VALID_FIXTURE.read_bytes()
    on_disk = (Path(workspace.directory) / "home" / "engineering-snapshot.json").read_bytes()
    assert on_disk == fixture_bytes
    assert json.loads(fixture_bytes) == snapshot
    assert snapshot["schemaVersion"] == SNAPSHOT_SCHEMA_VERSION


@pytest.mark.parametrize(
    ("fixture_name", "match"),
    sorted(INVALID_FIXTURES.items()),
    ids=sorted(INVALID_FIXTURES),
)
def test_invalid_fixtures_are_rejected(tmp_path, fixture_name, match):
    root = tmp_path / "workspace"
    (root / "home").mkdir(parents=True)
    (root / "home" / "engineering-snapshot.json").write_bytes(
        (FIXTURES / fixture_name).read_bytes()
    )
    workspace = SimpleNamespace(directory=root)

    with pytest.raises(EngineeringSnapshotError, match=match):
        read_engineering_snapshot(workspace)
