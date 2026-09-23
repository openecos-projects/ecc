"""Verdict merge, result reading, and degraded availability for lec_dual."""

import pytest

from chipcompiler.data import LECEngineEnum
from chipcompiler.tools.lec_dual import utility

from ._helpers import _write_netlists, write_engine_result


def _outcome(engine, status, *, result="default", available=True, reason="", error=""):
    if result == "default":
        result = {"status": status} if status is not None else None
    return utility.EngineOutcome(
        engine=engine,
        available=available,
        reason=reason,
        succeeded=available and status == "proven",
        error=error,
        result=result,
    )


@pytest.mark.parametrize(
    "left_status,right_status,expected_status,expected_agreement",
    [
        ("proven", "proven", "proven", True),
        ("proven", "incomplete", "incomplete", False),
        ("incomplete", "incomplete", "incomplete", True),
        (None, "proven", "incomplete", None),
        (None, None, "incomplete", None),
    ],
)
def test_merge_matrix(left_status, right_status, expected_status, expected_agreement, tmp_path):
    golden, gate = _write_netlists(tmp_path)
    outcomes = [
        _outcome(LECEngineEnum.YOSYS_LEC, left_status),
        _outcome(LECEngineEnum.KEPLER_FORMAL, right_status),
    ]

    payload = utility.merge_outcomes(outcomes, golden_verilog=golden, gate_verilog=gate)

    assert payload["status"] == expected_status
    assert payload["agreement"] is expected_agreement


def test_merge_carries_the_single_engine_contract_over_the_shared_inputs(tmp_path):
    from chipcompiler.utility import file_digest

    golden, gate = _write_netlists(tmp_path)
    golden_sha, golden_size = file_digest(golden)
    gate_sha, gate_size = file_digest(gate)
    outcomes = [
        _outcome(LECEngineEnum.YOSYS_LEC, "proven"),
        _outcome(LECEngineEnum.KEPLER_FORMAL, "proven"),
    ]

    payload = utility.merge_outcomes(outcomes, golden_verilog=golden, gate_verilog=gate)

    assert payload == {
        "status": "proven",
        "golden_verilog": str(golden),
        "gate_verilog": str(gate),
        "golden_sha256": golden_sha,
        "gate_sha256": gate_sha,
        "golden_size_bytes": golden_size,
        "gate_size_bytes": gate_size,
        "engines": {
            "yosys_lec": {"status": "proven"},
            "kepler_formal": {"status": "proven"},
        },
        "agreement": True,
    }


def test_merge_never_reports_proven_when_any_engine_did_not_prove(tmp_path):
    golden, gate = _write_netlists(tmp_path)
    outcomes = [
        _outcome(LECEngineEnum.YOSYS_LEC, "proven"),
        _outcome(
            LECEngineEnum.KEPLER_FORMAL,
            None,
            available=False,
            reason="kepler-formal is not installed",
        ),
    ]

    payload = utility.merge_outcomes(outcomes, golden_verilog=golden, gate_verilog=gate)

    assert payload["status"] == "incomplete"
    assert payload["agreement"] is None
    assert payload["engines"]["kepler_formal"] == {
        "status": "unavailable",
        "reason": "kepler-formal is not installed",
    }
    assert payload["engines"]["yosys_lec"] == {"status": "proven"}


def test_merge_records_the_prep_difference_on_disagreement(tmp_path):
    golden, gate = _write_netlists(tmp_path)
    outcomes = [
        _outcome(LECEngineEnum.YOSYS_LEC, "proven"),
        _outcome(LECEngineEnum.KEPLER_FORMAL, "incomplete"),
    ]

    payload = utility.merge_outcomes(outcomes, golden_verilog=golden, gate_verilog=gate)

    assert payload["agreement"] is False
    note = payload["disagreement_note"]
    assert "kepler_formal" in note
    assert "physical cells" in note
    assert "yosys_lec" in note

    agreeing = utility.merge_outcomes(
        [
            _outcome(LECEngineEnum.YOSYS_LEC, "proven"),
            _outcome(LECEngineEnum.KEPLER_FORMAL, "proven"),
        ],
        golden_verilog=golden,
        gate_verilog=gate,
    )
    assert "disagreement_note" not in agreeing


def test_engine_error_is_recorded_in_the_engines_map(tmp_path):
    golden, gate = _write_netlists(tmp_path)
    outcomes = [
        _outcome(LECEngineEnum.YOSYS_LEC, None, error="yosys exploded"),
        _outcome(LECEngineEnum.KEPLER_FORMAL, "proven"),
    ]

    payload = utility.merge_outcomes(outcomes, golden_verilog=golden, gate_verilog=gate)

    assert payload["status"] == "incomplete"
    assert payload["agreement"] is None
    assert payload["engines"]["yosys_lec"] == {
        "status": "incomplete",
        "error": "yosys exploded",
    }


def test_read_engine_result_distinguishes_missing_unparseable_and_valid(tmp_path):
    result_path = tmp_path / "result.json"
    assert utility.read_engine_result(result_path) is None
    assert utility.read_engine_result(None) is None

    result_path.write_text("not json at all\n")
    assert utility.read_engine_result(result_path) is None

    # A payload without the contract's status key is not parseable evidence.
    result_path.write_text("{}\n")
    assert utility.read_engine_result(result_path) is None

    write_engine_result(result_path, proven=True)
    assert utility.read_engine_result(result_path) == {"status": "proven"}


def test_is_eda_exist_requires_at_least_one_engine(monkeypatch):
    availability = {
        LECEngineEnum.YOSYS_LEC: (False, "no yosys"),
        LECEngineEnum.KEPLER_FORMAL: (False, "no kepler"),
    }
    monkeypatch.setattr(utility, "engine_availability", lambda engine: availability[engine])

    with pytest.raises(RuntimeError, match="no yosys.*no kepler"):
        utility.is_eda_exist()

    availability[LECEngineEnum.KEPLER_FORMAL] = (True, "")
    assert utility.is_eda_exist() is True
