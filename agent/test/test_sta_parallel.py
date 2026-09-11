import multiprocessing
import os
import signal
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent import sta_parallel as sta


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


def test_worker_setting_is_candidate_sta_only(tmp_path, monkeypatch):
    monkeypatch.setattr(sta.sys, "platform", "linux")
    workspace = _workspace(tmp_path)
    step = SimpleNamespace(tool="ecc", name="sta")
    assert sta.sta_workers(workspace, step) == 2
    for value in ("1", "2", "4"):
        monkeypatch.setenv("ECOS_AGENT_STA_WORKERS", value)
        assert sta.sta_workers(workspace, step) == int(value)
    monkeypatch.setenv("ECOS_AGENT_STA_WORKERS", "13")
    with pytest.raises(ValueError, match="1, 2, or 4"):
        sta.sta_workers(workspace, step)
    step.name = "Harden"
    assert sta.sta_workers(workspace, step) == 1


def test_non_linux_candidates_keep_serial_default(tmp_path, monkeypatch):
    monkeypatch.setattr(sta.sys, "platform", "darwin")
    monkeypatch.delenv("ECOS_AGENT_STA_WORKERS", raising=False)
    workspace = _workspace(tmp_path)
    step = SimpleNamespace(tool="ecc", name="sta")
    assert sta.sta_workers(workspace, step) == 1
    monkeypatch.setenv("ECOS_AGENT_STA_WORKERS", "2")
    with pytest.raises(ValueError, match="requires Linux"):
        sta.sta_workers(workspace, step)
    step.name = "sta"
    workspace.directory = tmp_path / "ordinary"
    assert sta.sta_workers(workspace, step) == 1


@pytest.mark.parametrize("fail", [False, True])
def test_full_corner_barrier_isolates_jobs_and_publishes_only_after_success(
    tmp_path, monkeypatch, fail
):
    workspace = _workspace(tmp_path)
    step = SimpleNamespace(log=SimpleNamespace(dir=tmp_path / "log"))
    module = SimpleNamespace(save_data=lambda _: None, is_db_data_exists=lambda _: True)
    proxy = sta._ParallelTiming(module, workspace, step, 2, 13, tmp_path / "temporary")
    originals = [
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
    step = SimpleNamespace(
        report=SimpleNamespace(dir=tmp_path / "report"),
        feature=SimpleNamespace(dir=tmp_path / "feature"),
        analysis=SimpleNamespace(dir=tmp_path / "analysis"),
        data=SimpleNamespace(dir=tmp_path),
    )
    item = dict(corner="MAX", temperature=125, rcx_corner="rcworst")
    for root in (step.report.dir, step.feature.dir):
        directory = sta.sta_artifact_directory(root, "MAX", 125, "rcworst")
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
    manager = SimpleNamespace(operation_status=lambda _: {"cancelRequested": True})
    observer = sta.RuntimeFlowObserver(manager, "operation")
    workspace = SimpleNamespace(_runtime_flow_observer=observer)
    with pytest.raises(sta.RuntimeOperationCancelled):
        sta._check_cancelled(workspace)


def test_spawn_cancellation_reaps_all_workers(tmp_path, monkeypatch):
    original_children = {child.pid for child in multiprocessing.active_children()}
    monkeypatch.setattr(sta, "_run_corner", _slow_worker)
    tasks = [(None, None, None, tmp_path / f"{index}.log") for index in range(4)]
    started = time.monotonic()

    def cancel():
        if len(list(tmp_path.glob("*.log"))) == 2:
            raise sta.RuntimeOperationCancelled("cancelled")
        assert time.monotonic() - started < 20

    with pytest.raises(sta.RuntimeOperationCancelled):
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
