import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest


def test_resolve_from_manifest_found(tmp_path: Path) -> None:
    """When manifest has yosys entry and binary exists, resolve it."""
    from chipcompiler.tools.yosys.utility import _resolve_from_manifest

    # Set up fake tool installation
    tool_dir = tmp_path / "yosys" / "0.61"
    bin_dir = tool_dir / "bin"
    bin_dir.mkdir(parents=True)
    yosys_bin = bin_dir / "yosys"
    yosys_bin.write_text("#!/bin/sh\necho yosys")
    yosys_bin.chmod(0o755)

    manifest = {
        "schema_version": 1,
        "installed": {
            "yosys": {
                "version": "0.61",
                "path": str(tool_dir),
                "sha256": "abc123",
            }
        },
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))

    with patch(
        "chipcompiler.tools.yosys.utility._MANIFEST_PATH",
        manifest_path,
    ):
        cmd, tool_path = _resolve_from_manifest("yosys")
        assert cmd == [str(yosys_bin)]
        assert tool_path == tool_dir


def test_resolve_from_manifest_no_file(tmp_path: Path) -> None:
    """When manifest doesn't exist, return empty."""
    from chipcompiler.tools.yosys.utility import _resolve_from_manifest

    with patch(
        "chipcompiler.tools.yosys.utility._MANIFEST_PATH",
        tmp_path / "nonexistent.json",
    ):
        cmd, tool_path = _resolve_from_manifest("yosys")
        assert cmd == []
        assert tool_path is None


def test_resolve_from_manifest_tool_not_installed(tmp_path: Path) -> None:
    """When manifest exists but tool not in it, return empty."""
    from chipcompiler.tools.yosys.utility import _resolve_from_manifest

    manifest = {"schema_version": 1, "installed": {}}
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))

    with patch(
        "chipcompiler.tools.yosys.utility._MANIFEST_PATH",
        manifest_path,
    ):
        cmd, tool_path = _resolve_from_manifest("yosys")
        assert cmd == []
        assert tool_path is None


def test_resolve_from_manifest_binary_missing(tmp_path: Path) -> None:
    """When manifest has entry but binary doesn't exist, return empty."""
    from chipcompiler.tools.yosys.utility import _resolve_from_manifest

    tool_dir = tmp_path / "yosys" / "0.61"
    tool_dir.mkdir(parents=True)
    # Don't create the binary

    manifest = {
        "schema_version": 1,
        "installed": {
            "yosys": {
                "version": "0.61",
                "path": str(tool_dir),
                "sha256": "abc123",
            }
        },
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))

    with patch(
        "chipcompiler.tools.yosys.utility._MANIFEST_PATH",
        manifest_path,
    ):
        cmd, tool_path = _resolve_from_manifest("yosys")
        assert cmd == []
        assert tool_path is None


def test_resolve_yosys_command_checks_manifest_first(tmp_path: Path) -> None:
    """_resolve_yosys_command should check manifest before env var and PATH."""
    from chipcompiler.tools.yosys.utility import _resolve_yosys_command

    # Set up fake manifest tool
    tool_dir = tmp_path / "yosys" / "0.61"
    bin_dir = tool_dir / "bin"
    bin_dir.mkdir(parents=True)
    yosys_bin = bin_dir / "yosys"
    yosys_bin.write_text("#!/bin/sh\necho yosys")
    yosys_bin.chmod(0o755)

    manifest = {
        "schema_version": 1,
        "installed": {
            "yosys": {
                "version": "0.61",
                "path": str(tool_dir),
                "sha256": "abc123",
            }
        },
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))

    with patch(
        "chipcompiler.tools.yosys.utility._MANIFEST_PATH",
        manifest_path,
    ):
        cmd, oss_path = _resolve_yosys_command()
        assert cmd == [str(yosys_bin)]
        assert oss_path == tool_dir
