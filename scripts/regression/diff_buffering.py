"""Run frozen standalone buffering cases and their external timing evaluations."""

import argparse
import concurrent.futures
import csv
import gzip
import importlib.util
import io
import json
import math
import re
import subprocess
import time
from collections import Counter
from pathlib import Path

from scripts.regression.placement.common import (
    cases,
    digest,
    effective_parameters,
    read,
    require,
    write,
    write_text,
)
from scripts.regression.placement.external import EVALUATIONS, evaluate
from scripts.regression.placement.verify import verify_environment


def components(path: Path):
    with gzip.open(path, "rt") as stream:
        text = stream.read()
    section = text.split("COMPONENTS ", 1)[1].split("END COMPONENTS", 1)[0]
    return dict(re.findall(r"^\s*-\s+(\S+)\s+(\S+)", section, re.M))


def inspect_buffering(batch: Path, case: dict):
    name = case["name"]
    workspace = batch / "projects" / name / "buffering"
    step = workspace / "diff_buffering_dreamplace"
    flow = read(workspace / "home/flow.json")["steps"]
    require(
        [(row["name"], row["state"]) for row in flow] == [("diff_buffering", "Success")],
        f"Incomplete buffering flow: {name}",
    )
    summary = read(step / "data/diff_buffering/diff_buffering_summary.json")
    require(summary["status"] == "ok" and summary["legal"], f"Illegal buffering output: {name}")
    require(
        summary["new_gp_optimizer_steps"]
        == summary["sizing_steps"]
        == summary["virtual_count"]
        == 0,
        f"Unexpected optimization lane: {name}",
    )
    params = effective_parameters(step / "log/diff_buffering.log")
    profile = read(batch / "profile.json")
    expected = {
        "flow_kind": "buffering",
        "placement_sizing_mode": "place_only",
        "buffering_candidate_drive_type_mode": "four_strength_table",
        "buffering_candidate_strategy": "discrete_net_gradient",
        "buffering_continuous_steps": profile["diff_buffering_rounds"],
        "buffering_route_b_selection_fraction": profile["diff_buffering_selection_fraction"],
        "buffering_max_repeaters_per_segment": 3,
        "num_threads": profile["num_threads"],
        "timing_aggregation_mode": profile["timing_aggregation_mode"],
        "timing_aggregation_tau_ps": profile["timing_aggregation_tau_ps"],
        "timing_wns_coeff": profile["diff_buffering_coefficients"]["wns"],
        "timing_tns_coeff": profile["diff_buffering_coefficients"]["tns"],
        "timing_cap_weight": profile["diff_buffering_coefficients"]["cap"],
        "timing_slew_weight": profile["diff_buffering_coefficients"]["slew"],
        "random_center_init_flag": 0,
        "cell_padding_x": 0,
        "timing_grad_balance_weight": 1.0,
    }
    require({key: params[key] for key in expected} == expected, f"Wrong profile: {name}")
    definition = step / "output" / f"{name}_diff_buffering.def.gz"
    netlist = step / "output" / f"{name}_diff_buffering.v.gz"
    require(netlist.is_file(), f"Missing buffered netlist: {name}")
    before, after = components(Path(case["inputs"]["def"])), components(definition)
    require(
        all(after.get(instance) == master for instance, master in before.items()),
        f"Buffering changed an existing cell master: {name}",
    )
    added = {instance: master for instance, master in after.items() if instance not in before}
    require(
        not summary["commit"].get("rejected_action_count", 0)
        and not summary["commit"].get("failed_action_count", 0),
        f"Partially accepted native commit: {name}",
    )
    require(
        len(added) == int(summary["commit"].get("accepted_action_count", 0)),
        f"Buffer count differs from native commit: {name}",
    )
    require(set(added.values()) <= set(case["pdk"]["buffers"]), f"Wrong buffer master: {name}")
    areas = read(batch / "master_areas.json")
    input_area = sum(areas[master] for master in before.values())
    output_area = sum(areas[master] for master in after.values())
    timing = {key: summary["final_timing"][key] / 1000.0 for key in ("wns", "tns")}
    require(all(math.isfinite(value) for value in timing.values()), f"Nonfinite STA: {name}")
    write(batch / "cases" / name / "effective-parameters.json", params)
    return {
        "case": name,
        "status": "running",
        "internal_ns": timing,
        "rounds": summary["buffering"]["iterations"],
        "inserted_buffers": len(added),
        "drive_master_counts": dict(Counter(added.values())),
        "input_cell_area_um2": input_area,
        "cell_area_um2": output_area,
        "area_increase_pct": 100.0 * (output_area / input_area - 1.0),
        "existing_masters_unchanged": True,
        "legal": True,
        "def": str(definition),
        "verilog": str(netlist),
        "def_sha256": digest(definition),
        "verilog_sha256": digest(netlist),
        "source_stage": "initial placement output, before diff_sizing",
    }


