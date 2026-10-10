"""Audit saved execution evidence independently of process completion."""

from pathlib import Path

from .artifacts import inspect_placement
from .common import cases, content_digest, digest, read, require, write
from .external import EVALUATIONS, parse_metrics
from .reports import collect


def verify_environment(batch: Path):
    provenance = read(batch / "provenance.json")
    require(
        digest(batch / "profile.json") == provenance["profile_sha256"], "Frozen profile changed"
    )
    for filename, value in provenance["runtime_file_hashes"].items():
        require(digest(batch / "runtime" / filename) == value, f"Runtime changed: {filename}")
    for filename, record in read(batch / "pdk_manifest.json").items():
        require(digest(Path(filename)) == record["sha256"], f"PDK changed: {filename}")
    for filename, value in provenance["evaluators"].items():
        require(digest(batch / filename) == value, f"Evaluator changed: {filename}")
    require(
        digest(Path(provenance["openroad_binary"])) == provenance["openroad_sha256"],
        "OpenROAD binary changed",
    )
    # The original standalone batches predate runner/launcher hash fields.
    for filename, value in provenance.get("runner_file_hashes", {}).items():
        require(digest(batch / "runner" / filename) == value, f"Runner changed: {filename}")
    if "launcher_sha256" in provenance:
        require(
            digest(batch / "run_python.sh") == provenance["launcher_sha256"], "Launcher changed"
        )
    return provenance


def verify(batch: Path):
    manifest = cases(batch)
    summary = collect(batch)
    expected = {"completed": len(manifest), "failed": 0, "running": 0, "queued": 0}
    require(summary["counts"] == expected, f"Batch incomplete: {summary['counts']}")
    provenance = verify_environment(batch)
    verified = []
    for case in manifest:
        name = case["name"]
        out = batch / "cases" / name
        saved = read(out / "report.json")
        inspection = inspect_placement(batch, case)
        fresh = inspection.report
        for key in (
            "input_hashes",
            "internal_ns",
            "gp_ns",
            "iterations",
            "final_overflow",
            "grad_balance",
            "routing_grid_preserved",
            "sizing_windows",
            "def",
            "def_sha256",
            "def_content_sha256",
            "verilog",
        ):
            require(
                saved[key] == fresh[key],
                f"Saved report differs from terminal evidence: {name}/{key}",
            )
        require(
            inspection.parameters == read(out / "effective-parameters.json"),
            f"Saved effective parameters changed: {name}",
        )
        for key, value in case["inputs"].items():
            require(digest(Path(value)) == case["hashes"][key], f"Input changed: {name}/{key}")
        require(digest(Path(saved["def"])) == saved["def_sha256"], f"Final DEF changed: {name}")
        require(content_digest(Path(saved["def"])) == saved["def_content_sha256"], name)
        for filename in (
            "pipeline.exit",
            "flow.exit",
            "external-placement/evaluate.exit",
            "external-gr50/evaluate.exit",
        ):
            require(
                (out / filename).read_text().strip() == "0", f"Failed process: {name}/{filename}"
            )
        for stage, specification in EVALUATIONS.items():
            report = saved[stage.replace("-", "_")]
            require(
                report == read(out / stage / "report.json"),
                f"External report changed: {name}/{stage}",
            )
            log = (out / stage / "evaluate.log").read_text()
            require(
                specification.marker in log,
                f"Missing external completion marker: {name}/{stage}",
            )
            timing, checks = parse_metrics(log, specification.prefix)
            require(
                report["timing_ns"] == timing and report["electrical_checks"] == checks,
                f"External metrics differ from stdout: {name}/{stage}",
            )
            require(
                report["status"] == "completed"
                and report["design_unchanged"]
                and report["source_def_sha256"] == saved["def_sha256"],
                f"External result uses a different design: {name}/{stage}",
            )
        verified.append(
            {
                "case": name,
                "sizing_windows": len(saved["sizing_windows"]),
                "iterations": saved["iterations"],
                "def": saved["def"],
                "gp_terminal_objective_terms": fresh["gp_terminal_objective_terms"],
            }
        )
    result = {
        "status": "passed",
        "counts": expected,
        "cases": verified,
        "runtime_hashes_verified": len(provenance["runtime_file_hashes"]),
    }
    write(batch / "verification.json", result)
    return result
