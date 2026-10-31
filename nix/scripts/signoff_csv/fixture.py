"""Deterministic workspace fixture for CI smoke tests.

This module writes the same on-disk product contracts the standalone collector
reads. It is test-only and does not import product code.
"""

import argparse
import json
from pathlib import Path


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _metrics(records: list[tuple[str, float | int]]) -> dict:
    return {
        "schema_version": 3,
        "metrics": [
            {
                "id": metric_id,
                "value": value,
                "unit": "",
                "source": {"kind": "analysis", "path": ""},
            }
            for metric_id, value in records
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args(argv)

    root = Path(args.workspace)
    design = "gcd"

    _write_json(
        root / "home" / "flow.json",
        {
            "design": design,
            "steps": [
                {"name": "Synthesis", "tool": "yosys", "state": "Success"},
                {"name": "postFloorplan", "tool": "ecc", "state": "Success"},
                {"name": "place", "tool": "dreamplace", "state": "Success"},
                {"name": "drc", "tool": "ecc", "state": "Success"},
                {"name": "lvs", "tool": "ecc", "state": "Success"},
                {"name": "sta", "tool": "ecc", "state": "Success"},
                {"name": "postRouteLec", "tool": "kepler_formal", "state": "Success"},
                {"name": "Harden", "tool": "ecc", "state": "Success"},
            ],
        },
    )

    _write_json(root / "Synthesis_yosys" / "analysis" / "qor_metrics.json", _metrics([("synthesis_cell_area", 4200.0)]))
    _write_json(
        root / "postFloorplan_ecc" / "analysis" / "qor_metrics.json",
        _metrics([("die_area", 40000.0), ("core_area", 32000.0), ("core_utilization", 0.62)]),
    )
    _write_json(
        root / "drc_ecc" / "analysis" / "qor_metrics.json",
        _metrics([("drc_count", 0)]),
    )
    _write_json(
        root / "drc_ecc" / "analysis" / "qor_summary.json",
        {
            "schema_version": 4,
            "quality_status": "pass",
            "gates": [
                {
                    "id": "qor.drc.clean",
                    "state": "pass",
                    "title": "DRC clean",
                    "metrics": [{"id": "drc_count", "actual": 0, "operator": "==", "expected": 0}],
                }
            ],
        },
    )
    _write_json(
        root / "sta_ecc" / "analysis" / "qor_metrics.json",
        _metrics(
            [
                ("sta_setup_wns", 1.2),
                ("sta_setup_tns", 0.0),
                ("sta_setup_violation_count", 0),
                ("sta_hold_wns", 0.15),
                ("sta_hold_tns", 0.0),
                ("sta_hold_violation_count", 0),
                ("sta_frequency_mhz", 100.0),
                ("sta_corner_count", 1),
                ("sta_expected_corner_count", 1),
                ("sta_missing_corner_count", 0),
            ]
        ),
    )
    _write_json(
        root / "sta_ecc" / "feature" / "MAX_125" / "RCworst" / "qor_summary.json",
        {
            "summary": {
                "setup": {"wns": 1.2, "tns": 0.0, "nvp": 0, "frequency_mhz": 100.0},
                "hold": {"wns": 0.15, "tns": 0.0, "nvp": 0},
            }
        },
    )

    lec = root / "postRouteLec_kepler_formal" / "output" / f"{design}_postRouteLec_result.json"
    _write_json(
        lec,
        {
            "status": "proven",
            "golden_verilog": "golden.v",
            "gate_verilog": "gate.v",
            "golden_sha256": "0" * 64,
            "gate_sha256": "1" * 64,
            "golden_size_bytes": 10,
            "gate_size_bytes": 20,
        },
    )

    _write_json(
        root / "Harden_ecc" / "analysis" / "qor_metrics.json",
        _metrics(
            [
                ("harden_artifact_missing_count", 0),
                ("die_area", 40000.0),
                ("core_area", 32000.0),
                ("core_utilization", 0.62),
            ]
        ),
    )
    for artifact in ("gds", "lef", "lib"):
        path = root / "Harden_ecc" / "output" / f"{design}_Harden.{artifact}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(artifact, encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
