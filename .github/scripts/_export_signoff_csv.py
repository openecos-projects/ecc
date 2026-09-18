#!/usr/bin/env python3
"""Implementation for export_signoff_csv.sh — do not call from CI directly.

Tabularizes QoR/checklist/flow already on disk; writes csv/ + metrics.check.txt.
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=Path("ci-artifacts/eda-signoff"))
    parser.add_argument(
        "--spec",
        type=Path,
        default=REPO_ROOT / "test" / "support" / "csv_profiles" / "signoff.yml",
    )
    args = parser.parse_args(argv)

    for path in (REPO_ROOT, REPO_ROOT / "test"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))

    from support.csv_export import build_csv_bundle, write_csv_bundle
    from support.csv_projection import write_projection
    from support.csv_spec import load_csv_spec

    from chipcompiler.data import load_workspace

    workspace_dir = args.workspace.resolve()
    if not workspace_dir.is_dir():
        print(f"workspace missing: {workspace_dir}", file=sys.stderr)
        return 1

    out_dir = args.out_dir.resolve()
    csv_dir = out_dir / "csv"
    reports = out_dir / "reports"
    for path in (csv_dir, reports):
        path.mkdir(parents=True, exist_ok=True)

    workspace = load_workspace(str(workspace_dir))
    if workspace is None:
        print(f"invalid workspace: {workspace_dir}", file=sys.stderr)
        return 1

    spec = load_csv_spec(str(args.spec.resolve()))
    bundle = build_csv_bundle(workspace, spec=spec)
    files = write_csv_bundle(bundle, str(csv_dir))
    if not files:
        print("csv export wrote no tables", file=sys.stderr)
        return 1

    check_path = write_projection(csv_dir, bundle.design, reports / "metrics.check.txt")
    print(f"csv → {csv_dir} ({len(files)} files)")
    print(f"projection → {check_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
