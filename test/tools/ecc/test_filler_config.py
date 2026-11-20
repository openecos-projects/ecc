"""Filler roles and explicit selections must reach the native allowlist."""

from unittest.mock import Mock

import pytest

from chipcompiler.data import PDK, Parameters, Workspace
from chipcompiler.data.workspace.filler_config import refresh_filler_config
from chipcompiler.tools.ecc.module import ECCToolsModule
from chipcompiler.utility import json_read, json_write


@pytest.mark.parametrize(
    ("profile", "overrides", "expected"),
    [
        ({}, {}, "FILL_LARGE FILL_SMALL"),
        ({"MJ": {"-filler": "PROFILE_FILL"}}, {}, "PROFILE_FILL"),
        ({"MJ": {"-filler": "PROFILE_FILL"}}, {"MJ": {"-filler": "USER_FILL"}}, "USER_FILL"),
        ({"MJ": {"-filler": "PROFILE_FILL"}}, {"MJ": {"-filler": "  "}}, "FILL_LARGE FILL_SMALL"),
    ],
)
def test_refresh_resolves_allowlist_and_preserves_width(tmp_path, profile, overrides, expected):
    path = tmp_path / "filler.json"
    json_write(path, {"-filler": "STALE_DECAP TAP", "-min_filler_width": 2})
    workspace = Workspace(
        directory=tmp_path,
        config={"filler": path},
        pdk=PDK(
            fillers=["FILL_LARGE", "FILL_SMALL"],
            description={"tools": {"configs": {"filler": profile}}},
        ),
        parameters=Parameters(data={"config_overrides": {"filler": overrides}}),
    )

    refresh_filler_config(workspace)
    refresh_filler_config(workspace)

    assert json_read(path) == {"MJ": {"-filler": expected}, "-min_filler_width": 2}


def test_refresh_migrates_legacy_width_and_updates_pdk_roles(tmp_path):
    path = tmp_path / "filler.json"
    json_write(path, {"PL": {"Filler": {"min_filler_width": 3}}})
    workspace = Workspace(
        directory=tmp_path, config={"filler": path}, pdk=PDK(fillers=["NEW_FILL"])
    )

    refresh_filler_config(workspace)

    assert json_read(path) == {"MJ": {"-filler": "NEW_FILL"}, "-min_filler_width": 3}


def test_filler_requires_allowlist_before_native_insertion(tmp_path):
    path = tmp_path / "filler.json"
    module = ECCToolsModule.__new__(ECCToolsModule)
    module.ecc = Mock()
    json_write(path, {"MJ": {"-filler": ""}})
    with pytest.raises(ValueError, match="PDK filler roles"):
        module.run_filler(path)
    module.ecc.insert_filler.assert_not_called()
    json_write(path, {"MJ": {"-filler": "FILL1"}})
    module.run_filler(path)
    module.ecc.insert_filler.assert_called_once_with(config=path)
