from types import SimpleNamespace
from typing import Any

import pytest

from chipcompiler.data.parameter import Parameters
from chipcompiler.data.pdk import PDK
from chipcompiler.data.workspace import Workspace
from chipcompiler.data.workspace.sdc import create_default_sdc, refresh_generated_sdc


@pytest.mark.parametrize("clock", ["core_clk", ""])
def test_generated_sdc_refresh_uses_current_parameters_and_load(tmp_path, clock):
    path = tmp_path / "constraints.sdc"
    workspace = Workspace(
        directory=tmp_path,
        pdk=PDK(name="custom", sdc=path, sdc_load=0.4),
        parameters=Parameters(data={"clock": clock, "frequency_max": 100, "max_fanout": 16}),
    )
    create_default_sdc(workspace)
    content = path.read_text()
    expected_bindings = {
        f"set clk_name      {clock or '__VIRTUAL_CLK__'}",
        "set clk_freq_mhz  100",
        "set_load 0.4 [all_outputs]",
        "set_max_fanout      16   [current_design]",
    }
    if clock:
        expected_bindings.add(f"set clk_port_name {clock}")
    assert {
        line
        for line in content.splitlines()
        if line.startswith(
            (
                "set clk_name ",
                "set clk_port_name ",
                "set clk_freq_mhz ",
                "set_load ",
                "set_max_fanout ",
            )
        )
    } == expected_bindings
    expected = (
        content.replace("set clk_freq_mhz  100\n", "set clk_freq_mhz  250.0\n")
        .replace("set_max_fanout      16   ", "set_max_fanout      48   ")
        .replace("set_load 0.4 ", "set_load 0.8 ")
    )
    if clock:
        expected = expected.replace("core_clk", "fast_clk")
        workspace.parameters.data["clock"] = "fast_clk"
    workspace.parameters.data.update(frequency_max=250.0, max_fanout=48)
    workspace.pdk.sdc_load = 0.8

    refresh_generated_sdc(workspace)

    assert path.read_text() == expected


def _ns(**kwargs: object) -> Any:
    return SimpleNamespace(**kwargs)


def test_external_generated_sdc_retains_electrical_constraints(tmp_path):
    path = tmp_path / "constraints.sdc"
    content = (
        "# Auto-generated SDC file\n"
        "create_clock -period 1.5 [get_ports clk]\n"
        "set_max_fanout 32 [current_design]\n"
        "set_load 0.001 [all_outputs]\n"
    )
    path.write_text(content)
    workspace = _ns(
        pdk=_ns(sdc=path),
        parameters=_ns(data={"clock": "clk", "frequency_max": 100}),
    )
    refresh_generated_sdc(workspace)
    assert path.read_text() == content


def test_clock_only_workspace_refresh_keeps_its_constraint_mode(tmp_path):
    path = tmp_path / "constraints.sdc"
    path.write_text("# ECC-generated clock-only SDC\nset clk_freq_mhz 100\n")
    workspace = _ns(
        pdk=_ns(sdc=path),
        parameters=_ns(data={"clock": "clk", "frequency_max": 200}),
    )

    refresh_generated_sdc(workspace)

    content = path.read_text()
    assert {
        "updated_frequency": "set clk_freq_mhz 200" in content,
        "clock": "create_clock" in content,
        "io_delays": "set_input_delay" in content or "set_output_delay" in content,
        "output_load": "set_load" in content,
    } == {
        "updated_frequency": True,
        "clock": True,
        "io_delays": False,
        "output_load": False,
    }
