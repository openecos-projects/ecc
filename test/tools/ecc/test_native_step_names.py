"""Legacy flow step names must reach the native feature API in its vocabulary."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from chipcompiler.data import StepEnum
from chipcompiler.tools.ecc.module import ECCToolsModule


@pytest.mark.parametrize(
    ("step", "native_step"),
    [
        (StepEnum.PLACEMENT.value, "placement"),
        (StepEnum.CTS.value, "cts"),
        (StepEnum.ROUTING.value, "routing"),
        (StepEnum.STA.value, "sta"),
    ],
)
def test_feature_step_passes_native_stage_without_changing_output_path(step, native_step):
    feature_tool = Mock()
    module = ECCToolsModule.__new__(ECCToolsModule)
    module.ecc = SimpleNamespace(feature_tool=feature_tool)
    output = Path("/workspace/feature/step.json")

    module.feature_step(step, output)

    feature_tool.assert_called_once_with(output, native_step)
