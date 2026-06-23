import shutil
import stat

from chipcompiler.data import PDK, OriginDesign, StepEnum, Workspace
from chipcompiler.data.workspace import init_workspace_config
from chipcompiler.tools.ecc_dreamplace import builder as dreamplace_builder
from chipcompiler.utility import json_read, json_write


def test_workspace_config_generation_leaves_config_root_writable_after_read_only_copy(
    tmp_path,
    monkeypatch,
    make_ics55_parameters,
):
    workspace = Workspace(
        directory=str(tmp_path / "workspace"),
        design=OriginDesign(name="gcd"),
        pdk=PDK(tech="tech.lef", lefs=["std.lef"], buffers=[], fillers=[]),
        parameters=make_ics55_parameters(),
    )
    config_dir = tmp_path / "workspace" / "config"

    real_copy2 = shutil.copy2

    def copy_readonly_config_file(src, dst):
        result = real_copy2(src, dst)
        tmp_path.joinpath(dst).chmod(stat.S_IREAD)
        return result

    monkeypatch.setattr(shutil, "copy2", copy_readonly_config_file)

    init_workspace_config(workspace)

    config_mode = config_dir.stat().st_mode
    copied_config = config_dir / "flow_config.json"
    copied_mode = copied_config.stat().st_mode
    assert config_mode & stat.S_IWUSR
    assert config_mode & stat.S_IXUSR
    assert copied_mode & stat.S_IWUSR

    extra_config = config_dir / "created_after_build.json"
    extra_config.write_text("{}", encoding="utf-8")
    assert extra_config.exists()


def test_dreamplace_config_generation_writes_generated_fields_to_copied_config(
    tmp_path,
    monkeypatch,
    make_ics55_parameters,
):
    workspace = Workspace(
        directory=str(tmp_path / "workspace"),
        design=OriginDesign(name="gcd"),
        pdk=PDK(tech="tech.lef", lefs=["std.lef"]),
        parameters=make_ics55_parameters(),
    )
    step = dreamplace_builder.build_step(
        workspace=workspace,
        step_name=StepEnum.PLACEMENT.value,
        input_def="input.def",
        input_verilog="input.v",
    )
    config_dir = tmp_path / "workspace" / "config"

    real_copy2 = shutil.copy2

    def copy_readonly_config_file(src, dst):
        result = real_copy2(src, dst)
        tmp_path.joinpath(dst).chmod(stat.S_IREAD)
        return result

    monkeypatch.setattr(shutil, "copy2", copy_readonly_config_file)

    init_workspace_config(workspace)
    monkeypatch.setattr(
        dreamplace_builder.ecc_builder,
        "build_step_config",
        lambda _workspace, _step: None,
    )

    dreamplace_builder.build_step_config(workspace, step)

    dreamplace_config = config_dir / "dreamplace.json"
    mode = dreamplace_config.stat().st_mode
    data = json_read(str(dreamplace_config))

    assert mode & stat.S_IWUSR
    assert data["lef_input"] == ["tech.lef", "std.lef"]
    assert data["def_input"] == "input.def"
    assert data["verilog_input"] == "input.v"
    assert data["result_dir"] == step.data[step.name]
    assert data["base_design_name"] == "gcd"


def test_workspace_config_generation_applies_flat_dreamplace_parameter_overrides(
    tmp_path,
    make_ics55_parameters,
):
    overrides = {
        "Target density": 0.65,
        "Target overflow": 0.05,
        "Cell padding x": 800,
        "Routability opt flag": 1,
    }
    workspace = Workspace(
        directory=str(tmp_path / "workspace"),
        design=OriginDesign(name="gcd"),
        pdk=PDK(tech="tech.lef", lefs=["std.lef"]),
        parameters=make_ics55_parameters(overrides),
    )

    init_workspace_config(workspace)

    dreamplace_config = json_read(workspace.config["dreamplace"])
    assert dreamplace_config["target_density"] == overrides["Target density"]
    assert dreamplace_config["stop_overflow"] == overrides["Target overflow"]
    assert dreamplace_config["cell_padding_x"] == overrides["Cell padding x"]
    assert dreamplace_config["routability_opt_flag"] == overrides["Routability opt flag"]


def test_workspace_config_generation_nested_dreamplace_overrides_win_over_flat_keys(
    tmp_path,
    make_ics55_parameters,
):
    overrides = {
        "Routability opt flag": 1,
        "DreamPlace": {"routability_opt_flag": 0},
    }
    workspace = Workspace(
        directory=str(tmp_path / "workspace"),
        design=OriginDesign(name="gcd"),
        pdk=PDK(tech="tech.lef", lefs=["std.lef"]),
        parameters=make_ics55_parameters(overrides),
    )

    init_workspace_config(workspace)

    dreamplace_config = json_read(workspace.config["dreamplace"])
    assert dreamplace_config["routability_opt_flag"] == overrides["DreamPlace"][
        "routability_opt_flag"
    ]


def test_dreamplace_step_config_refresh_reapplies_current_parameter_file(
    tmp_path,
    monkeypatch,
    make_ics55_parameters,
):
    initial_overrides = {"Target density": 0.65}
    workspace = Workspace(
        directory=str(tmp_path / "workspace"),
        design=OriginDesign(name="gcd"),
        pdk=PDK(tech="tech.lef", lefs=["std.lef"]),
        parameters=make_ics55_parameters(initial_overrides),
    )
    (tmp_path / "workspace" / "home").mkdir(parents=True)
    workspace.parameters.path = str(tmp_path / "workspace" / "home" / "parameters.json")
    step = dreamplace_builder.build_step(
        workspace=workspace,
        step_name=StepEnum.PLACEMENT.value,
        input_def="input.def",
        input_verilog="input.v",
    )

    init_workspace_config(workspace)
    updated_overrides = {
        "Target density": 0.7,
        "DreamPlace": {
            "def_input": "stale.def",
            "verilog_input": "stale.v",
            "result_dir": "stale-output",
        },
    }
    updated_parameters = make_ics55_parameters(updated_overrides)
    json_write(
        workspace.parameters.path,
        updated_parameters.data,
    )
    monkeypatch.setattr(
        dreamplace_builder.ecc_builder,
        "build_step_config",
        lambda _workspace, _step: None,
    )

    dreamplace_builder.build_step_config(workspace, step)

    dreamplace_config = json_read(workspace.config["dreamplace"])
    assert dreamplace_config["target_density"] == updated_overrides["Target density"]
    assert dreamplace_config["def_input"] == "input.def"
    assert dreamplace_config["verilog_input"] == "input.v"
    assert dreamplace_config["result_dir"] == step.data[step.name]
