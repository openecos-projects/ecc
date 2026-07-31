import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from chipcompiler.data.candidate_contract import (
    CandidateStepContractError,
    validate_candidate_step_contract,
)
from chipcompiler.data.candidate_input_binding import bind_candidate_input
from chipcompiler.data.candidate_materialization import materialize_candidate_config


class _Flow:
    def __init__(self, *steps):
        self._steps = {step.name: step for step in steps}

    def get_workspace_step(self, name):
        return self._steps.get(name)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _workspace(tmp_path: Path):
    cts_config = tmp_path / "config" / "cts_default_config.json"
    _write_json(cts_config, {"skew_bound": 0.08})
    parameters = tmp_path / "home" / "parameters.json"
    _write_json(parameters, {"Core": {"Utilitization": 0.6}})
    source_dir = tmp_path / "legalization_dreamplace" / "output"
    source_dir.mkdir(parents=True)
    source_def = source_dir / "gcd_legalization.def.gz"
    source_def.write_text("DEF legalization\n", encoding="utf-8")
    source_verilog = source_dir / "gcd_legalization.v.gz"
    source_verilog.write_text("VERILOG legalization\n", encoding="utf-8")
    source_db = source_dir / "gcd_legalization_db"
    source_db.mkdir()
    (source_db / "manifest").write_text("DB legalization\n", encoding="utf-8")
    legalization = SimpleNamespace(
        name="legalization",
        input={},
        output={"def": source_def, "verilog": source_verilog, "db": source_db},
    )
    cts = SimpleNamespace(name="CTS", input={}, output={})
    workspace = SimpleNamespace(
        directory=str(tmp_path),
        config={"CTS": cts_config},
        pdk=SimpleNamespace(buffers=[]),
        parameters=SimpleNamespace(path=parameters),
        flow=SimpleNamespace(
            data={
                "steps": [
                    {"name": "CTS", "tool": "ecc"},
                    {"name": "legalization", "tool": "dreamplace"},
                ]
            }
        ),
    )
    return workspace, _Flow(cts, legalization)


def test_matching_candidate_receipts_are_accepted(tmp_path):
    workspace, flow = _workspace(tmp_path)
    materialize_candidate_config(
        workspace,
        "CTS",
        [{"knob_id": "cts.skew_bound", "value": 0.1}],
        candidate_id="cts-candidate-001",
    )
    bind_candidate_input(
        workspace,
        flow,
        "CTS",
        "legalization",
        candidate_id="cts-candidate-001",
    )

    assert validate_candidate_step_contract(workspace, "CTS") == "cts-candidate-001"


def test_parameter_candidate_requires_a_bound_upstream_checkpoint(tmp_path):
    workspace, _flow = _workspace(tmp_path)
    materialize_candidate_config(
        workspace,
        "CTS",
        [{"knob_id": "cts.skew_bound", "value": 0.1}],
        candidate_id="cts-candidate-001",
    )

    with pytest.raises(CandidateStepContractError, match="requires a bound upstream checkpoint"):
        validate_candidate_step_contract(workspace, "CTS")


def test_mismatched_candidate_receipts_are_rejected(tmp_path):
    workspace, flow = _workspace(tmp_path)
    materialize_candidate_config(
        workspace,
        "CTS",
        [{"knob_id": "cts.skew_bound", "value": 0.1}],
        candidate_id="cts-config-001",
    )
    bind_candidate_input(
        workspace,
        flow,
        "CTS",
        "legalization",
        candidate_id="cts-input-001",
    )

    with pytest.raises(CandidateStepContractError, match="candidate receipt mismatch"):
        validate_candidate_step_contract(workspace, "CTS")


def test_parameter_candidate_rejects_materialized_config_drift_before_run_step(tmp_path):
    workspace, flow = _workspace(tmp_path)
    materialize_candidate_config(
        workspace,
        "CTS",
        [{"knob_id": "cts.skew_bound", "value": 0.1}],
        candidate_id="cts-candidate-001",
    )
    bind_candidate_input(
        workspace,
        flow,
        "CTS",
        "legalization",
        candidate_id="cts-candidate-001",
    )
    _write_json(Path(workspace.config["CTS"]), {"skew_bound": 0.2})

    with pytest.raises(CandidateStepContractError, match="materialized candidate config drift"):
        validate_candidate_step_contract(workspace, "CTS")


def test_bound_candidate_input_rejects_backend_drift_without_patch(tmp_path):
    workspace, flow = _workspace(tmp_path)
    bind_candidate_input(
        workspace,
        flow,
        "CTS",
        "legalization",
        candidate_id="cts-fixed-candidate",
    )
    cts_flow_step = next(step for step in workspace.flow.data["steps"] if step["name"] == "CTS")
    cts_flow_step["tool"] = "dreamplace"

    with pytest.raises(CandidateStepContractError, match="candidate backend is unavailable"):
        validate_candidate_step_contract(workspace, "CTS")
