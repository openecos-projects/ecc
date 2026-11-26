"""Report metadata must describe the library group actually selected for an RC corner."""

import json

from chipcompiler.data import OriginDesign, StepEnum, Workspace
from chipcompiler.tools.ecc.builder import build_step, build_step_space
from chipcompiler.tools.ecc.metrics import build_metrics_sta


def test_metrics_select_exact_rc_group_before_pvt_default(tmp_path):
    workspace = Workspace(directory=tmp_path, design=OriginDesign(name="core", top_module="core"))
    step = build_step(workspace, StepEnum.STA.value, input_def=None, input_verilog=None)
    build_step_space(step)
    config = tmp_path / "sta.json"
    config.write_text(
        json.dumps(
            {
                "liberty": [
                    {
                        "corner": "MIN",
                        "temperature": -40,
                        "rc_corner": "Cbest",
                        "path": ["/pdk/core_ff_1p30_m40.lib"],
                    },
                    {
                        "corner": "MIN",
                        "temperature": -40,
                        "path": ["/pdk/core_ff_1p32_m40.lib"],
                    },
                ],
                "signoff": [{"MIN": ["Cbest", "RCworst"]}],
            }
        )
    )
    workspace.config[StepEnum.STA.value] = config
    assert build_metrics_sta(workspace, step) is not None
    assert step.feature.step is not None
    signoff = json.loads(step.feature.step.read_text())["sta"]["signoff_metrics"]
    assert {
        item["sta_corner"]: (item["voltage_v"], item["process_corner"], item["availability"])
        for item in signoff["corners"]
    } == {
        "MIN_m40/Cbest": (1.3, "FF", "missing"),
        "MIN_m40/RCworst": (1.32, "FF", "missing"),
    }
