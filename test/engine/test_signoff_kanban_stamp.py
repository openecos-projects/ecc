"""Version stamp footer for generated kanban (fingerprint底子; no baseline diff)."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_kanban_module():
    path = (
        Path(__file__).resolve().parents[2]
        / "nix"
        / "scripts"
        / "generate-signoff-kanban.py"
    )
    spec = importlib.util.spec_from_file_location("generate_signoff_kanban", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_append_version_footer_stamps_commit_and_snapshot_hash():
    mod = _load_kanban_module()
    text = mod._append_version_footer(
        "# board\n",
        commit="abcdef0123456789deadbeef",
        commit_url="https://example.test/commit/abcdef0123456789deadbeef",
        snapshot_sha256="a" * 64,
    )
    assert "Snapshot SHA-256" in text
    assert "a" * 64 in text
    assert "abcdef012345" in text
