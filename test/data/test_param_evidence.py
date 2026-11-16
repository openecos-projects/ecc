"""Per-step parameter evidence: what fed a step, from where, and what the tool config holds."""

import json
from pathlib import Path
from typing import Any

from chipcompiler.data import create_workspace, load_workspace, save_parameter
from chipcompiler.data.workspace import refresh_workspace_config
from chipcompiler.params import (
    EVIDENCE_FILE,
    PARAM_SOURCES_KEY,
    lookup_schema,
    update_workspace_param_value,
    write_step_parameter_evidence,
)
from chipcompiler.params.evidence import build_step_parameter_record


def _workspace(tmp_path: Path, minimal_ics55_pdk_factory: Any, parameters: dict) -> Any:
    rtl = tmp_path / "gcd.v"
    rtl.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")
    create_workspace(
        directory=str(tmp_path / "workspace"),
        origin_def="",
        origin_verilog=str(rtl),
        pdk="ics55",
        parameters=parameters,
        pdk_root=str(minimal_ics55_pdk_factory(tmp_path / "pdk")),
    )
    workspace = load_workspace(str(tmp_path / "workspace"))
    assert workspace is not None
    return workspace


def _record(record: dict[str, Any], param: str) -> dict[str, Any]:
    return next(item for item in record["parameters"] if item["param"] == param)


def test_record_reports_value_default_and_source_per_layer(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
) -> None:
    workspace = _workspace(
        tmp_path,
        minimal_ics55_pdk_factory,
        {**default_ics55_parameters, PARAM_SOURCES_KEY: {"place.cell_padding_x": "cli"}},
    )
    schema = lookup_schema("place.target_density")
    assert schema is not None
    update_workspace_param_value(workspace, schema, 0.5)
    assert save_parameter(workspace.parameters)
    refresh_workspace_config(workspace)

    record = build_step_parameter_record(workspace, "place", "dreamplace")

    assert _record(record, "place.target_density") == {
        "param": "place.target_density",
        "value": 0.5,
        "default": 0.4,
        "source": "workspace",
    }
    assert _record(record, "place.cell_padding_x")["source"] == "cli"
    assert _record(record, "place.stop_overflow")["source"] == "default"
    assert record["config"]["dreamplace"]["target_density"] == 0.5


def test_record_covers_only_parameters_applicable_to_the_step(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
) -> None:
    workspace = _workspace(tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters)

    record = build_step_parameter_record(workspace, "CTS", "ecc")

    params = {item["param"] for item in record["parameters"]}
    assert "cts.max_fanout" in params
    assert "place.target_density" not in params
    assert record["config"]["CTS"]["max_fanout"] == 32


def test_evidence_file_is_written_beside_the_step_files(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
) -> None:
    workspace = _workspace(tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters)
    step_directory = tmp_path / "step"
    step_directory.mkdir()
    step = type("Step", (), {"name": "CTS", "tool": "ecc"})()

    assert write_step_parameter_evidence(workspace, step, step_directory)

    written = json.loads((step_directory / EVIDENCE_FILE).read_text(encoding="utf-8"))
    assert (written["step"], written["tool"]) == ("CTS", "ecc")


def test_evidence_failure_never_raises(tmp_path) -> None:
    step = type("Step", (), {"name": "CTS", "tool": "ecc"})()

    assert write_step_parameter_evidence(object(), step, tmp_path) is False
