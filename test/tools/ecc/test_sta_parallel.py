import json
import multiprocessing
import os
import signal
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from chipcompiler.tools.ecc import sta_parallel as sta


def _guarded_worker(connection, stale_parent):
    import ctypes

    if stale_parent:
        sta.multiprocessing.parent_process = lambda: SimpleNamespace(pid=-1)
    sta._arm_parent_death_signal()
    value = ctypes.c_int()
    assert ctypes.CDLL(None).prctl(2, ctypes.byref(value), 0, 0, 0) == 0
    connection.send(value.value)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux parent-death signal")
@pytest.mark.parametrize("stale_parent", [False, True])
def test_worker_arms_parent_death_signal_and_closes_startup_race(stale_parent):
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_guarded_worker, args=(sender, stale_parent))
    try:
        process.start()
        process.join(timeout=15)
        assert process.exitcode == (-signal.SIGKILL if stale_parent else 0)
        if not stale_parent:
            assert receiver.poll(1)
            assert receiver.recv() == signal.SIGKILL
    finally:
        if process.is_alive():
            assert process.pid is not None
            assert process.pid is not None
            os.kill(process.pid, signal.SIGKILL)
            process.join()
        process.close()
        receiver.close()
        sender.close()


def _guarded_slow_worker(connection):
    sta._arm_parent_death_signal()
    connection.send(os.getpid())
    time.sleep(30)


def _guarded_parent(connection):
    sta._arm_parent_death_signal()
    worker = multiprocessing.get_context("spawn").Process(
        target=_guarded_slow_worker, args=(connection,)
    )
    worker.start()
    worker.join()


def _parent_death_supervisor(connection, death_signal):
    import ctypes

    # Adopt and reap the orphan in this isolated process, not in the test runner.
    assert ctypes.CDLL(None).prctl(36, 1, 0, 0, 0) == 0  # PR_SET_CHILD_SUBREAPER
    receiver, sender = multiprocessing.get_context("spawn").Pipe(duplex=False)
    parent = multiprocessing.get_context("spawn").Process(target=_guarded_parent, args=(sender,))
    parent.start()
    worker_pid = None
    reaped = False
    try:
        assert receiver.poll(15)
        worker_pid = receiver.recv()
        assert parent.pid is not None
        os.kill(parent.pid, death_signal)
        parent.join(timeout=5)
        assert parent.exitcode == -death_signal
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            pid, status = os.waitpid(worker_pid, os.WNOHANG)
            if pid:
                reaped = True
                connection.send(os.waitstatus_to_exitcode(status))
                return
            time.sleep(0.05)
        raise AssertionError("STA worker survived parent termination")
    finally:
        if parent.is_alive():
            parent.kill()
            parent.join()
        if worker_pid is not None and not reaped:
            os.kill(worker_pid, signal.SIGKILL)
            os.waitpid(worker_pid, 0)
        parent.close()
        receiver.close()
        sender.close()


@pytest.mark.skipif(sys.platform != "linux", reason="Linux parent-death signal")
@pytest.mark.parametrize("death_signal", [signal.SIGTERM, signal.SIGKILL])
def test_terminating_rpc_parent_kills_corner_worker(death_signal):
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    supervisor = context.Process(target=_parent_death_supervisor, args=(sender, death_signal))
    try:
        supervisor.start()
        supervisor.join(timeout=25)
        assert supervisor.exitcode == 0
        assert receiver.poll(1)
        assert receiver.recv() == -signal.SIGKILL
    finally:
        if supervisor.is_alive():
            supervisor.kill()
            supervisor.join()
        supervisor.close()
        receiver.close()
        sender.close()


def _workspace(tmp_path):
    return SimpleNamespace(
        directory=tmp_path / ".agent" / "candidates" / "one", config={"db": "db.json"}
    )


def test_worker_setting_applies_to_every_workspace_sta_step(tmp_path, monkeypatch):
    monkeypatch.setattr(sta.sys, "platform", "linux")
    monkeypatch.setattr(sta.os, "cpu_count", lambda: 8)
    workspace = _workspace(tmp_path)
    config_path = tmp_path / "sta.json"
    workspace.config["sta"] = config_path
    config_path.write_text("{}")
    step: Any = SimpleNamespace(tool="ecc", name="sta")
    assert sta.sta_workers(workspace, step) == 1
    monkeypatch.setenv("ECOS_AGENT_STA_WORKERS", "4")
    for value in (1, 2, 3, 4):
        config_path.write_text(json.dumps({"max_parallel_corners": value}))
        assert sta.sta_workers(workspace, step) == value
    for value in (0, 5, True, 2.5, "2"):
        config_path.write_text(json.dumps({"max_parallel_corners": value}))
        with pytest.raises(ValueError, match="between 1 and 4"):
            sta.sta_workers(workspace, step)
    step.name = "Harden"
    assert sta.sta_workers(workspace, step) == 1


