import csv
import importlib.util
import json
from pathlib import Path

import pytest

MODEL_PATH = Path(__file__).parents[1] / "nix" / "scripts" / "signoff_csv" / "frequency_model.py"
SPEC = importlib.util.spec_from_file_location("frequency_model_lite", MODEL_PATH)
assert SPEC is not None
frequency_model = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(frequency_model)


def _sta(target=200, achieved="195.5"):
    return {
        "design": "gcd",
        "metrics": [
            {"id": "sta_target_frequency_mhz", "value": target},
            {"id": "sta_frequency_mhz", "value": achieved},
        ],
    }


def _run(candidate, phase, run_id, status="pass", coverage="pass"):
    return {
        "candidate_mhz": str(candidate),
        "phase": phase,
        "run_id": run_id,
        "base_id": "gcd-base-v1",
        "status": status,
        "coverage_status": coverage,
    }


def _payload(runs, **overrides):
    params = {
        "pll_refclk_mhz": "20",
        "pll_bypass": False,
        "frequency_min_mhz": "150",
        "frequency_max_mhz": "200",
        "guardband_frequency_ratio": "0.05",
    }
    params.update(overrides.pop("params", {}))
    payload = {
        "schema_version": 1,
        "kind": "frequency_run_results",
        "design": "gcd",
        "base_id": "gcd-base-v1",
        "evidence_mode": "fixture",
        "params": params,
        "runs": runs,
    }
    payload.update(overrides)
    return payload


def _rows(payload, sta=None):
    request = frequency_model._request(payload, (sta or _sta())["design"])
    return {row["metric"]: row for row in frequency_model.build_rows(sta or _sta(), request)}


def test_pll_enumeration_is_exact_unique_and_deterministic():
    candidates = frequency_model.enumerate_candidates(frequency_model.Fraction(20), bypass=False)
    assert candidates == frequency_model.enumerate_candidates(
        frequency_model.Fraction(20), bypass=False
    )
    assert all(candidate.mode == "pll" for candidate in candidates)
    assert all(500 <= candidate.vco <= 1200 for candidate in candidates)
    assert all(17 <= candidate.n <= 255 for candidate in candidates)
    assert all(candidate.select in (0, 1) for candidate in candidates)
    assert all(candidate.divider in (1, 2, 4, 8) for candidate in candidates)
    frequencies = [candidate.frequency for candidate in candidates]
    assert frequencies == sorted(frequencies, reverse=True)
    assert len(frequencies) == len(set(frequencies))


def test_chapter_example_verifies_190_and_recommends_180():
    rows = _rows(
        _payload(
            [
                _run(200, "verification", "v200", "fail"),
                _run(195, "verification", "v195", "fail"),
                _run(190, "verification", "v190"),
                _run(180, "guardband", "g180"),
            ]
        )
    )
    assert rows["target_frequency_mhz"]["value"] == "200"
    assert rows["achieved_fmax_mhz"]["value"] == "195.5"
    assert rows["verified_frequency_mhz"]["value"] == "190"
    assert rows["guard_limit_mhz"]["value"] == "180.5"
    assert rows["recommended_frequency_mhz"]["value"] == "180"
    assert rows["recommended_frequency_mhz"]["status"] == "pass"
    assert rows["recommended_frequency_mhz"]["run_id"] == "g180"
    assert rows["recommended_frequency_mhz"]["detail"] == "g_f=0.05"
    assert rows["pll_output_frequency_mhz"]["value"] == "180"
    assert rows["n"]["value"] == "18"
    assert rows["select"]["value"] == "1"
    assert rows["od_code"]["value"] == "10"
    assert rows["output_divider"]["value"] == "4"
    assert rows["vco_mhz"]["value"] == "720"
    assert all(row["evidence_mode"] == "fixture" for row in rows.values())


def test_failed_higher_candidate_does_not_assume_monotonicity():
    rows = _rows(
        _payload(
            [
                _run(200, "verification", "v200", "fail"),
                _run(195, "verification", "v195"),
                _run(195, "guardband", "g195"),
            ],
            params={"guardband_frequency_ratio": "0"},
        )
    )
    assert rows["verified_frequency_mhz"]["value"] == "195"
    assert rows["recommended_frequency_mhz"]["value"] == "195"


def test_unknown_higher_candidate_blocks_lower_pass():
    rows = _rows(
        _payload(
            [
                _run(200, "verification", "v200", "unknown"),
                _run(195, "verification", "v195"),
            ]
        )
    )
    assert rows["verified_frequency_mhz"]["status"] == "incomplete_evidence"
    assert rows["verified_frequency_mhz"]["value"] == ""
    assert rows["recommended_frequency_mhz"]["status"] == "incomplete_evidence"
    assert rows["recommended_frequency_mhz"]["detail"] == "higher_candidate_unknown"


def test_missing_higher_run_is_unknown_not_a_pass():
    rows = _rows(_payload([_run(195, "verification", "v195")]))
    assert rows["verified_frequency_mhz"]["status"] == "incomplete_evidence"
    assert rows["recommended_frequency_mhz"]["value"] == ""


@pytest.mark.parametrize("status", ["pass", "fail"])
def test_unknown_coverage_cannot_promote_a_candidate(status):
    rows = _rows(
        _payload(
            [
                _run(200, "verification", "v200", status, "unknown"),
                _run(195, "verification", "v195"),
            ]
        )
    )
    assert rows["verified_frequency_mhz"]["status"] == "incomplete_evidence"
    assert rows["recommended_frequency_mhz"]["value"] == ""


