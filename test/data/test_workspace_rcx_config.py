"""Process-file configuration survives PDK defaults, overrides and step rebuilds."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from chipcompiler.data import PDK, Workspace
from chipcompiler.data.workspace.rcx_config import refresh_rcx_config
from chipcompiler.data.workspace.tool_configs import tool_config

CONFIGS = Path(__file__).resolve().parents[2] / "chipcompiler/tools/ecc/configs"


def _workspace(tmp_path, pdk, config):
    path = tmp_path / "rcx_ecc.json"
    path.write_text(json.dumps(config))
    return Workspace(directory=tmp_path, pdk=pdk, config={"rcx": path})


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_refresh_adds_process_inputs_to_existing_config(tmp_path, version):
    pdk_root = tmp_path / "pdk"
    pdk = PDK(name="ics55", version=version, root=pdk_root)
    current: dict = tool_config(CONFIGS, "rcx_ecc.json", PDK()) | {"thread_num": 3}
    workspace = _workspace(tmp_path, pdk, current)
    expected: dict = tool_config(CONFIGS, "rcx_ecc.json", pdk) | current
    if version == "v2":
        expected["mapping_file"] = str(tmp_path / "rcx_layers.map")
    else:
        expected["mapping_file"] = str(pdk_root / expected["mapping_file"])
    for corner in expected["corners"]:
        for key in ("process_file", "captab_file"):
            corner[key] = str(pdk_root / corner[key])

    for _ in range(2):
        refresh_rcx_config(workspace)
        assert json.loads(workspace.config["rcx"].read_text()) == expected
    if version == "v2":
        assert (tmp_path / "rcx_layers.map").read_bytes() == (
            CONFIGS / "pdk/ics55-v2/rcx_layers.map"
        ).read_bytes()


@pytest.mark.parametrize("process_key", ["process_file", "itf_file"])
@pytest.mark.parametrize("version", ["v1", "v2"])
def test_refresh_preserves_explicit_corner_and_absolute_files(tmp_path, process_key, version):
    pdk_root = tmp_path / "pdk"
    pdk = PDK(name="ics55", version=version, root=pdk_root)
    current = tool_config(CONFIGS, "rcx_ecc.json", PDK()) | {
        "mapping_file": str(tmp_path / "external layers.map"),
        "corners": [
            {
                "name": "USER",
                "temperature": [85],
                process_key: str(tmp_path / "custom process.itf"),
                "captab_file": "user/custom.captab",
                "process_options": {"extensions": ["dielectric_surface_fields"]},
            }
        ],
    }
    expected = deepcopy(current)
    expected["corners"][0]["captab_file"] = str(pdk_root / "user/custom.captab")
    workspace = _workspace(tmp_path, pdk, current)

    for _ in range(2):
        refresh_rcx_config(workspace)
        assert json.loads(workspace.config["rcx"].read_text()) == expected


def test_refresh_uses_custom_pdk_process_profile(tmp_path):
    pdk_root = tmp_path / "pdk"
    pdk = PDK(name="custom", root=pdk_root)
    profile_path = pdk_root / "ecc-configs/ecc/rcx_ecc.json"
    profile_path.parent.mkdir(parents=True)
    profile = {
        "mapping_file": "custom.map",
        "corners": [{"name": "SLOW", "process_file": "slow.itf", "captab_file": "slow.cap"}],
    }
    profile_path.write_text(json.dumps(profile))
    current = tool_config(CONFIGS, "rcx_ecc.json", PDK())
    workspace = _workspace(tmp_path, pdk, current)
    expected = current | {
        "mapping_file": str(pdk_root / "custom.map"),
        "corners": [
            {
                "name": "SLOW",
                "process_file": str(pdk_root / "slow.itf"),
                "captab_file": str(pdk_root / "slow.cap"),
            }
        ],
    }

    refresh_rcx_config(workspace)

    assert json.loads(workspace.config["rcx"].read_text()) == expected


def test_process_paths_survive_workspace_and_step_override_replay(
    tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters, gcd_rtl_file
):
    from chipcompiler.data import StepEnum, create_workspace
    from chipcompiler.data.workspace import refresh_workspace_config, update_step_config
    from chipcompiler.tools.ecc.builder import build_step, build_step_config

    pdk_root = minimal_ics55_pdk_factory(tmp_path / "pdk")
    override = {
        "mapping_file": "custom.map",
        "corners": [
            {
                "name": "TYPICAL",
                "temperature": [25],
                "process_file": "custom.itf",
                "captab_file": "custom.captab",
            }
        ],
    }
    workspace = create_workspace(
        directory=tmp_path / "workspace",
        origin_def="",
        origin_verilog=gcd_rtl_file,
        pdk="ics55",
        pdk_root=pdk_root,
        parameters=default_ics55_parameters | {"config_overrides": {"rcx": override}},
    )
    assert workspace is not None
    expected = tool_config(CONFIGS, "rcx_ecc.json", PDK()) | deepcopy(override)
    expected["mapping_file"] = str(pdk_root / "custom.map")
    expected["corners"][0].update(
        process_file=str(pdk_root / "custom.itf"),
        captab_file=str(pdk_root / "custom.captab"),
    )
    for stage in (StepEnum.PRE_FLOORPLAN, StepEnum.POST_FLOORPLAN, StepEnum.RCX):
        refresh_workspace_config(workspace)
        assert json.loads(workspace.config["rcx"].read_text()) == expected
        step = build_step(workspace, stage, input_def=None, input_verilog=None)
        update_step_config(workspace, step)
        if stage == StepEnum.RCX:
            assert step.data.dir is not None
            expected["output"] = str(step.data.dir)
            expected["corners"][0]["spef_file"] = [
                {"25": str(step.data.dir / "gcd_TYPICAL_25C.spef")}
            ]
            build_step_config(workspace, step)
            assert step.output.spef == [step.data.dir / "gcd_TYPICAL_25C.spef"]
        assert json.loads(workspace.config["rcx"].read_text()) == expected
