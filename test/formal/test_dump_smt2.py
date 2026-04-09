"""Unit tests for test.formal.dump_smt2 helper."""

from __future__ import annotations

from pathlib import Path

import pytest
from z3 import Int, Solver

from test.formal import dump_smt2


def _make_solver() -> Solver:
    """Create a minimal solver with one constraint."""
    s = Solver()
    s.add(Int("x") > 0)
    return s


def test_dump_writes_to_expected_directory(tmp_path: Path) -> None:
    """dump_smt2 writes a .smt2 file inside the given output_dir."""
    s = _make_solver()
    result = dump_smt2(s, "test_output", output_dir=str(tmp_path))

    assert result.exists()
    assert result.name == "test_output.smt2"
    assert result.parent == tmp_path
    content = result.read_text(encoding="utf-8")
    assert "(check-sat)" in content


def test_dump_rejects_path_separators() -> None:
    """Names with / or os.sep are rejected."""
    s = _make_solver()

    with pytest.raises(ValueError, match="plain filename stem"):
        dump_smt2(s, "../escape")

    with pytest.raises(ValueError, match="plain filename stem"):
        dump_smt2(s, "sub/path")


def test_dump_rejects_empty_name() -> None:
    """Empty or whitespace-only names are rejected."""
    s = _make_solver()

    with pytest.raises(ValueError, match="non-empty"):
        dump_smt2(s, "")

    with pytest.raises(ValueError, match="non-empty"):
        dump_smt2(s, "   ")


def test_dump_uses_utf8_encoding(tmp_path: Path) -> None:
    """Output file is written with explicit UTF-8 encoding."""
    s = _make_solver()
    result = dump_smt2(s, "encoding_test", output_dir=str(tmp_path))

    # Read back with explicit UTF-8 -- should not raise
    content = result.read_text(encoding="utf-8")
    assert len(content) > 0
