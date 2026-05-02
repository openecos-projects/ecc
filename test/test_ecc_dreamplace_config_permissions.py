import shutil
import stat

from chipcompiler.data import PDK, OriginDesign, Parameters, StepEnum, Workspace
from chipcompiler.data.workspace import init_workspace_config
from chipcompiler.tools.ecc_dreamplace import builder as dreamplace_builder
from chipcompiler.utility import json_read, json_write


def test_workspace_config_generation_leaves_config_root_writable_after_read_only_copy(
    tmp_path,
    monkeypatch,
):
    workspace = Workspace(
        directory=str(tmp_path / "workspace"),
        design=OriginDesign(name="gcd"),
        pdk=PDK(tech="tech.lef", lefs=["std.lef"], buffers=[], fillers=[]),
        parameters=Parameters(data={}),
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
):
    workspace = Workspace(
        directory=str(tmp_path / "workspace"),
        design=OriginDesign(name="gcd"),
        pdk=PDK(tech="tech.lef", lefs=["std.lef"]),
        parameters=Parameters(data={}),
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
