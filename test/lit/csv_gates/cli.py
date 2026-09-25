"""CLI: export signoff CSV + gate projection + run manifest."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from csv_gates.bundle import build_csv_bundle, write_csv_bundle
from csv_gates.manifest import build_run_manifest, write_run_manifest
from csv_gates.projection import projection_lines
from csv_gates.spec import CsvSpecError, load_csv_spec


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export signoff CSV + gate projection")
    parser.add_argument("--workspace", required=True, help="Workspace directory")
    parser.add_argument("--out-dir", required=True, help="Output directory")
    parser.add_argument("--spec", required=True, help="CSV/gate profile YAML")
    parser.add_argument("--run-id", default=None, help="Override ECC_SIGNOFF_RUN_ID")
    args = parser.parse_args(argv)

    try:
        from chipcompiler.data import load_workspace
    except ImportError as exc:
        print(f"error: cannot import chipcompiler\n  detail: {exc}", file=sys.stderr)
        return 2

    workspace_dir = Path(args.workspace).resolve()
    out_dir = Path(args.out_dir).resolve()
    if not workspace_dir.is_dir():
        print(f"workspace missing: {workspace_dir}", file=sys.stderr)
        return 1

    workspace = load_workspace(str(workspace_dir), read_only=True)
    if workspace is None:
        print(f"invalid workspace: {workspace_dir}", file=sys.stderr)
        return 1

    try:
        spec = load_csv_spec(str(Path(args.spec).resolve()))
    except CsvSpecError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    csv_dir, reports = out_dir / "csv", out_dir / "reports"
    csv_dir.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)

    bundle = build_csv_bundle(workspace, spec=spec)
    files = write_csv_bundle(bundle, str(csv_dir))
    if not files:
        print("csv export wrote no tables", file=sys.stderr)
        return 1

    lines = projection_lines(csv_dir, bundle.design, spec=spec)
    check_path = reports / "metrics.check.txt"
    check_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    gate_lines = [line for line in lines if line.startswith("gate ")]
    failed = sum(1 for line in gate_lines if "status=fail" in line)
    manifest = build_run_manifest(
        design=bundle.design,
        workspace=workspace_dir,
        spec_path=spec.source_path,
        gates_total=len(gate_lines),
        gates_failed=failed,
        run_id=args.run_id,
    )
    manifest_path = write_run_manifest(manifest, reports / "run_manifest.json")

    print(f"csv → {csv_dir} ({len(files)} files)")
    print(f"projection → {check_path}")
    print(f"manifest → {manifest_path} run_id={manifest.run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
