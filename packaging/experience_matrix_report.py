"""Compatibility wrapper for the ECC experience design-matrix aggregator."""

import argparse
import json
from pathlib import Path

from ecc_experience.benchmark.matrix import aggregate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--expected-designs-json", required=True)
    parser.add_argument(
        "--families-json",
        type=Path,
        help="Optional JSON object mapping design IDs to manually declared family labels",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        expected = json.loads(args.expected_designs_json)
        if not isinstance(expected, list):
            raise ValueError("Expected designs must be a JSON array")
        families = None
        if args.families_json is not None:
            families = json.loads(args.families_json.read_text(encoding="utf-8"))
        report = aggregate(args.inputs, expected, args.output, families)
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "fail", "reason": str(exc)}))
        return 6
    print(json.dumps(report))
    return report["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
