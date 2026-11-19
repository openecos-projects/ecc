"""Each DreamPlace step resolves its own config into its step directory."""

from pathlib import Path
from types import SimpleNamespace

from chipcompiler.data import PDK, OriginDesign, SkippableStepEnum, StepEnum, Workspace
from chipcompiler.data.workspace import init_workspace_config
from chipcompiler.data.workspace.config_manifest import (
    derived_config_manifest_path,
    modified_derived_configs,
    record_derived_config,
)
from chipcompiler.tools.ecc_dreamplace import builder
from chipcompiler.tools.ecc_dreamplace.module import DreamplaceModule
from chipcompiler.tools.ecc_dreamplace.run_modes import (
    GEOMETRY_ONLY_CONFIG,
    MODE_FLAGS,
    DreamplaceRunMode,
)
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
        step.name: json_read(builder.step_config_path(workspace, step))["result_dir"]
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

    assert owner.directory is not None
    assert path == owner.directory / "config" / "dreamplace_ecc.json"
    assert path.is_file()
    assert workspace.config["dreamplace"].read_bytes() == baseline
    assert builder.effective_config_path(workspace, owner) == path


def test_a_step_value_reaches_only_its_own_step_config(
    tmp_path, monkeypatch, make_ics55_parameters
) -> None:
    workspace = _workspace(tmp_path, make_ics55_parameters)
    workspace.parameters.data["step_params"] = {"placement": {"place.target_density": 0.71}}
    baseline = json_read(workspace.config["dreamplace"])
    monkeypatch.setattr(builder.ecc_builder, "build_step_config", lambda *_: None)
    steps = [
        _step(workspace, tmp_path, name)
        for name in (StepEnum.PLACEMENT.value, StepEnum.MACRO_PLACEMENT.value)
    ]

    for step in steps:
        builder.build_step_config(workspace, step)

    assert {
        step.name: json_read(builder.step_config_path(workspace, step))["target_density"]
        for step in steps
    } == {
        StepEnum.PLACEMENT.value: 0.71,
        StepEnum.MACRO_PLACEMENT.value: baseline["target_density"],
    }
    assert json_read(workspace.config["dreamplace"]) == baseline


def test_placement_and_diff_opt_keep_distinct_actions_through_profile_expansion(
    tmp_path, monkeypatch, make_ics55_parameters
) -> None:
    workspace = _workspace(tmp_path, make_ics55_parameters)
    workspace.parameters.data["step_params"] = {
        "placement": {"place.timing_sizing_action": "up"},
        "diff_opt": {"place.timing_sizing_action": "quad"},
    }
    record_derived_config(workspace)
    manifest = derived_config_manifest_path(workspace.directory).read_bytes()
    monkeypatch.setattr(builder.ecc_builder, "build_step_config", lambda *_: None)
    # The drive table needs real buffer Liberty data; its path is all the profile checks.
    monkeypatch.setattr(
        builder,
        "prepare_diff_opt_drive_table",
        lambda _workspace, _step, params: params
        | {"buffering_candidate_drive_strength_table": "generated.json"},
    )
    steps = [
        _step(workspace, tmp_path, name)
        for name in (StepEnum.PLACEMENT.value, SkippableStepEnum.DIFF_OPT.value)
    ]

    for step in steps:
        builder.build_step_config(workspace, step)

    # Both configs are resolved through ``resolve_flow_config``; the explicit
    # step value is replayed over the profile defaults.
    assert {
        step.name: json_read(builder.step_config_path(workspace, step))["timing_sizing_action"]
        for step in steps
    } == {StepEnum.PLACEMENT.value: "up", SkippableStepEnum.DIFF_OPT.value: "quad"}
    assert modified_derived_configs(workspace.directory) == []
    assert derived_config_manifest_path(workspace.directory).read_bytes() == manifest


def test_geometry_only_steps_persist_the_settings_their_mode_forces(
    tmp_path, monkeypatch, make_ics55_parameters
) -> None:
    workspace = _workspace(tmp_path, make_ics55_parameters)
    monkeypatch.setattr(builder.ecc_builder, "build_step_config", lambda *_: None)
    modes = {
        StepEnum.MACRO_PLACEMENT.value: DreamplaceRunMode.MACRO_PLACEMENT,
        StepEnum.LEGALIZATION.value: DreamplaceRunMode.LEGALIZATION,
        SkippableStepEnum.TIMING_OPT.value: DreamplaceRunMode.LEGALIZATION,
    }

    persisted = {}
    for name in modes:
        step = _step(workspace, tmp_path, name)
        builder.write_step_config(workspace, step)
        config = json_read(builder.step_config_path(workspace, step))
        persisted[name] = {key: config[key] for key in config if key in _forced_keys(modes[name])}

    assert persisted == {
        name: {**GEOMETRY_ONLY_CONFIG, **MODE_FLAGS[mode]} for name, mode in modes.items()
    }