def test_non_linux_keeps_serial_default(tmp_path, monkeypatch):
    monkeypatch.setattr(sta.sys, "platform", "darwin")
    workspace = _workspace(tmp_path)
    config_path = tmp_path / "sta.json"
    config_path.write_text('{"max_parallel_corners": 4}')
    workspace.config["sta"] = config_path
    step: Any = SimpleNamespace(tool="ecc", name="sta")
    assert sta.sta_workers(workspace, step) == 1


@pytest.mark.skipif(not hasattr(os, "sched_getaffinity"), reason="CPU affinity unavailable")
def test_cpu_affinity_limits_corner_concurrency(tmp_path, monkeypatch):
    config_path = tmp_path / "sta.json"
    config_path.write_text('{"max_parallel_corners": 4}')
    workspace: Any = SimpleNamespace(config={"sta": config_path})
    monkeypatch.setattr(sta.sys, "platform", "linux")
    monkeypatch.setattr(sta.os, "sched_getaffinity", lambda _: {0})
    assert sta.sta_workers(workspace, SimpleNamespace(tool="ecc", name="sta")) == 1


@pytest.mark.parametrize("workers", [1, 2, 3, 4])
def test_cli_tool_dispatch_uses_the_sta_config(tmp_path, monkeypatch, workers):
    config_path = tmp_path / "sta.json"
    config_path.write_text(json.dumps({"max_parallel_corners": workers}))
    workspace: Any = SimpleNamespace(config={"sta": config_path})
    step: Any = SimpleNamespace(name="sta", tool="ecc")
    monkeypatch.setattr(sta.sys, "platform", "linux")
    monkeypatch.setattr(sta.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(sta.runner, "is_eda_exist", lambda: True)
    calls = []
    monkeypatch.setattr(sta.runner, "run_sta", lambda **_: calls.append(1) or True)
    monkeypatch.setattr(sta, "run_parallel_sta", lambda *args: calls.append(args[-1]) or True)
    assert sta.runner.run_step(workspace, step) is True
    assert calls == [workers]


@pytest.mark.parametrize("fail", [False, True])
def test_full_corner_barrier_isolates_jobs_and_publishes_only_after_success(
    tmp_path, monkeypatch, fail
):
    workspace = _workspace(tmp_path)
    step: Any = SimpleNamespace(log=SimpleNamespace(dir=tmp_path / "log"))
    module = SimpleNamespace(save_data=lambda _: None, is_db_data_exists=lambda _: True)
    proxy = sta._ParallelTiming(module, workspace, step, 2, 13, tmp_path / "temporary")
    originals: list[dict[str, Any]] = [
        dict(
            work_dir=tmp_path / "shared",
            report_dir=tmp_path / "report" / str(index),
            feature_dir=tmp_path / "feature" / str(index),
            corner=str(index),
            lib_paths=["lib"],
            spef_path="spef",
            sdc_path="sdc",
            config="sta.json",
        )
        for index in range(13)
    ]
    calls = []

    def run(jobs, workers, check):
        calls.append(jobs)
        assert workers == 2
        assert len(jobs) == 13
        assert len({job[2]["work_dir"] for job in jobs}) == 13
        for original, (_, _, job, _) in zip(originals, jobs, strict=True):
            assert job["corner"] == original["corner"]
            assert job["lib_paths"] == original["lib_paths"]
            assert not original["report_dir"].exists()
            for key in ("report_dir", "feature_dir"):
                (job[key] / "result.json").write_text(job["corner"])
        if fail:
            raise RuntimeError("corner failed")
        check()

    monkeypatch.setattr(sta, "_run_processes", run)
    for job in originals[:-1]:
        proxy.run_timing(**job)
    assert not calls
    if fail:
        with pytest.raises(RuntimeError, match="corner failed"):
            proxy.run_timing(**originals[-1])
        assert not (tmp_path / "report").exists()
    else:
        proxy.run_timing(**originals[-1])
        for job in originals:
            assert (job["feature_dir"] / "result.json").read_text() == job["corner"]
    assert len(calls) == 1


def test_failed_validation_clears_stale_corner_and_aggregate(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    step: Any = SimpleNamespace(
        report=SimpleNamespace(dir=tmp_path / "report"),
        feature=SimpleNamespace(dir=tmp_path / "feature"),
        analysis=SimpleNamespace(dir=tmp_path / "analysis"),
        data=SimpleNamespace(dir=tmp_path),
    )
    item = dict(corner="MAX", temperature=125, rcx_corner="rcworst")
    for root in (step.report.dir, step.feature.dir):
        directory = sta.sta_artifact_directory(root, "MAX", 125, "rcworst")
        assert directory is not None
        directory.mkdir(parents=True)
        (directory / "qor_summary.json").write_text("old")
    step.analysis.dir.mkdir()
    (step.analysis.dir / "qor_metrics.json").write_text("old")
    monkeypatch.setattr(sta.runner, "collect_sta_signoff_items", lambda _: [item])
    monkeypatch.setattr(sta.runner, "get_eda_instance", lambda *_: object())
    monkeypatch.setattr(sta.runner, "run_sta", lambda *_: False)
    assert sta.run_parallel_sta(workspace, step, None, 2) is False
    assert not list(tmp_path.rglob("*.json"))
    assert not list(tmp_path.glob("agent-sta-*"))


def _slow_worker(_db, _snapshot, _job, log_path):
    Path(log_path).write_text("started")
    time.sleep(30)


def _short_worker(_db, _snapshot, _job, log_path):
    Path(log_path).write_text("started")
    time.sleep(0.1)


@pytest.mark.parametrize("headroom, expected", [(0, 1), (2048, 2), (100000, 3)])
def test_memory_headroom_limits_dispatch(tmp_path, monkeypatch, headroom, expected):
    monkeypatch.setattr(sta, "_run_corner", _short_worker)
    monkeypatch.setattr(sta, "_memory_headroom_mb", lambda: headroom)
    monkeypatch.setattr(sta, "get_process_rss_mb", lambda _: 0)
    maximum = 0

    def check():
        nonlocal maximum
        maximum = max(maximum, len(multiprocessing.active_children()))

    tasks = [(None, None, None, tmp_path / f"{index}.log") for index in range(5)]
    sta._run_processes(tasks, 3, check)
    assert maximum == expected
    assert len(list(tmp_path.glob("*.log"))) == 5


def test_memory_reserves_host_and_cgroup_headroom(tmp_path, monkeypatch):
    def mapped_path(value):
        return tmp_path / value.lstrip("/")

    files = {
        "/proc/meminfo": "MemTotal: 33554432 kB\nMemAvailable: 16777216 kB\n",
        "/proc/self/cgroup": "0::/test/child\n",
        "/sys/fs/cgroup/test/memory.max": str(4096 * 1024**2),
        "/sys/fs/cgroup/test/memory.current": str(2048 * 1024**2),
    }
    for name, content in files.items():
        path = mapped_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    monkeypatch.setattr(sta, "Path", mapped_path)
    assert sta._memory_headroom_mb() == 1024
    mapped_path("/proc/self/cgroup").write_text("5:memory:/test\n")
    assert sta._memory_headroom_mb() == 0
    mapped_path("/proc/meminfo").unlink()
    assert sta._memory_headroom_mb() == 0


def _failed_worker(_db, _snapshot, _job, log_path):
    if Path(log_path).stem == "0":
        raise SystemExit(7)
    time.sleep(30)


def test_worker_crash_reaps_remaining_processes(tmp_path, monkeypatch):
    original_children = {child.pid for child in multiprocessing.active_children()}
    monkeypatch.setattr(sta, "_run_corner", _failed_worker)
    tasks = [(None, None, None, tmp_path / f"{index}.log") for index in range(4)]
    with pytest.raises(RuntimeError, match="exited with 7"):
        sta._run_processes(tasks, 2, lambda: None)
    assert {child.pid for child in multiprocessing.active_children()} == original_children


def test_runtime_observer_cancellation_is_checked():
    def cancel():
        raise RuntimeError("cancelled")

    observer = SimpleNamespace(raise_if_cancelled=cancel)
    workspace: Any = SimpleNamespace(_runtime_flow_observer=observer)
    with pytest.raises(RuntimeError, match="cancelled"):
        sta._check_cancelled(workspace)


def test_spawn_cancellation_reaps_all_workers(tmp_path, monkeypatch):
    original_children = {child.pid for child in multiprocessing.active_children()}
    monkeypatch.setattr(sta, "_run_corner", _slow_worker)
    # Test cancellation independently of host memory; throttling has its own test.
    monkeypatch.setattr(sta, "_memory_headroom_mb", lambda: 2048)
    monkeypatch.setattr(sta, "get_process_rss_mb", lambda _: 0)
    tasks = [(None, None, None, tmp_path / f"{index}.log") for index in range(4)]
    started = time.monotonic()

    def cancel():
        if len(list(tmp_path.glob("*.log"))) == 2:
            raise RuntimeError("cancelled")
        assert time.monotonic() - started < 20

    with pytest.raises(RuntimeError, match="cancelled"):
        sta._run_processes(tasks, 2, cancel)
    assert len(list(tmp_path.glob("*.log"))) == 2
    assert {child.pid for child in multiprocessing.active_children()} == original_children


def test_memory_counts_simultaneous_descendant_rss_once(tmp_path, monkeypatch):
    for pid, children in ((1, "2 3"), (2, "3"), (3, "")):
        path = tmp_path / str(pid) / "task" / str(pid) / "children"
        path.parent.mkdir(parents=True)
        path.write_text(children)
    monkeypatch.setattr(sta, "Path", lambda value: tmp_path / value.removeprefix("/proc/"))
    monkeypatch.setattr(sta, "get_process_rss_mb", lambda pid: {1: 10, 2: 20, 3: 30}[pid])
    peak = [0]
    sta.track_sta_process_memory(1, SimpleNamespace(wait=lambda _: True), peak)
    assert peak == [60]
