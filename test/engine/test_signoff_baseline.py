"""In-repo signoff baseline versions (durable multi-version data)."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_baseline_module():
    path = Path(__file__).resolve().parents[2] / "nix" / "scripts" / "signoff_baseline.py"
    spec = importlib.util.spec_from_file_location("signoff_baseline", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_baseline_verify_and_diff():
    mod = _load_baseline_module()
    root = Path(__file__).resolve().parents[2] / "nix" / "signoff-baseline"
    assert mod.cmd_verify(root) == 0
    assert mod.cmd_diff(root, "v2026-09-synth", "v2026-10-runtime") == 0
