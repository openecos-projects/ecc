"""Formal verification test utilities."""

from __future__ import annotations

import os
from pathlib import Path

from z3 import Solver

# Default output directory for SMT-LIB dumps (relative to ecc/)
_SMT2_DIR: str = os.path.join(os.path.dirname(__file__), "smt2")


def dump_smt2(solver: Solver, name: str, output_dir: str | None = None) -> Path:
    """Dump a solver's constraints to an SMT-LIB2 file for review.

    Args:
        solver: z3 Solver instance with constraints added.
        name: File stem (e.g., "state_machine_transition"). Produces `<name>.smt2`.
        output_dir: Directory for output. Defaults to `test/formal/smt2/`.

    Returns:
        Path to the written .smt2 file.

    Example:
        >>> solver = Solver()
        >>> solver.add(x > 0)
        >>> path = dump_smt2(solver, "example")
        >>> # writes test/formal/smt2/example.smt2
    """
    out_dir: str = output_dir or _SMT2_DIR
    os.makedirs(out_dir, exist_ok=True)

    out_path = Path(out_dir) / f"{name}.smt2"
    out_path.write_text(solver.to_smt2())
    return out_path
