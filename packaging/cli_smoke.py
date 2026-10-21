"""Smoke-test a packaged ECC executable against a real workspace."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

COMMANDS = (
    ("status", "status", True),
    ("step report", "report step", True),
    ("project report", "report project", False),
    ("signoff check", "signoff check", True),
    ("pdk verify", "pdk verify", False),
)


def _run(binary: Path, args: list[str]) -> tuple[int, object]:
    result = subprocess.run(
        [str(binary), *args, "--json"],
        check=False,
        capture_output=True,
        text=True,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"{binary.name} {' '.join(args)} did not emit JSON: {result.stdout[-500:]}"
        ) from exc
    return result.returncode, payload


def run_smoke(binary: Path, project: Path, workspace: str | None) -> list[dict]:
    if not binary.is_file():
        raise FileNotFoundError(binary)
    common = ["--project", str(project)]
    if workspace:
        common.extend(["--workspace", workspace])
    reports = []
    for name, command, uses_workspace in COMMANDS:
        command_args = command.split() + common
        if not uses_workspace and workspace:
            command_args = command.split() + ["--project", str(project)]
        code, payload = _run(binary, command_args)
        if not isinstance(payload, list) or not payload:
            raise RuntimeError(f"{name} returned an empty/non-list JSON payload")
        reports.append({"command": name, "exit_code": code, "records": len(payload)})
    return reports


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--workspace")
    args = parser.parse_args()
    for report in run_smoke(args.binary, args.project, args.workspace):
        print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
