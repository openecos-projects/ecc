#!/usr/bin/env python3
"""Load / verify / diff in-repo signoff baseline versions (durable vs artifacts).

In:
    nix/signoff-baseline/index.json + versions/*.json
Out:
    list / verify status / diff / matrix JSON on stdout or --out
Entry:
    main()  nix/scripts/signoff_baseline.py
    .github workflow (Verify in-repo multi-version baseline)
See:
    check_metric()          chipcompiler/runtime/signoff/qor_perf_support.py
    generate-signoff-kanban.py  nix/scripts/generate-signoff-kanban.py

Usage:
  PYTHONPATH=. python nix/scripts/signoff_baseline.py list
  PYTHONPATH=. python nix/scripts/signoff_baseline.py verify
  PYTHONPATH=. python nix/scripts/signoff_baseline.py diff \\
      --from v2026-09-synth --to v2026-10-runtime
  PYTHONPATH=. python nix/scripts/signoff_baseline.py export-matrix --out matrix.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _baseline_root(root: Path | None = None) -> Path:
    return (root or _repo_root()) / "nix" / "signoff-baseline"


def load_index(baseline_root: Path) -> dict[str, Any]:
    path = baseline_root / "index.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("kind") != "signoff_baseline_index":
        raise ValueError(f"invalid baseline index: {path}")
    return data


def load_snapshot(baseline_root: Path, rel_path: str) -> dict[str, Any]:
    path = baseline_root / rel_path
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("kind") != "signoff_baseline_snapshot":
        raise ValueError(f"invalid baseline snapshot: {path}")
    return data


def iter_versions(baseline_root: Path) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    index = load_index(baseline_root)
    versions = index.get("versions")
    if not isinstance(versions, list) or not versions:
        raise ValueError("baseline index has no versions")
    out: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for entry in versions:
        if not isinstance(entry, dict):
            raise ValueError("baseline version entry must be an object")
        rel = entry.get("path")
        if not isinstance(rel, str) or not rel:
            raise ValueError(f"version entry missing path: {entry!r}")
        snap = load_snapshot(baseline_root, rel)
        if snap.get("id") != entry.get("id"):
            raise ValueError(
                f"snapshot id {snap.get('id')!r} != index id {entry.get('id')!r} ({rel})"
            )
        out.append((entry, snap))
    return out


def cmd_list(baseline_root: Path) -> int:
    for entry, snap in iter_versions(baseline_root):
        metrics = snap.get("metrics") if isinstance(snap.get("metrics"), dict) else {}
        print(
            f"{entry['id']}\t{snap.get('readiness')}\t{snap.get('status')}\t"
            f"drc={metrics.get('drc_count')}\t"
            f"setup_wns={metrics.get('sta_setup_wns')}\t{entry.get('label', '')}"
        )
    return 0


def cmd_verify(baseline_root: Path) -> int:
    rows = iter_versions(baseline_root)
    required = ("drc_count", "sta_setup_wns", "sta_hold_wns")
    for entry, snap in rows:
        metrics = snap.get("metrics")
        if not isinstance(metrics, dict):
            raise ValueError(f"{entry['id']}: metrics missing")
        for key in required:
            if key not in metrics:
                raise ValueError(f"{entry['id']}: missing metric {key}")
            value = metrics[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{entry['id']}: metric {key} not numeric")
        readiness = snap.get("readiness")
        if readiness not in {"PASS", "WARN", "MISS", "ERROR"}:
            raise ValueError(f"{entry['id']}: bad readiness {readiness!r}")
    print(f"ok: {len(rows)} baseline versions under {baseline_root}")
    return 0


def cmd_diff(baseline_root: Path, from_id: str, to_id: str) -> int:
    by_id = {entry["id"]: snap for entry, snap in iter_versions(baseline_root)}
    if from_id not in by_id or to_id not in by_id:
        raise SystemExit(f"unknown version id (have: {sorted(by_id)})")
    left, right = by_id[from_id], by_id[to_id]
    print(f"readiness: {left.get('readiness')} -> {right.get('readiness')}")
    print(f"status: {left.get('status')} -> {right.get('status')}")
    left_m = left.get("metrics") if isinstance(left.get("metrics"), dict) else {}
    right_m = right.get("metrics") if isinstance(right.get("metrics"), dict) else {}
    keys = sorted(set(left_m) | set(right_m))
    for key in keys:
        lv, rv = left_m.get(key), right_m.get(key)
        mark = "" if lv == rv else " *"
        print(f"metric {key}: {lv} -> {rv}{mark}")
    return 0


def cmd_export_matrix(baseline_root: Path, out: Path) -> int:
    rows = []
    for entry, snap in iter_versions(baseline_root):
        metrics = snap.get("metrics") if isinstance(snap.get("metrics"), dict) else {}
        rows.append(
            {
                "id": entry["id"],
                "label": entry.get("label"),
                "readiness": snap.get("readiness"),
                "status": snap.get("status"),
                "recorded_at": snap.get("recorded_at"),
                "metrics": metrics,
            }
        )
    payload = {
        "schema_version": 1,
        "kind": "signoff_baseline_matrix",
        "versions": rows,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline-root",
        type=Path,
        default=None,
        help="defaults to <repo>/nix/signoff-baseline",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="print version table")
    sub.add_parser("verify", help="validate index + snapshots")

    p_diff = sub.add_parser("diff", help="diff two version ids")
    p_diff.add_argument("--from", dest="from_id", required=True)
    p_diff.add_argument("--to", dest="to_id", required=True)

    p_export = sub.add_parser("export-matrix", help="write matrix JSON for CI artifact")
    p_export.add_argument("--out", type=Path, required=True)

    args = parser.parse_args(argv)
    baseline_root = args.baseline_root or _baseline_root()
    if args.cmd == "list":
        return cmd_list(baseline_root)
    if args.cmd == "verify":
        return cmd_verify(baseline_root)
    if args.cmd == "diff":
        return cmd_diff(baseline_root, args.from_id, args.to_id)
    if args.cmd == "export-matrix":
        return cmd_export_matrix(baseline_root, args.out)
    raise SystemExit(f"unknown command {args.cmd}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 — CLI boundary
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
