"""Bounded parallel case pipelines; one failed case does not hide the others."""

import concurrent.futures
import subprocess
import time
from pathlib import Path

from .common import cases, read, require, write
from .reports import collect
from .verify import verify, verify_environment


def launch(batch: Path, case: dict):
    name = case["name"]
    out = batch / "cases" / name
    with (out / "pipeline.log").open("x") as stream:
        process = subprocess.Popen(
            [
                "bash",
                str(batch / "run_python.sh"),
                "-m",
                "scripts.regression.placement",
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
        write(
            out / "process.json", {"pid": process.pid, "started_epoch": time.time(), "case": name}
        )
        code = process.wait()
    (out / "pipeline.exit").write_text(str(code) + "\n")
    state = read(out / "status.json")
    if code or state["status"] != "completed":
        state.update(status="failed", pipeline_exit=code, finished_epoch=time.time())
        write(out / "status.json", state)
    return name, code


def run(batch: Path, jobs: int):
    require(jobs > 0, "jobs must be positive")
    manifest = cases(batch)
    require((batch / "prepare.exit").read_text().strip() == "0", "Preparation did not succeed")
    require(
        all(
            read(batch / "cases" / c["name"] / "status.json")["status"] == "queued"
            and not (batch / "cases" / c["name"] / "pipeline.log").exists()
            for c in manifest
        ),
        "Batch has already started; prepare a fresh output directory",
    )
    verify_environment(batch)
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
        pending = {pool.submit(launch, batch, case): case["name"] for case in order}
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
    code = int(counts["completed"] != len(manifest) or counts["failed"] != 0)
    if not code:
        try:
            verify(batch)
        except Exception as error:
            code = 1
            write(batch / "verification.json", {"status": "failed", "error": repr(error)})
    write(
        batch / "batch-final-summary.json",
        {
            "status": "completed" if not code else "failed",
            "counts": counts,
            "started_epoch": started,
            "finished_epoch": time.time(),
            "elapsed_seconds": time.time() - started,
            "results": str(batch / "results.md"),
            "verification": "passed" if not code else "failed_or_incomplete",
        },
    )
    (batch / "batch.exit").write_text(str(code) + "\n")
    return code
