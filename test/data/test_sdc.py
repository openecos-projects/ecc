from types import SimpleNamespace
from typing import Any

from chipcompiler.data.workspace.sdc import refresh_generated_sdc


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
