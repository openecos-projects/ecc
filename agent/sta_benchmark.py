"""Compare full-corner STA schedules on isolated copies of one routed workspace."""

import argparse
import hashlib
import importlib.metadata
import json
import math
import multiprocessing
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path


def _inventory(root):
    if not root.is_dir():
        raise ValueError("benchmark source must be an existing workspace directory")
    result = {}
    for directory, names, files in os.walk(root):
        names[:] = sorted(name for name in names if name != ".agent")
        if any((Path(directory) / name).is_symlink() for name in names):
            raise ValueError("benchmark source contains a directory symlink")
        for name in sorted(files):
            path = Path(directory) / name
            if path.is_symlink():
                raise ValueError(f"benchmark source contains a symlink: {path}")
            with path.open("rb") as stream:
                result[str(path.relative_to(root))] = hashlib.file_digest(
                    stream, "sha256"
                ).hexdigest()
    return result


def _tree_rss_mb(pid):
    pending, visited, rss = [pid], set(), 0
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        visited.add(current)
        try:
            rss += int(Path(f"/proc/{current}/statm").read_text().split()[1])
            for path in Path(f"/proc/{current}/task").glob("*/children"):
                pending.extend(int(value) for value in path.read_text().split())
        except (FileNotFoundError, ProcessLookupError):
            pass
    return rss * os.sysconf("SC_PAGE_SIZE") / 1024**2


def _metric_payload(root):
    sta = root / "sta_ecc"
    payload = {}
    for pattern in ("*/*/qor_summary.json", "*/*/power_summary.json"):
        for path in sorted((sta / "feature").glob(pattern)):
            payload[str(path.relative_to(sta))] = json.loads(path.read_text())
    if not payload:
        raise ValueError("STA corner artifacts are absent")
    for stage in ("sta_ecc", "Harden_ecc"):
        qor = json.loads((root / stage / "analysis/qor_metrics.json").read_text())
        payload[f"{stage}/metrics"] = {
            item["id"]: item["value"]
            for item in qor["metrics"]
            if item["id"] not in {"runtime_seconds", "peak_memory_mb"}
        }
        checklist = json.loads((root / stage / "checklist.json").read_text())
        payload[f"{stage}/gates"] = {item["id"]: item["state"] for item in checklist["checklist"]}
    metrics = payload["sta_ecc/metrics"]
    expected = metrics.get("sta_expected_corner_count", 0)
    qor_corners = {str(Path(key).parent) for key in payload if key.endswith("/qor_summary.json")}
    power_corners = {
        str(Path(key).parent) for key in payload if key.endswith("/power_summary.json")
    }
    if (
        type(expected) is not int
        or expected <= 0
        or metrics.get("sta_corner_count") != expected
        or metrics.get("sta_missing_corner_count") != 0
        or len(qor_corners) != expected
        or qor_corners != power_corners
    ):
        raise ValueError("STA timing/power corner coverage is incomplete")
    return payload


def _compare(reference, candidate, path=""):
    if isinstance(reference, dict) and isinstance(candidate, dict):
        if reference.keys() != candidate.keys():
            raise ValueError(f"metric keys differ at {path}")
        for key in reference:
            _compare(reference[key], candidate[key], f"{path}/{key}")
    elif isinstance(reference, list) and isinstance(candidate, list):
        if len(reference) != len(candidate):
            raise ValueError(f"metric list length differs at {path}")
        for index, (left, right) in enumerate(zip(reference, candidate, strict=True)):
            _compare(left, right, f"{path}/{index}")
    elif type(reference) is float and type(candidate) in (int, float):
        if not math.isclose(reference, candidate, rel_tol=1e-9, abs_tol=1e-9):
            raise ValueError(f"metric differs at {path}: {reference} != {candidate}")
    elif type(reference) is not type(candidate) or reference != candidate:
        raise ValueError(f"metric differs at {path}: {reference} != {candidate}")


