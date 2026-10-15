"""Check packaged experience evidence, feature queries and controlled entry points."""

import argparse
import hashlib
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
    _extensions(binary, output, store, case_id, shown[0])
    _model_lifecycle(binary, output)
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
    _invoke(
        binary,
        ["features", case_id, "--store", str(corrupt_store)],
        output,
        "features-corrupt",
        {6},
    )
    _campaign_quality(binary, output, store, case_id, "quality", {7})
    _campaign_quality(binary, output, corrupt_store, case_id, "quality-corrupt", {6})
    return {"status": "pass", "case_id": case_id, "verification": verified[0]["status"]}


def _extensions(binary: Path, output: Path, store: Path, case_id: str, shown: dict) -> None:
    features = _invoke(
        binary, ["features", case_id, "--store", str(store)], output, "features", {0}
    )[0]
    if features["case_id"] != case_id or features["visibility"] != "complete_observation":
        raise RuntimeError("Feature query lost its case identity or visibility")
    steps = shown["facts"]["flow"]["steps"]
    if steps:
        boundary = steps[0]["name"]
        prefix = _invoke(
            binary,
            ["features", case_id, "--store", str(store), "--through-step", boundary],
            output,
            "features-prefix",
            {0},
        )[0]
        if prefix["visibility"] != "flow_prefix" or [item["step"] for item in prefix["steps"]] != [
            boundary
        ]:
            raise RuntimeError("Feature prefix exposed later flow steps")
        invalid_release = output / "invalid-release.json"
        invalid_release.write_text("{}", encoding="utf-8")
        _invoke(
            binary,
            [
                "match",
                case_id,
                "--store",
                str(store),
                "--release",
                str(invalid_release),
                "--through-step",
                boundary,
            ],
            output,
            "match-invalid-release",
            {2},
        )
    invalid_plan = output / "invalid-dse-plan.json"
    invalid_plan.write_text("{}", encoding="utf-8")
    _invoke(
        binary,
        ["dse", "run", "--plan", str(invalid_plan), "--output", str(output / "rejected-dse")],
        output,
        "dse-invalid-plan",
        {2},
    )
    invalid_spec = output / "invalid-study.json"
    invalid_spec.write_text("{}", encoding="utf-8")
    _invoke(
        binary,
        [
            "study",
            "evaluate",
            "--spec",
            str(invalid_spec),
            "--store",
            str(store),
            "--output",
            str(output / "rejected-study.json"),
        ],
        output,
        "study-invalid-spec",
        {2},
    )
    _invoke(
        binary,
        [
            "study",
            "publish",
            "--evaluation",
            str(invalid_spec),
            "--store",
            str(store),
            "--output",
            str(output / "rejected-release.json"),
        ],
        output,
        "study-invalid-report",
        {2},
    )
    if any(
        (output / name).exists()
        for name in ("rejected-dse", "rejected-study.json", "rejected-release.json")
    ):
        raise RuntimeError("Rejected experience input created execution or publication output")


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


def _model_lifecycle(binary: Path, output: Path) -> None:
    """Exercise the packaged P4 commands with a generic, non-design fixture."""
    training = output / "model-training.json"
    heldout = output / "model-heldout.json"
    model = output / "model.json"
    evaluation = output / "model-evaluation.json"
    release = output / "model-release.json"
    advice = output / "model-advice.json"

    def make_rows(start: int, count: int) -> list[dict]:
        return [
            {
                "case_id": f"model-case-{index}",
                "input_content_fingerprint": f"model-input-{index}",
                "group": "family-a" if index % 2 else "family-b",
                "attempt_id": f"model-attempt-{index}",
                "features": {
                    "constant": 1.0,
                    "spec.utilization": float(index - start + 1 + (0.5 if start else 0)),
                },
                "target": 100.0 + 2.0 * (index - start + 1 + (0.5 if start else 0)),
                "parameters": {
                    "floorplan.core_util": float(index - start + 1 + (0.5 if start else 0))
                },
                "process_fingerprint": "smoke-process",
                "runtime": {"ecc": "smoke", "openroad": "installed"},
            }
            for index in range(start, start + count)
        ]

    def write_dataset(path: Path, release_id: str, rows: list[dict]) -> None:
        identity = {
            "schema": "ecc-experience-model-dataset/1",
            "feature_schema": "ecc-experience-model-features/1",
            "release_id": release_id,
            "release_sha256": f"sha-{release_id}",
            "target": "final_qor",
            "through_step": "Synthesis",
            "groups": {row["case_id"]: row["group"] for row in rows},
            "rows": rows,
        }
        identity_bytes = json.dumps(
            identity, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        payload = {
            **identity,
            "dataset_id": "dataset-" + hashlib.sha256(identity_bytes).hexdigest(),
            "summary": {"row_count": len(rows)},
            "excluded": [],
            "limitations": [],
        }
        path.write_text(json.dumps(payload), encoding="utf-8")

    write_dataset(training, "smoke-training", make_rows(0, 6))
    write_dataset(heldout, "smoke-heldout", make_rows(10, 4))
    _invoke(
        binary,
        ["model", "train", "--dataset", str(training), "--output", str(model)],
        output,
        "model-train",
        {0},
    )
    evaluated = _invoke(
        binary,
        [
            "model",
            "evaluate",
            "--model",
            str(model),
            "--dataset",
            str(heldout),
            "--output",
            str(evaluation),
        ],
        output,
        "model-evaluate",
        {0},
    )
    if evaluated[0]["status"] != "pass":
        raise RuntimeError("Packaged model evaluation did not pass")
    _invoke(
        binary,
        [
            "model",
            "publish",
            "--model",
            str(model),
            "--evaluation",
            str(evaluation),
            "--output",
            str(release),
        ],
        output,
        "model-publish",
        {0},
    )
    advised = _invoke(
        binary,
        [
            "model",
            "advise",
            "--model-release",
            str(release),
            "--dataset",
            str(heldout),
            "--output",
            str(advice),
            "--limit",
            "2",
        ],
        output,
        "model-advise",
        {0},
    )
    if advised[0]["safe_to_apply"] is not False or not advice.is_file():
        raise RuntimeError("Packaged model advice was not read-only")


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
