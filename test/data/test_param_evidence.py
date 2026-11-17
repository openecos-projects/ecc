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
from chipcompiler.tools.ecc_dreamplace import builder as dreamplace_builder
from test.flow_fixture import current_flow_document


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
    workspace.flow.data = current_flow_document(
        {"name": name, "tool": tool, "state": "Unstart"}
        for name, tool in (("placement", "dreamplace"), ("diff_opt", "dreamplace"), ("cts", "ecc"))
    )
    return workspace


def _record(record: dict[str, Any], param: str) -> dict[str, Any]:
    return next(item for item in record["parameters"] if item["param"] == param)


def test_record_reports_value_default_and_source_per_layer(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
) -> None:
    workspace = _workspace(
        tmp_path,
        minimal_ics55_pdk_factory,
        {**default_ics55_parameters, PARAM_SOURCES_KEY: {"placement:place.cell_padding_x": "cli"}},
    )
    schema = lookup_schema("place.target_density")
    assert schema is not None
    update_workspace_param_value(workspace, schema, 0.5, step="placement")
    assert save_parameter(workspace.parameters)
    refresh_workspace_config(workspace)
    step = dreamplace_builder.build_step(
        workspace, "placement", input_def=tmp_path / "in.def", input_verilog=tmp_path / "in.v"
    )
    dreamplace_builder.write_step_config(workspace, step)

    record = build_step_parameter_record(workspace, "placement", "dreamplace", step.directory)

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

    record = build_step_parameter_record(workspace, "cts", "ecc")

    params = {item["param"] for item in record["parameters"]}
    assert "cts.max_fanout" in params
    assert "place.target_density" not in params
    assert record["config"]["cts"]["max_fanout"] == 32


def test_evidence_file_is_written_beside_the_step_files(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
) -> None:
    workspace = _workspace(tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters)
    step_directory = tmp_path / "step"
    step_directory.mkdir()
    step = type("Step", (), {"name": "cts", "tool": "ecc"})()

    assert write_step_parameter_evidence(workspace, step, step_directory)

    written = json.loads((step_directory / EVIDENCE_FILE).read_text(encoding="utf-8"))
    assert (written["step"], written["tool"]) == ("cts", "ecc")


def test_evidence_failure_never_raises(tmp_path) -> None:
    step = type("Step", (), {"name": "cts", "tool": "ecc"})()

    assert write_step_parameter_evidence(object(), step, tmp_path) is False


def test_record_lists_only_configs_the_step_consumes(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
) -> None:
    workspace = _workspace(tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters)

    record = build_step_parameter_record(workspace, "routing", "ecc")

    assert set(record["config"]) == {"routing", "db"}
    assert record["config"]["routing"]["RT.-bottom_routing_layer"] == "MET2"


def test_each_step_records_its_own_value_and_source(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters
) -> None:
    schema = lookup_schema("place.timing_sizing_action")
    assert schema is not None
    workspace = _workspace(
        tmp_path,
        minimal_ics55_pdk_factory,
        {
            **default_ics55_parameters,
            "step_params": {"diff_opt": {"place.timing_sizing_action": "quad"}},
            PARAM_SOURCES_KEY: {"diff_opt:place.timing_sizing_action": "ecc.toml"},
        },
    )
    update_workspace_param_value(workspace, schema, "up", step="placement")

    records = {
        step: _record(build_step_parameter_record(workspace, step, "dreamplace"), schema.param)
        for step in ("placement", "diff_opt")
    }

    assert records == {
        "placement": {
            "param": schema.param,
            "value": "up",
            "default": schema.default,
            "source": "workspace",
        },
        "diff_opt": {
            "param": schema.param,
            "value": "quad",
            "default": schema.default,
            "source": "ecc.toml",
        },
    }
