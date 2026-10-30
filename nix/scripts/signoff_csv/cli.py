"""Standalone CLI: collect signoff product CSVs without product imports."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

_PARENT = Path(__file__).resolve().parents[1]
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))

from signoff_csv.collectors import (  # noqa: E402
    collect_area,
    collect_drc,
    collect_harden,
    collect_lec,
    collect_sta,
)
from signoff_csv.common import flow_ledger, write_csv  # noqa: E402

CHECKS: dict[str, tuple[Callable[[Path, dict[str, Any]], list[dict[str, Any]]], list[str], bool]] = {
    "sta": (collect_sta, ["kind", "corner", "rc_corner", "metric", "value", "unit", "source", "present"], True),
    "drc": (collect_drc, ["kind", "metric", "value", "unit", "gate", "gate_state", "source", "present"], True),
    "lec": (
        collect_lec,
        ["status", "golden_verilog", "golden_sha256", "golden_size_bytes", "gate_verilog", "gate_sha256", "gate_size_bytes", "source", "present"],
        True,
    ),
    "harden": (collect_harden, ["kind", "metric", "value", "unit", "source", "present", "sha256", "bytes"], True),
    "area": (collect_area, ["step", "metric", "value", "unit", "source", "present"], False),
}


def _status(check: str, rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "fail"
    if check == "lec":
        return "pass" if rows[0].get("status") == "proven" else "fail"
    if check == "drc":
        return "pass" if rows[0].get("gate_state") == "pass" else "fail"
    if any(row.get("present") == "false" for row in rows):
        return "fail"
    return "pass"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, help="ECC workspace root")
    parser.add_argument("--out-dir", required=True, help="Output directory for CSV files")
    parser.add_argument(
        "--checks",
        default="sta,drc,lec,harden,area",
        help="Comma-separated check names; defaults to all five",
    )
    args = parser.parse_args(argv)

    workspace = Path(args.workspace).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    flow = flow_ledger(workspace)

    selected = [name.strip() for name in args.checks.split(",") if name.strip()]
    unknown = [name for name in selected if name not in CHECKS]
    if unknown:
        print(f"unknown checks: {', '.join(unknown)}", file=sys.stderr)
        return 2

    manifest_checks: dict[str, Any] = {}
    manifest_files: dict[str, str] = {}
    for check in selected:
        collector, fieldnames, _ = CHECKS[check]
        rows = collector(workspace, flow)
        csv_path = out_dir / f"{check}.csv"
        write_csv(csv_path, fieldnames, rows)
        manifest_checks[check] = {
            "status": _status(check, rows),
            "rows": len(rows),
            "file": csv_path.name,
        }
        manifest_files[check] = str(csv_path)

    gate = "PASS"
    for check, (_, _, mandatory) in CHECKS.items():
        if check in manifest_checks and mandatory and manifest_checks[check]["status"] != "pass":
            gate = "FAIL"
            break

    manifest = {
        "schema_version": 1,
        "kind": "signoff_csv_manifest",
        "workspace": str(workspace),
        "design": str(flow.get("design", "")),
        "checks": manifest_checks,
        "files": manifest_files,
        "gate": gate,
    }
    manifest_path = out_dir / "signoff_csv_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if gate == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
