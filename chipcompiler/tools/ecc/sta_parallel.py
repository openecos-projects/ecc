"""Full-corner STA with isolated native processes.

Parallel STA applies to every workspace's `sta` step. The generated STA
configuration supplies the upper bound; memory headroom limits dispatch.
"""

import json
import multiprocessing
import os
import shutil
import signal
import sys
import time
from contextlib import suppress
from pathlib import Path
from tempfile import TemporaryDirectory

from chipcompiler.data import is_sta_step
from chipcompiler.engine.step_execution import get_process_rss_mb
from chipcompiler.tools.ecc import runner
from chipcompiler.tools.ecc.module import ECCToolsModule
from chipcompiler.tools.ecc.sta_artifacts import copy_sta_artifact, discard_sta_outputs
from chipcompiler.tools.ecc.sta_qor import sta_artifact_directory
from chipcompiler.utility.log import redirect_stdio_to_file


def sta_workers(workspace, step) -> int:
    if not is_sta_step(step):
        return 1
    path = workspace.config.get("sta")
    if not path:
        return 1
    with open(path, encoding="utf-8") as stream:
        value = json.load(stream).get("max_parallel_corners", 1)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 4:
        raise ValueError("STA max_parallel_corners must be an integer between 1 and 4")
    if sys.platform != "linux":
        return 1
    cpu_count = os.cpu_count() or 1
    if hasattr(os, "sched_getaffinity"):
        with suppress(OSError):
            cpu_count = min(cpu_count, len(os.sched_getaffinity(0)) or 1)
    return min(value, cpu_count)


def _memory_headroom_mb():
    try:
        fields = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
        available = int(fields["MemAvailable"].split()[0]) / 1024
        total = int(fields["MemTotal"].split()[0]) / 1024
        for line in Path("/proc/self/cgroup").read_text().splitlines():
            if "memory" in line.split(":", 2)[1].split(","):
                return 0
            if not line.startswith("0::"):
                continue
            root = Path("/sys/fs/cgroup")
            relative = line.split("::", 1)[1].lstrip("/")
            if ".." in relative.split("/"):
                return 0
            directory = root / relative
            while directory == root or root in directory.parents:
                limit_path = directory / "memory.max"
                if limit_path.is_file():
                    limit = limit_path.read_text().strip()
                    if limit != "max":
                        capacity = int(limit) / 1024**2
                        used = int((directory / "memory.current").read_text()) / 1024**2
                        total = min(total, capacity)
                        available = min(available, capacity - used)
                directory = directory.parent
        return max(0, available - max(1024, total * 0.1))
    except (OSError, ValueError, KeyError, IndexError):
        return 0


def _arm_parent_death_signal(parent_pid=None):
    import ctypes

    # A caller can be killed without running its Python cleanup.
    if parent_pid is None:
        parent_pid = multiprocessing.parent_process().pid
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    if os.getppid() != parent_pid:
        os.kill(os.getpid(), signal.SIGKILL)


def _run_corner(db_config, snapshot, job, log_path):
    _arm_parent_death_signal()
    redirect_stdio_to_file(str(log_path))
    module = ECCToolsModule()
    try:
        module.init_config(db_config, job["work_dir"], job["feature_dir"])
        if not module.load_data(snapshot):
            raise RuntimeError("STA worker failed to load candidate database snapshot")
        module.run_timing(**job)
    finally:
        module.close()


def get_sta_process_rss_mb(pid):
    pending = [pid]
    seen = set()
    rss = 0.0
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        rss += get_process_rss_mb(current)
        for path in Path(f"/proc/{current}/task").glob("*/children"):
            with suppress(OSError, ValueError):
                pending.extend(int(value) for value in path.read_text().split())
    return rss


def track_sta_process_memory(pid, stop_event, peak_memory):
    while True:
        peak_memory[0] = max(peak_memory[0], get_sta_process_rss_mb(pid))
        if stop_event.wait(0.1):
            return


def _check_cancelled(workspace):
    observer = getattr(workspace, "_runtime_flow_observer", None)
    callback = getattr(observer, "raise_if_cancelled", None)
    if callable(callback):
        callback()
    event = getattr(workspace, "_ecc_cancel_event", None)
    if event is not None and event.is_set():
        raise RuntimeError("STA cancelled")


