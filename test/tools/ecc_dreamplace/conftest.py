from pathlib import Path

import pytest

from chipcompiler.data.parameter import get_parameters, update_parameters
from chipcompiler.tools.ecc_dreamplace import builder as dreamplace_builder
from chipcompiler.utility import json_read


@pytest.fixture
def dreamplace_default_config():
    config_path = (
        Path(dreamplace_builder.__file__).resolve().parent / "configs" / "dreamplace.json"
    )
    return json_read(str(config_path))


@pytest.fixture
def make_ics55_parameters():
    def factory(overrides: dict | None = None):
        parameters = get_parameters("ics55")
        if overrides:
            update_parameters(overrides, parameters.data)
        return parameters

    return factory
