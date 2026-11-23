"""Unit coverage for tool_config()'s defaults/pdk-override merge semantics."""

import json
from pathlib import Path

import pytest

import chipcompiler
from chipcompiler.data.pdk import PDK
from chipcompiler.data.workspace.tool_configs import tool_config
from chipcompiler.utility import JsonReadError


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


def test_tool_config_raises_when_an_existing_override_is_corrupt(tmp_path):
    _write(tmp_path / "defaults" / "tool.json", {"a": 1})
    override = tmp_path / "pdk" / "fixture-v1" / "tool.json"
    override.parent.mkdir(parents=True, exist_ok=True)
    override.write_text('{"a": ', encoding="utf-8")

    with pytest.raises(JsonReadError):
        tool_config(tmp_path, "tool.json", PDK(name="fixture", version="v1"))


def test_tool_config_rejects_an_override_that_is_not_an_object(tmp_path):
    _write(tmp_path / "defaults" / "tool.json", {"a": 1})
    _write(tmp_path / "pdk" / "fixture-v1" / "tool.json", ["a"])

    with pytest.raises(JsonReadError, match="must be an object"):
        tool_config(tmp_path, "tool.json", PDK(name="fixture", version="v1"))


def _reference_merge(default, override):
    """Independent deep merge: dicts recurse, everything else replaces."""
    merged = dict(default)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _reference_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


@pytest.mark.parametrize("variant", ["ics55-v1", "ics55-v2"])
@pytest.mark.parametrize(
    "tool_dir",
    ["tools/ecc/configs", "tools/ecc_dreamplace/configs", "tools/ecc_sizer/configs"],
)
def test_tool_config_merges_the_real_shipped_defaults_and_overrides(tool_dir, variant):
    """Every shipped override must layer onto its defaults exactly as merged."""
    configs_dir = Path(chipcompiler.__file__).resolve().parent / tool_dir
    name, version = variant.split("-")
    pdk = PDK(name=name, version=version)

    for default_path in sorted((configs_dir / "defaults").glob("*.json")):
        override_path = configs_dir / "pdk" / variant / default_path.name
        default = json.loads(default_path.read_text(encoding="utf-8"))
        expected = (
            _reference_merge(default, json.loads(override_path.read_text(encoding="utf-8")))
            if override_path.is_file()
            else default
        )
        assert tool_config(configs_dir, default_path.name, pdk) == expected
