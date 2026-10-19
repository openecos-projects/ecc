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


def run_smoke(
    binary: Path,
    project: Path,
    workspace: str,
    output: Path,
    *,
    include_dse_contract: bool = False,
) -> dict:
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
    _extensions(
        binary,
        output,
        store,
        project,
        workspace,
        case_id,
        shown[0],
        include_dse_contract=include_dse_contract,
    )
    _model_lifecycle(binary, project, output)
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


def _extensions(
    binary: Path,
    output: Path,
    store: Path,
    project: Path,
    workspace: str,
    case_id: str,
    shown: dict,
    *,
    include_dse_contract: bool,
) -> None:
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
    if include_dse_contract:
        _dse_patience_contract(binary, output, store, project, workspace, features)
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


def _dse_spec(features: dict):
    supported = {"postfloorplan", "place", "cts"}
    direction_by_metric = {
        "sta_setup_wns": "maximize",
        "sta_setup_tns": "maximize",
        "sta_hold_wns": "maximize",
        "sta_hold_tns": "maximize",
        "sta_frequency_mhz": "maximize",
    }
    lower_is_better = {
        "core_area",
        "die_area",
        "place_hpwl",
        "place_grwl",
        "place_flute_wirelength",
        "cts_buffer_count",
        "clock_wirelength",
    }
    for step in features.get("steps", []):
        if step.get("step", "").casefold() not in supported:
            continue
        metric = next(
            (
                item
                for item in step.get("metrics", [])
                if item.get("status") == "available"
                and isinstance(item.get("id"), str)
                and isinstance(item.get("unit"), str)
                and (item["id"] in lower_is_better or item["id"] in direction_by_metric)
            ),
            None,
        )
        if metric is not None:
            return {
                "schema_version": 2,
                "strategy": "adaptive",
                "seed": 7,
                "space": {
                    "floorplan.core_util": {
                        "range": [0.25, 0.55],
                        "step": 0.05,
                    }
                },
                "objectives": [
                    {
                        "metric": metric["id"],
                        "unit": metric["unit"],
                        "direction": direction_by_metric.get(metric["id"], "minimize"),
                    }
                ],
                "rungs": [{"through_step": step["step"], "promote_count": 1}],
                "limits": {
                    "max_trials": 9,
                    "max_seconds": 60,
                    "trial_timeout_seconds": 30,
                    "patience": "auto",
                },
            }
    return None


def _dse_patience_contract(
    binary: Path,
    output: Path,
    store: Path,
    project: Path,
    workspace: str,
    features: dict,
) -> None:
    spec = _dse_spec(features)
    if spec is None:
        (output / "dse-auto-patience.json").write_text(
            json.dumps({"status": "skipped", "reason": "no_supported_stage_metric"}),
            encoding="utf-8",
        )
        return
    spec_path = output / "dse-auto-patience-spec.json"
    plan_path = output / "dse-auto-patience-plan.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    planned = _invoke(
        binary,
        [
            "dse",
            "plan",
            "--project",
            str(project),
            "--workspace",
            workspace,
            "--store",
            str(store),
            "--spec",
            str(spec_path),
            "--output",
            str(plan_path),
        ],
        output,
        "dse-auto-patience",
        {0},
    )
    frozen = json.loads(plan_path.read_text(encoding="utf-8"))
    resolution = frozen.get("patience_resolution")
    if (
        frozen.get("limits", {}).get("patience") != 6
        or resolution is None
        or resolution.get("mode") != "auto"
        or resolution.get("resolved") != 6
        or resolution.get("screening_trials") != 7
    ):
        raise RuntimeError("Packaged DSE plan did not freeze automatic patience")
    if planned[0].get("plan") != str(plan_path.resolve()):
        raise RuntimeError("Packaged DSE plan returned the wrong output path")


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