def worker(batch: Path, name: str):
    out = batch / "cases" / name
    case = read(out / "case.json")
    started = time.time()

    def status(stage, **extra):
        write(
            out / "status.json",
            {"case": name, "status": "running", "stage": stage, "started_epoch": started, **extra},
        )

    try:
        specs = {
            package: importlib.util.find_spec(package)
            for package in ("chipcompiler", "dreamplace", "ecc_tools_bin")
        }
        imports = {package: spec.origin if spec else None for package, spec in specs.items()}
        require(
            all(
                path is not None and Path(path).is_relative_to(batch / "runtime")
                for path in imports.values()
            ),
            f"Worker imported live sources: {imports}",
        )
        write(out / "imports.json", imports)
        for key, value in case["inputs"].items():
            require(digest(Path(value)) == case["hashes"][key], f"Changed input: {name}/{key}")
        status("diff_buffering")
        buffering_started = time.perf_counter()
        # sys.executable is the frozen Nix-compatible ELF. Starting the CLI
        # directly preserves its loader without invoking a system shell.
        import sys

        with (out / "flow.log").open("x") as stream:
            process = subprocess.run(
                [
                    sys.executable,
                    "-S",
                    "-m",
                    "chipcompiler.cli.main",
                    "run",
                    "--project",
                    str(batch / "projects" / name),
                    "--workspace",
                    "buffering",
                    "--from",
                    "diff_buffering",
                    "--to",
                    "diff_buffering",
                    "--plain",
                ],
                cwd=out,
                stdout=stream,
                stderr=subprocess.STDOUT,
            )
        (out / "flow.exit").write_text(str(process.returncode) + "\n")
        require(process.returncode == 0, f"Buffering failed: {name}")
        report = inspect_buffering(batch, case)
        report["buffering_elapsed_seconds"] = time.perf_counter() - buffering_started
        write(out / "buffering-report.json", report)
        for stage in EVALUATIONS:
            status(stage)
            report[stage.replace("-", "_")] = evaluate(
                batch, case, stage, Path(report["def"]), Path(report["verilog"])
            )
            write(out / "buffering-report.json", report)
        report.update(status="completed", elapsed_seconds=time.time() - started)
        write(out / "report.json", report)
        write(
            out / "status.json",
            {
                "case": name,
                "status": "completed",
                "stage": "finished",
                "started_epoch": started,
                "finished_epoch": time.time(),
            },
        )
    except Exception as error:
        state = read(out / "status.json")
        state.update(status="failed", error=repr(error), finished_epoch=time.time())
        write(out / "status.json", state)
        raise