def _run_workspace(root):
    from agent.engine import AgentEngineFlow
    from agent.workspace_api import _prepare_candidate_rerun
    from chipcompiler.data import StateEnum
    from chipcompiler.data.workspace import load_workspace

    workspace = load_workspace(root)
    flow = AgentEngineFlow(workspace)
    flow.create_step_workspaces(initialize_config=False, executable_steps={"sta", "Harden"})
    _prepare_candidate_rerun(
        workspace, flow, [flow.get_workspace_step(stage) for stage in ("sta", "Harden")]
    )
    if not flow.init_db_engine():
        raise RuntimeError("cannot initialize routed benchmark database")
    elapsed = {}
    for stage in ("sta", "Harden"):
        started = time.monotonic()
        state = flow.run_step(stage, rerun=True)
        elapsed[stage] = time.monotonic() - started
        if state != StateEnum.Success:
            raise RuntimeError(f"benchmark stage failed: {stage}: {state}")
    payload = _metric_payload(root)
    (root / "sta-benchmark-result.json").write_text(
        json.dumps({"elapsed_seconds": elapsed, "metrics": payload}, indent=2) + "\n"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--workers", type=int, nargs="+", default=[1, 2, 4], choices=[1, 2, 4])
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--workspace", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.workspace:
        _run_workspace(args.workspace)
        return
    if not args.source or not args.output or args.repeats < 1 or args.workers[0] != 1:
        parser.error(
            "source, new output, positive repeats and a serial-first schedule are required"
        )
    source, output = args.source.resolve(), args.output.resolve()
    if output == source or source in output.parents or output in source.parents:
        parser.error("output must be independent of the source workspace")
    before = _inventory(source)
    output.mkdir(parents=True, exist_ok=False)
    (output / "source-inventory.json").write_text(json.dumps(before, indent=2) + "\n")
    metadata = {
        "command": sys.argv,
        "python": sys.version,
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "packages": {name: importlib.metadata.version(name) for name in ("ecc", "ecc-tools-bin")},
        "implementation_sha256": {
            name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in ("sta_parallel.py", "sta_benchmark.py", "engine.py", "tools.py")
        },
    }
    (output / "environment.json").write_text(json.dumps(metadata, indent=2) + "\n")
    from agent.candidate_clone import candidate_clone_ignore

    results, reference = [], None
    try:
        for repeat in range(args.repeats):
            for workers in args.workers:
                name = f"r{repeat + 1}-w{workers}"
                root = output / ".agent/candidates" / name
                shutil.copytree(source, root, ignore=candidate_clone_ignore(source, "sta"))
                env = dict(os.environ, ECOS_AGENT_STA_WORKERS=str(workers))
                started, peak = time.monotonic(), 0.0
                with (output / f"{name}.log").open("w") as log:
                    process = subprocess.Popen(
                        [sys.executable, "-m", "agent.sta_benchmark", "--workspace", str(root)],
                        env=env,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                    )
                    try:
                        while process.poll() is None:
                            peak = max(peak, _tree_rss_mb(process.pid))
                            time.sleep(0.05)
                        if process.returncode:
                            raise RuntimeError(f"{name} failed; see {output / (name + '.log')}")
                    finally:
                        if process.poll() is None:
                            import signal

                            os.killpg(process.pid, signal.SIGKILL)
                            process.wait()
                result = json.loads((root / "sta-benchmark-result.json").read_text())
                if reference is None:
                    reference = result["metrics"]
                _compare(reference, result["metrics"])
                results.append(
                    {
                        "run": name,
                        "workers": workers,
                        "elapsed_seconds": result["elapsed_seconds"],
                        "driver_seconds": time.monotonic() - started,
                        "sampled_peak_tree_rss_mb": peak,
                        "metrics_match_serial": True,
                    }
                )
                print(json.dumps(results[-1]), flush=True)
                (output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    finally:
        unchanged = before == _inventory(source)
        (output / "source-unchanged.json").write_text(json.dumps({"unchanged": unchanged}) + "\n")
        if not unchanged:
            raise RuntimeError("source workspace changed during benchmark")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
