"""Each DreamPlace step resolves its own config into its step directory."""

from pathlib import Path

from chipcompiler.data import PDK, OriginDesign, SkippableStepEnum, StepEnum, Workspace
from chipcompiler.data.workspace import init_workspace_config
from chipcompiler.tools.ecc_dreamplace import builder
from chipcompiler.utility import json_read


def _workspace(tmp_path: Path, make_ics55_parameters) -> Workspace:
    workspace = Workspace(
        directory=tmp_path / "workspace",
        design=OriginDesign(name="gcd"),
        pdk=PDK(tech=Path("tech.lef"), lefs=[Path("std.lef")]),
        parameters=make_ics55_parameters(),
    )
    init_workspace_config(workspace)
    return workspace


def _step(workspace: Workspace, tmp_path: Path, name: str):
    return builder.build_step(
        workspace, name, input_def=tmp_path / "input.def", input_verilog=tmp_path / "input.v"
    )


def test_step_builds_write_their_own_configs_and_leave_the_baseline_alone(
    tmp_path, monkeypatch, make_ics55_parameters
) -> None:
    workspace = _workspace(tmp_path, make_ics55_parameters)
    baseline = workspace.config["dreamplace"].read_bytes()
    monkeypatch.setattr(builder.ecc_builder, "build_step_config", lambda *_: None)
    steps = [
        _step(workspace, tmp_path, name)
        for name in (
            StepEnum.MACRO_PLACEMENT.value,
            StepEnum.PLACEMENT.value,
            StepEnum.LEGALIZATION.value,
        )
    ]

    for step in steps:
        builder.build_step_config(workspace, step)

    configs = {
        step.name: json_read(step.directory / "config" / "dreamplace_ecc.json")["result_dir"]
        for step in steps
    }

    assert configs == {step.name: str(step.data.workdir_for(step.name)) for step in steps}
    assert workspace.config["dreamplace"].read_bytes() == baseline


def test_an_inner_legalization_owner_resolves_its_own_config(
    tmp_path, make_ics55_parameters
) -> None:
    workspace = _workspace(tmp_path, make_ics55_parameters)
    baseline = workspace.config["dreamplace"].read_bytes()
    owner = _step(workspace, tmp_path, SkippableStepEnum.TIMING_OPT.value)

    path = builder.write_step_config(workspace, owner)

    assert path == owner.directory / "config" / "dreamplace_ecc.json"
    assert path.is_file()
    assert workspace.config["dreamplace"].read_bytes() == baseline
    assert builder.effective_config_path(workspace, owner) == path
