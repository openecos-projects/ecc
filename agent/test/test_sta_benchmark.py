import json

import pytest

from agent.sta_benchmark import _compare, _inventory, _metric_payload


def test_benchmark_comparison_preserves_counts_and_coverage():
    original = {"corner-a": {"wns": 1.0, "nvp": 2}, "power": [0.5]}
    _compare(original, {"corner-a": {"wns": 1.0 + 1e-10, "nvp": 2}, "power": [0.5]})
    for changed in (
        {"corner-a": {"wns": 1.1, "nvp": 2}, "power": [0.5]},
        {"corner-a": {"wns": 1.0, "nvp": 3}, "power": [0.5]},
        {"corner-a": {"wns": float("nan"), "nvp": 2}, "power": [0.5]},
        {"power": [0.5]},
    ):
        with pytest.raises(ValueError):
            _compare(original, changed)


def test_benchmark_inventory_excludes_candidates_and_detects_change(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "input").write_text("old")
    (source / ".agent").mkdir()
    (source / ".agent/ignored").write_text("ignored")
    before = _inventory(source)
    assert set(before) == {"input"}
    (source / "input").write_text("new")
    assert before != _inventory(source)


def test_benchmark_inventory_rejects_directory_symlinks(tmp_path):
    (tmp_path / "link").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="directory symlink"):
        _inventory(tmp_path)


def test_benchmark_requires_complete_power_and_timing_coverage(tmp_path):
    metrics = {
        "sta_expected_corner_count": 1,
        "sta_corner_count": 1,
        "sta_missing_corner_count": 0,
    }
    for stage in ("sta_ecc", "Harden_ecc"):
        root = tmp_path / stage
        (root / "analysis").mkdir(parents=True)
        (root / "analysis/qor_metrics.json").write_text(
            json.dumps({"metrics": [{"id": key, "value": value} for key, value in metrics.items()]})
        )
        (root / "checklist.json").write_text('{"checklist": []}')
    corner = tmp_path / "sta_ecc/feature/MAX/RCworst"
    corner.mkdir(parents=True)
    (corner / "qor_summary.json").write_text("{}")
    with pytest.raises(ValueError, match="coverage is incomplete"):
        _metric_payload(tmp_path)
    (corner / "power_summary.json").write_text("{}")
    assert _metric_payload(tmp_path)["sta_ecc/metrics"] == metrics
