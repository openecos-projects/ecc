"""Smoke-test reproducible CLI commands in a packaged ECC executable."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path


def run(binary: Path, args: list[str], *, json_option: bool = True) -> tuple[int, object]:
    command = [str(binary), *args]
    if json_option:
        command.append("--json")
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{' '.join(args)} did not emit JSON: {result.stdout[-500:]} stderr={result.stderr[-500:]}" ) from exc
    return result.returncode, payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--design", type=Path, required=True)
    parser.add_argument("--e2e-out", type=Path)
    args = parser.parse_args()
    if not args.binary.is_file() or not (args.design / "ecc.toml").is_file():
        raise FileNotFoundError("packaged ECC binary or design ecc.toml is missing")
    with tempfile.TemporaryDirectory(prefix="ecc-repro-smoke-") as directory:
        project = Path(directory) / "project"
        workspace = project / "smoke"
        (workspace / "home").mkdir(parents=True)
        (project / "ecc.toml").write_text((args.design / "ecc.toml").read_text())
        (project / "project.json").write_text("{}\n")
        (workspace / "home" / "flow.json").write_text('{"status":"success","steps":[]}\n')
        (workspace / "home" / "checklist.json").write_text('{"items":[]}\n')
        (workspace / "home" / "qor_report.json").write_text('{"qor_score":1.0}\n')
        package = Path(directory) / "evidence.tar.gz"
        code, exported = run(args.binary, ["reproducible", "export", "--project", str(project), "--workspace", "smoke", "--output", str(package)], json_option=False)
        if code != 0 or exported.get("status") != "success":
            raise RuntimeError(f"export failed: {exported}")
        code, verified = run(args.binary, ["reproducible", "verify", "--package", str(package)])
        if code != 0 or verified.get("status") != "pass":
            raise RuntimeError(f"verify failed: {verified}")
        code, report = run(args.binary, ["reproducible", "report", "--package", str(package)])
        if code != 0 or report.get("verification", {}).get("status") != "pass":
            raise RuntimeError(f"report failed: {report}")
        code, diagnosis = run(args.binary, ["diagnose", "run", "--project", str(project), "--workspace", "smoke"])
        if code != 0 or diagnosis.get("status") not in {"passed", "attention"}:
            raise RuntimeError(f"diagnose failed: {diagnosis}")
        code, plan = run(args.binary, ["sweep", "create", "--project", str(project), "--name", "smoke", "--param", "place.target_density=0.60,0.65"], json_option=False)
        if code != 0 or not plan.get("plan_fingerprint"):
            raise RuntimeError(f"sweep plan failed: {plan}")
    if args.e2e_out and args.e2e_out.is_dir():
        workspaces = sorted(args.e2e_out.rglob("home/flow.json"))
        if workspaces:
            workspace = workspaces[0].parent.parent
            project = workspace.parent.parent
            package = args.e2e_out / "reproducible-e2e.tar.gz"
            code, _ = run(args.binary, ["status", "--project", str(project), "--workspace", str(workspace)])
            if code != 0:
                raise RuntimeError(f"real E2E status failed for {workspace}")
            code, exported = run(args.binary, ["reproducible", "export", "--project", str(project), "--workspace", str(workspace), "--output", str(package)], json_option=False)
            if code != 0 or exported.get("status") != "success":
                raise RuntimeError(f"real E2E export failed: {exported}")
            code, verified = run(args.binary, ["reproducible", "verify", "--package", str(package)])
            if code != 0 or verified.get("status") != "pass":
                raise RuntimeError(f"real E2E verify failed: {verified}")
            print(json.dumps({"status": "pass", "real_workspace": str(workspace)}))
    print(json.dumps({"status": "pass", "design": args.design.name}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
