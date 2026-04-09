"""Formal verification test utilities."""

from __future__ import annotations

import os
from pathlib import Path

from z3 import Solver

# Default output directory: test/formal/smt2/ (sibling of this __init__.py)
_SMT2_DIR: str = os.path.join(os.path.dirname(__file__), "smt2")


def dump_smt2(solver: Solver, name: str, output_dir: str | None = None) -> Path:
    """Dump a solver's constraints to an SMT-LIB2 file for review.

    Args:
        solver: z3 Solver instance with constraints added.
        name: File stem (e.g., "state_machine_transition"). Produces `<name>.smt2`.
              Must not contain path separators.
        output_dir: Directory for output. Defaults to `test/formal/smt2/`.

    Returns:
        Path to the written .smt2 file.

    Raises:
        ValueError: If name contains path separators or attempts directory traversal.

    Example:
        >>> solver = Solver()
        >>> solver.add(x > 0)
        >>> path = dump_smt2(solver, "example")
        >>> # writes test/formal/smt2/example.smt2
    """
    if os.path.basename(name) != name or os.sep in name or "/" in name:
        msg = f"name must be a plain filename stem, got: {name!r}"
        raise ValueError(msg)

    out_dir: str = output_dir or _SMT2_DIR
    os.makedirs(out_dir, exist_ok=True)

    out_path = (Path(out_dir) / f"{name}.smt2").resolve()
    resolved_dir = Path(out_dir).resolve()

    if not out_path.is_relative_to(resolved_dir):
        msg = f"resolved path {out_path} escapes output directory {resolved_dir}"
        raise ValueError(msg)

    out_path.write_text(solver.to_smt2())
    return out_path
