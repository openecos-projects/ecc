"""One isolated placement and external evaluation pipeline."""

import subprocess
import time
from pathlib import Path

from .artifacts import inspect_placement
from .common import digest, read, require, workspace, write
from .external import EVALUATIONS, evaluate


def run_case(batch: Path, name: str):
    out = batch / "cases" / name
    case = read(out / "case.json")
    target = workspace(batch, name)
    started = time.time()

    def status(stage):
        write(
            out / "status.json",
            {"case": name, "status": "running", "stage": stage, "started_epoch": started},
        )

    try:
        status("placement")
        for key, value in case["inputs"].items():
            require(digest(Path(value)) == case["hashes"][key], f"Changed input: {name}/{key}")
        placement_started = time.perf_counter()
        with (out / "flow.log").open("x") as stream:
            result = subprocess.run(
                [
                    "bash",
                    str(batch / "run_python.sh"),
                    "-m",
                    "chipcompiler.cli.main",
                    "run",
                    "--project",
                    str(target.parent),
                    "--workspace",
                    target.name,
                    "--from",
                    "place",
                    "--to",
                    "place",
                    "--plain",
                ],
                cwd=out,
                stdout=stream,
                stderr=subprocess.STDOUT,
            )
        (out / "flow.exit").write_text(str(result.returncode) + "\n")
        require(result.returncode == 0, f"Placement failed: {name}")
        inspection = inspect_placement(batch, case)
        report = inspection.report
        write(out / "effective-parameters.json", inspection.parameters)
        write(out / "timing-aggregation-effective.json", inspection.aggregation_events)
        report["placement_elapsed_seconds"] = time.perf_counter() - placement_started
        write(out / "placement-report.json", report)
        for stage in EVALUATIONS:
            status(stage)
            report[stage.replace("-", "_")] = evaluate(
                batch, case, stage, Path(report["def"]), Path(report["verilog"])
            )
            write(out / "placement-report.json", report)
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
        state.update(status="failed", finished_epoch=time.time(), error=repr(error))
        write(out / "status.json", state)
        raise
