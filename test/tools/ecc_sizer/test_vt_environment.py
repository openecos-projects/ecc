"""Sizer VT-suffix environment lines, driven by the merged sizer_ecc.json."""

import json
from pathlib import Path

import pytest

from chipcompiler.data.pdk import PDK
from chipcompiler.data.workspace.tool_configs import tool_config
from chipcompiler.tools.ecc_sizer import builder as sizer_builder

from ._sizer_helpers import _workspace

_CONFIGS_DIR = Path(sizer_builder.__file__).resolve().parent / "configs"


def _with_sizer_config(workspace, pdk):
    config_path = workspace.directory / "sizer_ecc.json"
    config_path.write_text(
        json.dumps(tool_config(_CONFIGS_DIR, "sizer_ecc.json", pdk)), encoding="utf-8"
    )
    workspace.config["sizer"] = config_path
    return workspace


def test_vt_environment_defaults_to_single_vt_group_with_no_override(tmp_path):
    workspace = _with_sizer_config(_workspace(tmp_path), PDK(name="fixture", version=""))

    assert sizer_builder._vt_environment(workspace) == "-num_vt 1\n"


def test_vt_environment_emits_ics55_v1_suffixes_slow_to_fast(tmp_path):
    workspace = _with_sizer_config(_workspace(tmp_path), PDK(name="ics55", version="v1"))

    assert sizer_builder._vt_environment(workspace) == (
        "-num_vt 3\n-suffix_hvt H7H\n-suffix_nvt H7R\n-suffix_lvt H7L\n"
    )


def test_vt_environment_emits_ics55_v2_suffixes_slow_to_fast(tmp_path):
    workspace = _with_sizer_config(_workspace(tmp_path), PDK(name="ics55", version="v2"))

    assert sizer_builder._vt_environment(workspace) == (
        "-num_vt 3\n-suffix_hvt _9THVT\n-suffix_nvt _9TSVT\n-suffix_lvt _9TLVT\n"
    )


def test_vt_environment_rejects_more_than_three_groups(tmp_path):
    workspace = _workspace(tmp_path)
    config_path = tmp_path / "sizer_ecc.json"
    config_path.write_text(json.dumps({"vt_suffixes": ["A", "B", "C", "D"]}), encoding="utf-8")
    workspace.config["sizer"] = config_path

    with pytest.raises(ValueError, match="at most three ordered VT groups"):
        sizer_builder._vt_environment(workspace)


def test_vt_environment_rejects_duplicate_suffixes(tmp_path):
    workspace = _workspace(tmp_path)
    config_path = tmp_path / "sizer_ecc.json"
    config_path.write_text(json.dumps({"vt_suffixes": ["A", "A"]}), encoding="utf-8")
    workspace.config["sizer"] = config_path

    with pytest.raises(ValueError, match="duplicate Sizer VT suffix"):
        sizer_builder._vt_environment(workspace)


def test_vt_environment_rejects_whitespace_suffix(tmp_path):
    workspace = _workspace(tmp_path)
    config_path = tmp_path / "sizer_ecc.json"
    config_path.write_text(json.dumps({"vt_suffixes": ["A B"]}), encoding="utf-8")
    workspace.config["sizer"] = config_path

    with pytest.raises(ValueError, match="nonempty token"):
        sizer_builder._vt_environment(workspace)
