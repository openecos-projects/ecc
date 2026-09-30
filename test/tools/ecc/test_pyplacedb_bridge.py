from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from chipcompiler.tools.ecc.module import ECCToolsModule


@pytest.mark.parametrize(
    "rail_options", [{}, {"include_m2_pg_rail_blockage": True, "include_m2_pg_rail_density": False}]
)
def test_pydb_forwards_placement_and_rail_options(rail_options):
    result = object()
    native_pydb = Mock(return_value=result)
    module = ECCToolsModule.__new__(ECCToolsModule)
    module.ecc = SimpleNamespace(pydb=native_pydb)
    dm_inst = object()

    assert module.pydb(dm_inst, 128, 256, 1, 0, **rail_options) is result

    native_pydb.assert_called_once_with(
        dm_inst,
        128,
        256,
        1,
        0,
        rail_options.get("include_m2_pg_rail_blockage", False),
        rail_options.get("include_m2_pg_rail_density", True),
    )
