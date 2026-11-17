import json
from pathlib import Path

import pytest

from chipcompiler.data.parameter import get_parameters, update_parameters
from chipcompiler.tools.ecc_dreamplace import builder as dreamplace_builder
from chipcompiler.utility import json_read


@pytest.fixture
def dreamplace_default_config():
    config_path = (
        Path(dreamplace_builder.__file__).resolve().parent / "configs" / "dreamplace_ecc.json"
    )
    config = json_read(config_path)
    config["buffering_fixed_buffer_master"] = "fixture_buffer"
    return config


@pytest.fixture
def make_ics55_parameters():
    def factory(overrides: dict | None = None):
        parameters = get_parameters("ics55")
        defaults = json.loads(
            (Path(__file__).parents[2] / "pdk/fixtures/tool_defaults.json").read_text()
        )
        parameters.data.setdefault("dreamplace", {})["buffering_fixed_buffer_master"] = (
            "fixture_buffer"
        )
        parameters.data["config_overrides"] = {"sta": defaults["sta"]}
        if overrides:
            update_parameters(overrides, parameters.data)
            parameters.data.setdefault("config_overrides", {}).setdefault("sta", defaults["sta"])
        parameters.data.setdefault("dreamplace", {}).setdefault(
            "buffering_fixed_buffer_master", "fixture_buffer"
        )
        return parameters

    return factory
