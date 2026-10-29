import json
from pathlib import Path

import pytest

from chipcompiler.data import SkippableStepEnum, StepEnum
from chipcompiler.data.workspace.sdc import create_default_sdc
from chipcompiler.tools.ecc import runner as ecc_runner
from chipcompiler.tools.ecc_sizer import builder

from ._sizer_helpers import _sizer_runtime, _workspace


@pytest.mark.parametrize(
    "step_name,phase_dir",
    [
        (StepEnum.PREPLACE.value, "pre_CTS"),
        (SkippableStepEnum.TIMING_OPT.value, "post_CTS"),
    ],
)
def test_setup_and_hold_commands_share_typical_constraints_for_the_stage(
    tmp_path, monkeypatch, step_name, phase_dir
):
    runtime = _sizer_runtime(tmp_path)
    monkeypatch.setenv("CHIPCOMPILER_ECC_SIZER_ROOT", str(runtime))
    workspace = _workspace(tmp_path)
    origin = workspace.directory / "origin"
    origin.mkdir(parents=True)
    workspace.pdk.sdc = origin / "gcd.sdc"
    create_default_sdc(workspace)
    template = Path(ecc_runner.__file__).parent / "configs" / "sta_ecc.json"
    config = json.loads(template.read_text())
    config_path = workspace.directory / "config" / "sta_ecc.json"
    config_path.parent.mkdir()
    config_path.write_text(json.dumps(config))
    workspace.config[StepEnum.STA.value] = config_path
    workspace.pdk.libs = [Path(path) for path in config["liberty"][0]["path"]]
    step = builder.build_step(workspace, step_name, input_def=None, input_verilog=None)
    builder.build_step_space(step)
    builder.build_step_config(workspace, step)

    assert step.script.sizer_cmd is not None
    assert step.script.sizer_hold_cmd is not None
    assert [
        line
        for path in (step.script.sizer_cmd, step.script.sizer_hold_cmd)
        for line in path.read_text().splitlines()
        if line.startswith("-sdc ")
    ] == [
        f"-sdc {origin / phase_dir / 'TYP_25_TYPICAL.tcl'}",
        f"-sdc {origin / phase_dir / 'TYP_25_TYPICAL.tcl'}",
    ]
