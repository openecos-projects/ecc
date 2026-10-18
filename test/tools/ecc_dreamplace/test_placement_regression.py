"""Placement regression evidence and parallel orchestration boundaries."""

import gzip
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from scripts.regression.placement.artifacts import validate_windows
from scripts.regression.placement.common import content_digest, digest, read, write
from scripts.regression.placement.external import parse_metrics
from scripts.regression.placement.reports import collect
from scripts.regression.placement.runner import launch
from scripts.regression.placement.verify import verify_environment


@pytest.fixture
def batch(tmp_path):
    root = Path(__file__).resolve().parents[3]
    profile = read(root / "test/regression/ics55/placement_fixed500_smooth2.json")
    write(tmp_path / "provenance.json", {"profile": profile})
    write(tmp_path / "cases_manifest.json", {"cases": [{"name": "example"}]})
    write(
        tmp_path / "cases/example/status.json",
        {"case": "example", "status": "queued", "stage": "placement"},
    )
    return tmp_path


def test_fixed_window_validation_uses_profile_and_rejects_gp_alpha(batch):
    policy = read(batch / "provenance.json")["profile"]["timing_opt_coefficients"]
    policy.update(wns=1000.0, tns=10.0)
    window = {"sizing": {"coefficients": policy | {"timing_grad_balance_weight": 1.0}}}
    validate_windows([window], policy)
    window["sizing"]["coefficients"]["timing_grad_balance_weight"] = 166.0
    with pytest.raises(ValueError, match="Fixed sizing weights changed"):
        validate_windows([window], policy)


def test_inherited_window_uses_live_weights_instead_of_retained_fixed_preset(batch):
    policy = read(batch / "provenance.json")["profile"]["timing_opt_coefficients"]
    policy["mode"] = "inherit"
    window = {
        "sizing": {
            "coefficients": {
                "mode": "inherit",
                "wns": 0.02,
                "tns": 0.0002,
                "cap": 2.0,
                "slew": 3.0,
                "timing_grad_balance_weight": 7.0,
            }
        }
    }
    validate_windows([window], policy)
    window["sizing"]["coefficients"]["wns"] = float("nan")
    with pytest.raises(ValueError, match="Invalid inherited weights"):
        validate_windows([window], policy)


def test_queued_results_stay_empty_and_report_selected_configuration(batch):
    provenance = read(batch / "provenance.json")
    provenance["profile"].update(timing_opt_sizing_rounds=5, timing_aggregation_mode="hard")
    write(batch / "provenance.json", provenance)
    summary = collect(batch)
    row = summary["rows"][0]
    assert (
        summary["counts"],
        row["internal_tns_ns"],
        row["external_placement_tns_ns"],
        row["external_gr50_tns_ns"],
    ) == (
        {"completed": 0, "failed": 0, "running": 0, "queued": 1},
        None,
        None,
        None,
    )
    table = (batch / "results.md").read_text()
    assert '"timing_opt_sizing_rounds": 5' in table
    assert '"timing_aggregation_mode": "hard"' in table
    assert "| example | — | — | — | queued: placement |" in table


def test_failed_external_gr_preserves_completed_placement_measurement(batch):
    write(
        batch / "cases/example/status.json",
        {"case": "example", "status": "failed", "stage": "external-gr50", "error": "exit 3"},
    )
    report = {
        "internal_ns": {"wns": -1.0, "tns": -100.0},
        "external_placement": {"timing_ns": {"wns": -1.1, "tns": -105.0}},
    }
    write(batch / "cases/example/placement-report.json", report)
    summary = collect(batch)
    row = summary["rows"][0]
    assert (
        summary["counts"],
        row["internal_tns_ns"],
        row["external_placement_tns_ns"],
        row["external_gr50_tns_ns"],
        row["error"],
    ) == (
        {"completed": 0, "failed": 1, "running": 0, "queued": 0},
        -100.0,
        -105.0,
        None,
        "exit 3",
    )
    assert read(batch / "cases/example/placement-report.json") == report


def test_native_process_exit_changes_stale_running_status_to_failed(batch, monkeypatch):
    out = batch / "cases/example"
    write(out / "status.json", {"case": "example", "status": "running", "stage": "placement"})
    original = subprocess.Popen

    def crash_process(command, **kwargs):
        return original([sys.executable, "-c", "raise SystemExit(3)"], **kwargs)

    monkeypatch.setattr("scripts.regression.placement.runner.subprocess.Popen", crash_process)
    assert launch(batch, {"name": "example"}) == ("example", 3)
    state = read(out / "status.json")
    assert {key: state[key] for key in ("status", "stage", "pipeline_exit")} == {
        "status": "failed",
        "stage": "placement",
        "pipeline_exit": 3,
    }
    assert (out / "pipeline.exit").read_text() == "3\n"


def test_parallel_artifact_writes_always_leave_one_complete_record(tmp_path):
    path = tmp_path / "status.json"
    records = [{"sequence": value, "payload": "x" * 10000} for value in range(32)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda value: write(path, value), records))
    assert read(path) in records
    assert sorted(item.name for item in tmp_path.iterdir()) == ["status.json"]


def test_def_content_hash_is_independent_of_gzip_timestamp(tmp_path):
    content = b"VERSION 5.8 ;\nTRACKS X 0 DO 10 STEP 100 LAYER MET2 ;\nEND DESIGN\n"
    paths = [tmp_path / "first.def.gz", tmp_path / "second.def.gz"]
    for stamp, path in enumerate(paths, start=1):
        with (
            path.open("wb") as stream,
            gzip.GzipFile(fileobj=stream, mode="wb", mtime=stamp) as writer,
        ):
            writer.write(content)
    assert digest(paths[0]) != digest(paths[1])
    assert content_digest(paths[0]) == content_digest(paths[1])


@pytest.mark.parametrize("changed", ["profile.json", "runtime/code.py", "runner/worker.py"])
def test_changed_frozen_artifact_is_rejected_before_launch(batch, changed):
    profile = read(batch / "provenance.json")["profile"]
    write(batch / "profile.json", profile)
    for filename in ("runtime/code.py", "runner/worker.py", "openroad", "run_python.sh"):
        path = batch / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("qualified artifact\n")
    write(batch / "pdk_manifest.json", {})
    provenance = {
        "profile": profile,
        "profile_sha256": digest(batch / "profile.json"),
        "runtime_file_hashes": {"code.py": digest(batch / "runtime/code.py")},
        "runner_file_hashes": {"worker.py": digest(batch / "runner/worker.py")},
        "launcher_sha256": digest(batch / "run_python.sh"),
        "openroad_binary": str(batch / "openroad"),
        "openroad_sha256": digest(batch / "openroad"),
        "evaluators": {},
    }
    write(batch / "provenance.json", provenance)
    assert verify_environment(batch) == provenance
    path = batch / changed
    path.write_text(path.read_text() + "changed\n")
    with pytest.raises(ValueError, match="changed"):
        verify_environment(batch)


def test_external_metrics_select_sta_lines_and_the_requested_evaluator():
    text = "\n".join(
        [
            "diagnostic: wns max -99.0",
            "wns max -1.000000",
            "tns max -20.000000",
            "GR_AUDIT_METRIC cap_violation_count=7",
            "PLACEMENT_AUDIT_METRIC cap_violation_count=2",
        ]
    )
    assert parse_metrics(text, "GR") == (
        {"wns": -1.0, "tns": -20.0},
        {"cap_violation_count": 7.0},
    )
