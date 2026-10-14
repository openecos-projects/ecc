"""Check experience CLI collection, idempotence and corruption detection."""

import argparse
import json
import shutil
import subprocess
from pathlib import Path


def _invoke(binary: Path, args: list[str], output: Path, label: str, expected: set[int]) -> list:
    result = subprocess.run(
        [str(binary), "experience", *args, "--json"],
        check=False,
        capture_output=True,
        text=True,
    )
    (output / f"{label}.stdout.json").write_text(result.stdout, encoding="utf-8")
    (output / f"{label}.stderr").write_text(result.stderr, encoding="utf-8")
    (output / f"{label}.exit").write_text(str(result.returncode), encoding="utf-8")
    if result.returncode not in expected:
        raise RuntimeError(
            f"{label} failed with {result.returncode}: {result.stdout}\n{result.stderr}"
        )
    payload = json.loads(result.stdout)
    if not isinstance(payload, list):
        raise RuntimeError(f"{label} did not return CLI records")
    return payload


def run_smoke(binary: Path, project: Path, workspace: str, output: Path) -> dict:
    if output.exists():
        raise FileExistsError("Smoke output must be a new directory")
    output.mkdir(parents=True)
    store = output / "store"
    arguments = [
        "collect",
        "--project",
        str(project),
        "--workspace",
        workspace,
        "--store",
        str(store),
    ]
    first = _invoke(binary, arguments, output, "collect", {0})
    repeated = _invoke(binary, arguments, output, "collect-again", {0})
    case_id = first[0]["case_id"]
    if first[0]["status"] != "created" or repeated[0]["status"] != "already_present":
        raise RuntimeError("Collection is not idempotent")
    if repeated[0]["case_id"] != case_id:
        raise RuntimeError("Repeated collection changed identity")
    listing = _invoke(binary, ["list", "--store", str(store)], output, "list", {0})
    if [record["case_id"] for record in listing] != [case_id]:
        raise RuntimeError("List differs from collection")
    shown = _invoke(binary, ["show", case_id, "--store", str(store)], output, "show", {0})
    verified = _invoke(binary, ["verify", case_id, "--store", str(store)], output, "verify", {0, 7})
    if verified[0]["integrity"] != "pass":
        raise RuntimeError("Stored evidence integrity failed")
    package = output / "experience.tar.gz"
    exported = _invoke(
        binary,
        ["export", "--store", str(store), "--case-id", case_id, "--output", str(package)],
        output,
        "export",
        {0},
    )
    imported_store = output / "imported-store"
    import_arguments = ["import", "--store", str(imported_store), "--package", str(package)]
    imported = _invoke(binary, import_arguments, output, "import", {0})
    imported_again = _invoke(binary, import_arguments, output, "import-again", {0})
    if (
        imported[0]["package_id"] != exported[0]["package_id"]
        or imported[0]["created_count"] != 1
        or imported_again[0]["status"] != "already_present"
    ):
        raise RuntimeError("Experience package round trip is not idempotent")
    imported_case = _invoke(
        binary, ["show", case_id, "--store", str(imported_store)], output, "import-show", {0}
    )
    if imported_case != shown:
        raise RuntimeError("Experience package round trip changed the case")
    damaged_package = output / "damaged-experience.tar.gz"
    damaged_package.write_bytes(b"invalid experience package")
    _invoke(
        binary,
        ["import", "--store", str(output / "rejected-store"), "--package", str(damaged_package)],
        output,
        "import-corrupt",
        {6},
    )
    if (output / "rejected-store").exists():
        raise RuntimeError("Invalid package created a destination store")
    corrupt_store = output / "corrupt-store"
    shutil.copytree(store, corrupt_store)
    evidence = next(item for item in shown[0]["evidence"] if item["stored_path"])
    relative = Path(evidence["stored_path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise RuntimeError("Unsafe stored evidence path")
    (corrupt_store / "cases" / case_id / relative).write_bytes(b"corrupt")
    rejected = _invoke(
        binary,
        ["verify", "--store", str(corrupt_store)],
        output,
        "verify-corrupt",
        {6},
    )
    if rejected[0]["status"] != "fail" or rejected[0]["integrity"] != "fail":
        raise RuntimeError("Corrupt evidence was not rejected")
    _campaign_quality(binary, output, store, case_id, "quality", {7})
    _campaign_quality(binary, output, corrupt_store, case_id, "quality-corrupt", {6})
    return {"status": "pass", "case_id": case_id, "verification": verified[0]["status"]}


def _campaign_quality(
    binary: Path, output: Path, store: Path, case_id: str, label: str, expected: set[int]
) -> None:
    source = output / "campaign-input"
    source.mkdir(exist_ok=True)
    manifest = output / f"{label}-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "campaign_id": label,
                "process_profile": "ics55",
                "store": store.name,
                "output_root": f"{label}-output",
                "mode": "baseline",
                "budget": {
                    "max_concurrent_flows": 1,
                    "max_trials_per_design": 1,
                    "timeout_seconds_per_trial": 60,
                },
                "designs": [
                    {
                        "id": "smoke",
                        "input": {"kind": "ecc-project", "path": source.name},
                        "workspace": "baseline",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    initialized = _invoke(
        binary, ["campaign", "init", "--manifest", str(manifest)], output, f"{label}-init", {0}
    )
    _invoke(
        binary,
        [
            "campaign",
            "record",
            "--ledger",
            initialized[0]["ledger"],
            "--design",
            "smoke",
            "--workspace",
            "baseline",
            "--status",
            "pass",
            "--trial-id",
            "smoke-trial",
            "--case-id",
            case_id,
        ],
        output,
        f"{label}-record",
        {0},
    )
    report = _invoke(
        binary, ["campaign", "quality", "--manifest", str(manifest)], output, label, expected
    )
    if report[0]["counts"]["trials"] != 1:
        raise RuntimeError("Campaign quality did not report the recorded observation")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            run_smoke(args.binary.resolve(), args.project.resolve(), args.workspace, args.output)
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
