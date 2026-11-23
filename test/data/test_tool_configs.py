"""Unit coverage for tool_config()'s defaults/pdk-override merge semantics."""

import json

import pytest

from chipcompiler.data.pdk import PDK
from chipcompiler.data.workspace.tool_configs import tool_config


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_tool_config_merges_nested_dicts_recursively(tmp_path):
    _write(
        tmp_path / "defaults" / "tool.json",
        {"a": {"x": 1, "y": 2}, "b": "default"},
    )
    _write(tmp_path / "pdk" / "fixture-v1" / "tool.json", {"a": {"y": 20}})

    config = tool_config(tmp_path, "tool.json", PDK(name="fixture", version="v1"))

    assert config == {"a": {"x": 1, "y": 20}, "b": "default"}


def test_tool_config_replaces_lists_entirely_instead_of_merging(tmp_path):
    _write(
        tmp_path / "defaults" / "tool.json",
        {"items": ["a", "b", "c"]},
    )
    _write(tmp_path / "pdk" / "fixture-v1" / "tool.json", {"items": ["z"]})

    config = tool_config(tmp_path, "tool.json", PDK(name="fixture", version="v1"))

    assert config == {"items": ["z"]}


def test_tool_config_falls_back_to_defaults_when_no_matching_override_dir(tmp_path):
    _write(tmp_path / "defaults" / "tool.json", {"a": 1})

    config = tool_config(tmp_path, "tool.json", PDK(name="fixture", version="v1"))

    assert config == {"a": 1}


def test_tool_config_falls_back_to_defaults_when_override_file_missing(tmp_path):
    _write(tmp_path / "defaults" / "tool.json", {"a": 1})
    (tmp_path / "pdk" / "fixture-v1").mkdir(parents=True)

    config = tool_config(tmp_path, "tool.json", PDK(name="fixture", version="v1"))

    assert config == {"a": 1}


def test_tool_config_falls_back_to_defaults_for_unversioned_pdk(tmp_path):
    _write(tmp_path / "defaults" / "tool.json", {"a": 1})
    _write(tmp_path / "pdk" / "fixture-v1" / "tool.json", {"a": 2})

    config = tool_config(tmp_path, "tool.json", PDK())

    assert config == {"a": 1}


def test_tool_config_raises_when_default_config_is_missing(tmp_path):
    with pytest.raises(FileNotFoundError, match="Required JSON file not found"):
        tool_config(tmp_path, "tool.json", PDK(name="fixture", version="v1"))