def _forced_keys(mode: DreamplaceRunMode) -> set[str]:
    return {*GEOMETRY_ONLY_CONFIG, *MODE_FLAGS[mode]}


def test_an_inner_legalization_runs_on_its_owner_step_file(
    tmp_path, monkeypatch, make_ics55_parameters
) -> None:
    from chipcompiler.tools.ecc_dreamplace import runner

    workspace = _workspace(tmp_path, make_ics55_parameters)
    owner = _step(workspace, tmp_path, SkippableStepEnum.TIMING_OPT.value)
    workspace.parameters.data["step_params"] = {"placement": {"place.target_density": 0.71}}
    engine = SimpleNamespace(close=lambda: None)
    loaded = []

    def record_legalization(module: DreamplaceModule) -> bool:
        params = module._build_params(_Params, mode=DreamplaceRunMode.LEGALIZATION)
        loaded.append(
            (
                module.param_path,
                params.target_density,
                params.global_place_flag,
                params.detailed_place_flag,
            )
        )
        return True

    monkeypatch.setattr(runner, "is_eda_exist", lambda: True)
    monkeypatch.setattr(runner.ecc_runner, "create_db_engine", lambda *_args: engine)
    monkeypatch.setattr(DreamplaceModule, "run_legalization", record_legalization)

    assert owner.directory is not None
    path = owner.directory / "config" / "dreamplace_ecc.json"
    assert not path.exists()
    record_derived_config(workspace)
    baseline = workspace.config["dreamplace"].read_bytes()
    manifest = derived_config_manifest_path(workspace.directory).read_bytes()

    result = runner.legalize_layout(
        workspace, owner, tmp_path / "sizer.def.gz", tmp_path / "sizer.v.gz"
    )

    baseline_density = json_read(workspace.config["dreamplace"])["target_density"]
    # The run resolves and executes on the owner's step file only.
    assert workspace.config["dreamplace"].read_bytes() == baseline
    assert derived_config_manifest_path(workspace.directory).read_bytes() == manifest
    assert modified_derived_configs(workspace.directory) == []
    assert result is engine
    assert loaded == [(path, baseline_density, 0, 0)]
    assert json_read(path)["result_dir"] == str(owner.data.workdir_for(owner.name))


class _Params:
    """Records what ``DreamplaceModule`` loads, as DreamPlace's ``Params`` would."""

    def fromJson(self, config: dict) -> None:
        self.__dict__.update(config)


def test_legalization_values_reach_only_the_legalization_config(
    tmp_path, monkeypatch, make_ics55_parameters
) -> None:
    workspace = _workspace(tmp_path, make_ics55_parameters)
    legalization_values = {
        "legalization.cell_padding_x": 400,
        "legalization.bndry_padding_x": 10,
        "legalization.bndry_padding_y": 20,
        "legalization.num_threads": 2,
        "legalization.deterministic_flag": 0,
    }
    workspace.parameters.data["step_params"] = {"legalization": legalization_values}
    baseline = json_read(workspace.config["dreamplace"])
    monkeypatch.setattr(builder.ecc_builder, "build_step_config", lambda *_: None)
    steps = [
        _step(workspace, tmp_path, name)
        for name in (StepEnum.PLACEMENT.value, StepEnum.LEGALIZATION.value)
    ]

    for step in steps:
        builder.build_step_config(workspace, step)

    fields = [param.removeprefix("legalization.") for param in legalization_values]
    configs = {
        step.name: {
            field: json_read(builder.step_config_path(workspace, step))[field] for field in fields
        }
        for step in steps
    }
    assert configs == {
        StepEnum.PLACEMENT.value: {field: baseline[field] for field in fields},
        StepEnum.LEGALIZATION.value: {
            param.removeprefix("legalization."): value
            for param, value in legalization_values.items()
        },
    }
    assert json_read(workspace.config["dreamplace"]) == baseline
