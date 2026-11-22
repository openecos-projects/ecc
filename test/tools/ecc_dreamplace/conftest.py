from pathlib import Path

import pytest

from chipcompiler.data.parameter import get_parameters, update_parameters
from chipcompiler.tools.ecc_dreamplace import builder as dreamplace_builder
from chipcompiler.utility import json_read


@pytest.fixture
def dreamplace_default_config():
    from chipcompiler.data.pdk import PDK
    from chipcompiler.data.workspace.tool_configs import tool_config

    configs_dir = Path(dreamplace_builder.__file__).resolve().parent / "configs"
    return tool_config(configs_dir, "dreamplace_ecc.json", PDK(name="ics55", version="v1"))


@pytest.fixture
def make_ics55_parameters():
    def factory(overrides: dict | None = None):
        parameters = get_parameters("ics55")
        default_sta = json_read(
            Path(dreamplace_builder.__file__).resolve().parents[1]
            / "ecc"
            / "configs"
            / "defaults"
            / "sta_ecc.json"
        )
        parameters.data.setdefault("dreamplace", {})["buffering_fixed_buffer_master"] = (
            "fixture_buffer"
        )
        parameters.data["config_overrides"] = {"sta": default_sta}
        if overrides:
            update_parameters(overrides, parameters.data)
            parameters.data.setdefault("config_overrides", {}).setdefault("sta", default_sta)
        parameters.data.setdefault("dreamplace", {}).setdefault(
            "buffering_fixed_buffer_master", "fixture_buffer"
        )
        return parameters

    return factory