def collect(batch: Path):
    rows = []
    counts = dict.fromkeys(("completed", "failed", "running", "queued"), 0)
    for case in cases(batch):
        out = batch / "cases" / case["name"]
        state = read(out / "status.json")
        counts[state["status"]] += 1
        path = out / "report.json"
        if not path.exists():
            path = out / "buffering-report.json"
        report = read(path) if path.exists() else {}
        source = read(out / "source-report.json")
        row = {"case": case["name"], "status": state["status"], "stage": state["stage"]}
        for label, data in (
            ("input_placement", source["external_placement"]["timing_ns"]),
            ("input_gr50", source["external_gr50"]["timing_ns"]),
            ("internal", report.get("internal_ns", {})),
            ("placement", report.get("external_placement", {}).get("timing_ns", {})),
            ("gr50", report.get("external_gr50", {}).get("timing_ns", {})),
        ):
            row.update({label + "_" + key: data.get(key) for key in ("wns", "tns")})
        for key in ("inserted_buffers", "area_increase_pct", "buffering_elapsed_seconds"):
            row[key] = report.get(key)
        row["error"] = state.get("error")
        rows.append(row)
    result = {
        "scope": "standalone diff_buffering; TT ideal-clock external placement RC and GR50 STA",
        "profile": read(batch / "profile.json"),
        "counts": counts,
        "rows": rows,
    }
    write(batch / "results.json", result)
    write(batch / "batch-status.json", counts)
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    write_text(batch / "results.csv", stream.getvalue())
    lines = [
        "Standalone buffering regression. Timing in ns; physical cell area excludes padding.",
        "",
        "| Case | Input GR50 WNS / TNS | Buffered internal | External placement RC | "
        "External GR50 | Buffers | Area increase | Status |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        pairs = []
        for label in ("input_gr50", "internal", "placement", "gr50"):
            a, b = row[label + "_wns"], row[label + "_tns"]
            pairs.append("—" if a is None or b is None else f"{a:.3f} / {b:.3f}")
        area = row["area_increase_pct"]
        lines.append(
            "| "
            + " | ".join(
                [
                    row["case"],
                    *pairs,
                    str(row["inserted_buffers"] or 0) if area is not None else "—",
                    "—" if area is None else f"{area:+.2f}%",
                    row["status"] + ": " + row["stage"],
                ]
            )
            + " |"
        )
    write_text(batch / "results.md", "\n".join(lines) + "\n")
    return result


def launch(batch: Path, name: str):
    out = batch / "cases" / name
    with (out / "pipeline.log").open("x") as stream:
        process = subprocess.Popen(
            [
                "bash",
                str(batch / "run_python.sh"),
                "-m",
                "scripts.regression.diff_buffering",
                "worker",
                "--batch",
                str(batch),
                "--case",
                name,
            ],
            cwd=out,
            stdout=stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        write(out / "process.json", {"pid": process.pid, "started_epoch": time.time()})
        code = process.wait()
    (out / "pipeline.exit").write_text(str(code) + "\n")
    state = read(out / "status.json")
    if code or state["status"] != "completed":
        state.update(status="failed", pipeline_exit=code, finished_epoch=time.time())
        write(out / "status.json", state)
    return name, code


def run(batch: Path, jobs: int):
    require(jobs > 0, "jobs must be positive")
    verify_environment(batch)
    manifest = cases(batch)
    require(
        all(
            read(batch / "cases" / c["name"] / "status.json")["status"] == "queued"
            for c in manifest
        ),
        "Batch has already started",
    )
    order = sorted(manifest, key=lambda case: case["component_count"], reverse=True)
    started = time.time()
    write(
        batch / "launch.json",
        {
            "max_parallel_cases": jobs,
            "started_epoch": started,
            "order": [case["name"] for case in order],
        },
    )
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        pending = {pool.submit(launch, batch, case["name"]): case["name"] for case in order}
        while pending:
            done, _ = concurrent.futures.wait(
                pending, timeout=30, return_when=concurrent.futures.FIRST_COMPLETED
            )
            for future in done:
                name = pending.pop(future)
                try:
                    print("FINISHED", future.result(), flush=True)
                except Exception as error:
                    write(
                        batch / "cases" / name / "status.json",
                        {
                            "case": name,
                            "status": "failed",
                            "stage": "orchestration",
                            "error": repr(error),
                        },
                    )
            print("STATUS", collect(batch)["counts"], flush=True)
    counts = collect(batch)["counts"]
    code = int(counts != {"completed": len(manifest), "failed": 0, "running": 0, "queued": 0})
    if not code:
        try:
            verify_environment(batch)
            for case in manifest:
                out = batch / "cases" / case["name"]
                report = read(out / "report.json")
                fresh = inspect_buffering(batch, case)
                require(
                    all(report[key] == value for key, value in fresh.items() if key != "status"),
                    f"Terminal artifacts changed: {case['name']}",
                )
                for filename in (
                    "pipeline.exit",
                    "flow.exit",
                    "external-placement/evaluate.exit",
                    "external-gr50/evaluate.exit",
                ):
                    require(
                        (out / filename).read_text().strip() == "0",
                        f"Failed exit: {out}/{filename}",
                    )
            write(batch / "verification.json", {"status": "passed", "cases": len(manifest)})
        except Exception as error:
            code = 1
            write(batch / "verification.json", {"status": "failed", "error": repr(error)})
    write(
        batch / "batch-final-summary.json",
        {
            "status": "completed" if not code else "failed",
            "counts": counts,
            "elapsed_seconds": time.time() - started,
        },
    )
    (batch / "batch.exit").write_text(str(code) + "\n")
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "worker", "collect"))
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--case")
    parser.add_argument("--jobs", type=int, default=6)
    args = parser.parse_args()
    if args.command == "run":
        return run(args.batch, args.jobs)
    if args.command == "worker":
        worker(args.batch, args.case)
    else:
        print(json.dumps(collect(args.batch)["counts"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