def test_guardband_failure_promotes_next_lower_pass():
    rows = _rows(
        _payload(
            [
                _run(200, "verification", "v200", "fail"),
                _run(195, "verification", "v195", "fail"),
                _run(190, "verification", "v190"),
                _run(180, "guardband", "g180", "fail"),
                _run(175, "guardband", "g175"),
            ]
        )
    )
    assert rows["verified_frequency_mhz"]["value"] == "190"
    assert rows["recommended_frequency_mhz"]["value"] == "175"
    assert rows["recommended_frequency_mhz"]["run_id"] == "g175"


def test_guardband_unknown_blocks_lower_pass():
    rows = _rows(
        _payload(
            [
                _run(200, "verification", "v200", "fail"),
                _run(195, "verification", "v195", "fail"),
                _run(190, "verification", "v190"),
                _run(180, "guardband", "g180", "unknown"),
                _run(175, "guardband", "g175"),
            ]
        )
    )
    assert rows["recommended_frequency_mhz"]["status"] == "incomplete_evidence"
    assert rows["recommended_frequency_mhz"]["detail"] == "guardband_higher_unknown"
    assert rows["recommended_frequency_mhz"]["value"] == ""


def test_zero_guardband_still_requires_an_independent_run():
    payload = _payload(
        [
            _run(200, "verification", "v200", "fail"),
            _run(195, "verification", "v195", "fail"),
            _run(190, "verification", "shared"),
            _run(190, "guardband", "shared"),
        ],
        params={"guardband_frequency_ratio": "0"},
    )
    with pytest.raises(ValueError, match="unique"):
        frequency_model._request(payload, "gcd")


def test_zero_guardband_accepts_distinct_run_at_same_candidate():
    rows = _rows(
        _payload(
            [
                _run(200, "verification", "v200", "fail"),
                _run(195, "verification", "v195", "fail"),
                _run(190, "verification", "v190"),
                _run(190, "guardband", "g190"),
            ],
            params={"guardband_frequency_ratio": "0"},
        )
    )
    assert rows["recommended_frequency_mhz"]["value"] == "190"
    assert rows["recommended_frequency_mhz"]["run_id"] == "g190"


def test_time_guardband_uses_period_domain_and_rechecks_candidate():
    payload = _payload(
        [
            _run(200, "verification", "v200", "fail"),
            _run(195, "verification", "v195", "fail"),
            _run(190, "verification", "v190"),
            _run(155, "guardband", "g155"),
        ]
    )
    del payload["params"]["guardband_frequency_ratio"]
    payload["params"]["guardband_time_ns"] = "1"
    rows = _rows(payload)
    assert rows["recommended_frequency_mhz"]["value"] == "155"
    assert rows["recommended_frequency_mhz"]["run_id"] == "g155"
    assert rows["recommended_frequency_mhz"]["detail"] == "time_guard_ns=1"
    assert rows["time_domain_ns"]["status"] == "pass"
    assert rows["frequency_domain_ratio"]["status"] == "unavailable"


def test_bypass_has_no_fake_pll_sentinels():
    rows = _rows(
        _payload(
            [
                _run(20, "verification", "v20"),
                _run(20, "guardband", "g20"),
            ],
            params={
                "pll_bypass": True,
                "frequency_min_mhz": "0",
                "guardband_frequency_ratio": "0",
            },
        )
    )
    assert rows["recommended_frequency_mhz"]["value"] == "20"
    assert rows["mode"]["value"] == "bypass"
    for metric in ("n", "select", "od_code", "output_divider", "vco_mhz"):
        assert rows[metric]["value"] == ""
        assert rows[metric]["status"] == "unavailable"
        assert rows[metric]["detail"] == "bypass_mode"


def test_boolean_native_target_is_unavailable():
    rows = _rows(_payload([]), sta=_sta(target=True))
    assert rows["target_frequency_mhz"]["status"] == "unavailable"
    assert rows["recommended_frequency_mhz"]["status"] == "unavailable"
    assert rows["recommended_frequency_mhz"]["detail"] == "target_unavailable"


@pytest.mark.parametrize(
    "mutation,match",
    [
        ({"design": "other"}, "identity"),
        ({"evidence_mode": "unknown"}, "evidence_mode"),
        ({"params": {"pll_bypass": 1}}, "boolean"),
        ({"params": {"guardband_time_ns": "1"}}, "mutually exclusive"),
    ],
)
def test_invalid_request_is_fail_closed(mutation, match):
    payload = _payload([], **mutation)
    with pytest.raises(ValueError, match=match):
        frequency_model._request(payload, "gcd")


def test_duplicate_run_id_is_rejected():
    payload = _payload(
        [
            _run(200, "verification", "duplicate"),
            _run(195, "verification", "duplicate"),
        ]
    )
    with pytest.raises(ValueError, match="unique"):
        frequency_model._request(payload, "gcd")


def test_cli_writes_compact_csv_when_input_is_missing(tmp_path, monkeypatch):
    sta_path = tmp_path / "qor_metrics.json"
    output = tmp_path / "frequency.csv"
    sta_path.write_text(json.dumps(_sta()), encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "frequency_model.py",
            "--input",
            str(tmp_path / "missing.json"),
            "--sta-metrics",
            str(sta_path),
            "--output",
            str(output),
        ],
    )
    assert frequency_model.main() == 0
    with output.open(newline="", encoding="utf-8") as stream:
        rows = {row["metric"]: row for row in csv.DictReader(stream)}
    assert rows["target_frequency_mhz"]["value"] == "200"
    assert rows["recommended_frequency_mhz"]["status"] == "unavailable"
    assert rows["recommended_frequency_mhz"]["detail"] == "frequency_input_missing"