def _model_lifecycle(binary: Path, project: Path, output: Path) -> None:
    """Exercise the packaged P5 model, registry, and sweep lifecycle."""
    training = output / "model-training.json"
    heldout = output / "model-heldout.json"
    model = output / "model.json"
    evaluation = output / "model-evaluation.json"
    release = output / "model-release.json"
    advice = output / "model-advice.json"
    matrix_a = output / "model-matrix-a.json"
    matrix_b = output / "model-matrix-b.json"
    matrix = output / "model-matrix.json"
    matrix_evaluation = output / "model-matrix-evaluation.json"
    matrix_release = output / "model-matrix-release.json"
    registry = output / "model-registry"

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
                "parameters": {"floorplan.core_util": 0.25 + (index - start) * 0.05},
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
    heldout_rows = make_rows(10, 4)
    for index, item in enumerate(heldout_rows):
        item["input_content_fingerprint"] = f"matrix-input-{index // 2}"
        item["group"] = "family-a" if index < 2 else "family-b"
    write_dataset(matrix_a, "smoke-matrix-a", heldout_rows[:2])
    write_dataset(matrix_b, "smoke-matrix-b", heldout_rows[2:])
    matrix_identity = {
        "schema": "ecc-experience-model-validation-matrix/1",
        "datasets": [
            {"path": matrix_a.name, "design": "design-a", "family": "family-a"},
            {"path": matrix_b.name, "design": "design-b", "family": "family-b"},
        ],
    }
    matrix_identity["matrix_id"] = (
        "matrix-"
        + hashlib.sha256(
            json.dumps(matrix_identity, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    matrix.write_text(json.dumps(matrix_identity), encoding="utf-8")
    _invoke(
        binary,
        ["dataset", "split", "--dataset", str(training), "--output", str(output / "model-split")],
        output,
        "model-split",
        {0},
    )
    _invoke(
        binary,
        [
            "dataset",
            "split",
            "--dataset",
            str(heldout),
            "--by",
            "family",
            "--output",
            str(output / "model-insufficient-split"),
        ],
        output,
        "model-insufficient-split",
        {7},
    )
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
            "evaluate",
            "--model",
            str(model),
            "--dataset",
            str(training),
            "--output",
            str(output / "model-leakage.json"),
        ],
        output,
        "model-leakage",
        {6},
    )
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
    validated = _invoke(
        binary,
        [
            "model",
            "validate",
            "--model",
            str(model),
            "--matrix",
            str(matrix),
            "--output",
            str(matrix_evaluation),
            "--min-independent-designs",
            "2",
        ],
        output,
        "model-matrix-validate",
        {0},
    )
    if validated[0]["status"] != "pass":
        raise RuntimeError("Packaged multi-design model validation did not pass")
    _invoke(
        binary,
        [
            "model",
            "publish",
            "--model",
            str(model),
            "--evaluation",
            str(matrix_evaluation),
            "--output",
            str(matrix_release),
        ],
        output,
        "model-matrix-publish",
        {0},
    )
    advised = _invoke(
        binary,
        [
            "model",
            "advise",
            "--model-release",
            str(matrix_release),
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
    _invoke(
        binary,
        ["model", "promote", "--model-release", str(release), "--registry", str(registry)],
        output,
        "model-promote-initial",
        {0},
    )
    _invoke(
        binary,
        [
            "model",
            "promote",
            "--model-release",
            str(matrix_release),
            "--registry",
            str(registry),
        ],
        output,
        "model-promote",
        {0},
    )
    registry_status = _invoke(
        binary,
        ["model", "registry", "--registry", str(registry)],
        output,
        "model-registry",
        {0},
    )
    if registry_status[0]["status"] != "active":
        raise RuntimeError("Packaged model registry is not active")
    rolled_back = _invoke(
        binary, ["model", "rollback", "--registry", str(registry)], output, "model-rollback", {0}
    )
    if rolled_back[0]["release_id"] != json.loads(release.read_text())["release_id"]:
        raise RuntimeError("Packaged model rollback selected the wrong release")
    sweep_project = output / "model-sweep-project"
    sweep_project.mkdir()
    (sweep_project / "ecc.toml").write_text("", encoding="utf-8")
    seeded = _invoke(
        binary,
        [
            "model",
            "seed-sweep",
            "--project",
            str(sweep_project),
            "--advice",
            str(advice),
            "--model-release",
            str(matrix_release),
            "--name",
            f"model-seeded-{output.name}",
        ],
        output,
        "model-seed-sweep",
        {0},
    )
    if seeded[0]["candidate_count"] != 2:
        raise RuntimeError("Model advice did not seed the expected sweep")
    _native_sweep(binary, sweep_project, seeded[0]["name"], output)


def _native_sweep(binary: Path, project: Path, name: str, output: Path) -> None:
    exported = output / "model-sweep.md"
    commands = [
        (["sweep", "verify"], "model-sweep-verify", 6),
        (["explore", "rank"], "model-sweep-rank", 0),
        (
            ["explore", "export", "--format", "markdown", "--output", str(exported)],
            "model-sweep-export",
            0,
        ),
    ]
    for arguments, label, expected in commands:
        result = subprocess.run(
            [str(binary), *arguments, "--project", str(project), "--name", name],
            check=False,
            capture_output=True,
            text=True,
        )
        (output / f"{label}.stdout.json").write_text(result.stdout, encoding="utf-8")
        (output / f"{label}.stderr").write_text(result.stderr, encoding="utf-8")
        (output / f"{label}.exit").write_text(str(result.returncode), encoding="utf-8")
        if result.returncode != expected or not isinstance(json.loads(result.stdout), (dict, list)):
            raise RuntimeError(f"Native sweep smoke failed: {label}: {result.stderr}")
        if label == "model-sweep-rank" and json.loads(result.stdout) != []:
            raise RuntimeError("Unexecuted advice sweep unexpectedly has measured results")
    if not exported.is_file() or "candidate" not in exported.read_text(encoding="utf-8"):
        raise RuntimeError("Native explore export omitted the seeded sweep")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--include-dse-contract",
        action="store_true",
        help="Run the optional no-flow DSE patience contract smoke",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            run_smoke(
                args.binary.resolve(),
                args.project.resolve(),
                args.workspace,
                args.output,
                include_dse_contract=args.include_dse_contract,
            )
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