def _run_processes(jobs, workers, check_cancelled):
    context = multiprocessing.get_context("spawn")
    active = []
    pending = iter(jobs)
    exhausted = False
    estimated_memory = max(1024, get_process_rss_mb(os.getpid()) * 2)
    try:
        while active or not exhausted:
            check_cancelled()
            if active:
                estimated_memory = max(
                    estimated_memory,
                    *(get_process_rss_mb(process.pid) * 1.5 for process, _ in active),
                )
            while len(active) < workers and not exhausted:
                if active:
                    pending_memory = sum(
                        max(0, estimated_memory - get_process_rss_mb(process.pid))
                        for process, _ in active
                    )
                    if _memory_headroom_mb() < estimated_memory + pending_memory:
                        break
                args = next(pending, None)
                if args is None:
                    exhausted = True
                    break
                process = context.Process(target=_run_corner, args=args)
                process.start()
                active.append((process, args[-1]))
            for process, log_path in active[:]:
                if process.exitcode is None:
                    continue
                process.join()
                active.remove((process, log_path))
                exitcode = process.exitcode
                process.close()
                if exitcode != 0:
                    raise RuntimeError(f"STA corner worker exited with {exitcode}; log: {log_path}")
            if active:
                time.sleep(0.05)
        check_cancelled()
    finally:
        for process, _log_path in active:
            if process.is_alive():
                process.terminate()
        for process, _log_path in active:
            process.join(timeout=5)
            if process.is_alive():
                process.kill()
                process.join()
            process.close()


class _ParallelTiming:
    def __init__(self, module, workspace, step, workers, count, root):
        self.module = module
        self.workspace = workspace
        self.step = step
        self.workers = workers
        self.count = count
        self.root = root
        self.jobs = []

    def __getattr__(self, name):
        return getattr(self.module, name)

    def run_timing(self, **job):
        # The last call is the barrier: generic run_sta cannot mark success early.
        self.jobs.append(job)
        if len(self.jobs) != self.count:
            return
        snapshot = self.root / "snapshot"
        self.module.save_data(snapshot)
        if not self.module.is_db_data_exists(snapshot):
            raise RuntimeError("STA candidate database snapshot is incomplete")
        tasks = []
        for index, original in enumerate(self.jobs):
            root = self.root / str(index)
            job = dict(
                original,
                work_dir=root / "work",
                report_dir=root / "report",
                feature_dir=root / "feature",
            )
            for key in ("work_dir", "report_dir", "feature_dir"):
                job[key].mkdir(parents=True)
            log_path = Path(self.step.log.dir) / f"sta-corner-{index}.log"
            tasks.append((self.workspace.config.get("db", ""), snapshot, job, log_path))
        _run_processes(tasks, self.workers, lambda: _check_cancelled(self.workspace))
        for original, (_, _, job, _) in zip(self.jobs, tasks, strict=True):
            for key in ("report_dir", "feature_dir"):
                for artifact in job[key].iterdir():
                    if artifact.is_file():
                        copy_sta_artifact(artifact, Path(original[key]))


def run_parallel_sta(workspace, step, ecc_module, workers):
    items = runner.collect_sta_signoff_items(workspace)
    destinations = []
    for item in items:
        for root in (step.report.dir, step.feature.dir):
            path = sta_artifact_directory(
                root or "", item["corner"], item["temperature"], item["rcx_corner"]
            )
            if path is not None:
                destinations.append(path)
                discard_sta_outputs(path)
    # A failed rerun must not expose old aggregate metrics as current evidence.
    analysis = Path(step.analysis.dir)
    if analysis.is_dir():
        for path in analysis.iterdir():
            if path.is_file():
                path.unlink()
    succeeded = False
    try:
        module = runner.get_eda_instance(workspace, step, ecc_module)
        if module is None:
            return False
        with TemporaryDirectory(prefix="agent-sta-", dir=step.data.dir) as directory:
            proxy = _ParallelTiming(module, workspace, step, workers, len(items), Path(directory))
            succeeded = runner.run_sta(workspace, step, proxy)
            return succeeded
    finally:
        if not succeeded:
            for path in destinations:
                discard_sta_outputs(path)
            if analysis.is_dir():
                shutil.rmtree(analysis)
