#!/usr/bin/env python3
"""CI: run ics55 gcd rtl2gds through a packaged ``ecc`` binary.

Requires ``ECC_BIN`` (absolute path to the PyInstaller ``ecc`` executable).
Creates ``--project-dir``, copies fixture RTL, sets the PDK root, then
``ecc run --workspace default``.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run(ecc: Path, args: list[str], *, cwd: Path | None = None) -> None:
    cmd = [str(ecc), *args]
    print("+", " ".join(cmd), flush=True)
    completed = subprocess.run(cmd, cwd=cwd, check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ecc",
        type=Path,
        default=Path(os.environ["ECC_BIN"]) if os.environ.get("ECC_BIN") else None,
        help="Packaged ecc binary (or set ECC_BIN)",
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=Path("ci-artifacts/gcd"),
        help="Project directory created by ecc init",
    )
    parser.add_argument(
        "--pdk-root",
        type=Path,
        default=None,
        help="icsprout55-pdk root (default: ../pdk/icsprout55-pdk relative to repo)",
    )
    parser.add_argument(
        "--workspace-name",
        default="default",
        help="Managed workspace name passed to ecc run",
    )
    args = parser.parse_args(argv)

    if args.ecc is None:
        print("missing --ecc / ECC_BIN (packaged ecc binary required)", file=sys.stderr)
        return 2
    ecc = args.ecc.resolve()
    if not ecc.is_file() or not os.access(ecc, os.X_OK):
        print(f"ecc binary not executable: {ecc}", file=sys.stderr)
        return 2

    verilog = REPO_ROOT / "test" / "fixtures" / "gcd" / "gcd.v"
    if not verilog.is_file():
        print(f"missing fixture RTL: {verilog}", file=sys.stderr)
        return 1

    pdk_root = (
        args.pdk_root.resolve()
        if args.pdk_root is not None
        else (REPO_ROOT.parent / "pdk" / "icsprout55-pdk").resolve()
    )
    if not pdk_root.is_dir():
        # CI clones to ../pdk from the repo working directory.
        alt = (Path.cwd().parent / "pdk" / "icsprout55-pdk").resolve()
        pdk_root = alt if alt.is_dir() else pdk_root
    if not pdk_root.is_dir():
        print(f"PDK root missing: {pdk_root}", file=sys.stderr)
        return 1

    project_dir = args.project_dir.resolve()
    if project_dir.exists():
        shutil.rmtree(project_dir)
    project_dir.parent.mkdir(parents=True, exist_ok=True)

    # ecc init creates <name>/ relative to cwd; pass path as the project name.
    _run(ecc, ["init", str(project_dir), "--plain"])

    rtl_dest = project_dir / "rtl" / "gcd.v"
    rtl_dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(verilog, rtl_dest)

    _run(ecc, ["pdk", "set-root", str(pdk_root), "--project", str(project_dir), "--plain"])
    _run(
        ecc,
        [
            "run",
            "--project",
            str(project_dir),
            "--workspace",
            args.workspace_name,
            "--plain",
        ],
    )

    workspace = project_dir / args.workspace_name
    marker = project_dir.parent / "eda-gcd.ok"
    if not (workspace / "home" / "flow.json").is_file():
        if marker.exists():
            marker.unlink()
        print(f"EDA rtl2gds failed → missing flow.json under {workspace}", file=sys.stderr)
        return 1

    marker.write_text(str(workspace) + "\n", encoding="utf-8")
    print(f"EDA rtl2gds ok → {workspace}")
    print(f"ECC_WORKSPACE={workspace}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
