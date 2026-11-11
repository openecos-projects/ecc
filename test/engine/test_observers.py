"""The observer the steps of a parallel analysis wave share, and the run's commit sink."""

import threading
from types import SimpleNamespace

import pytest

from chipcompiler.data.workspace import Flow
from chipcompiler.data.workspace.flow_ledger import ledger_lock
from chipcompiler.engine import snapshot
from chipcompiler.engine.observers import WaveObserver, _EngineeringCommitSink


class _OverlapProbe:
    """An observer whose callbacks record when two of them run at once."""

    fatal_observer = True
    execution = {"schema_version": 1, "run_id": "run-1"}

    def __init__(self):
        self._guard = threading.Lock()
        self._second_entered = threading.Event()
        self._inside = 0
        self.overlapped = False

    def on_step_started(self, step):
        with self._guard:
            self._inside += 1
            if self._inside > 1:
                self.overlapped = True
                self._second_entered.set()
        # Give a sibling thread the chance to enter while this one is inside.
        self._second_entered.wait(timeout=0.2)
        with self._guard:
            self._inside -= 1
        return step.name


def _ledger(tmp_path) -> Flow:
    return Flow(path=tmp_path / "home" / "flow.json")


def _held_by_caller(ledger: Flow) -> bool:
    """Whether the calling thread holds the ledger lock: another thread cannot take it."""
    taken = threading.Event()

    def take():
        with ledger_lock(ledger):
            taken.set()

    threading.Thread(target=take, daemon=True).start()
    return not taken.wait(timeout=0.2)


def test_forwards_plain_attributes_and_missing_names_unchanged(tmp_path):
    wrapped = SimpleNamespace(
        execution={"schema_version": 1, "run_id": "run-1"},
        runtime_operation=None,
        fatal_observer=True,
    )
    proxy = WaveObserver(wrapped, _ledger(tmp_path))

    assert (
        proxy.execution,
        proxy.runtime_operation,
        proxy.fatal_observer,
        getattr(proxy, "on_step_skipped", "absent"),
        getattr(WaveObserver(None, _ledger(tmp_path)), "execution", "absent"),
    ) == ({"schema_version": 1, "run_id": "run-1"}, None, True, "absent", "absent")


def test_callbacks_return_values_and_exceptions_pass_through(tmp_path):
    def failing(_step):
        raise RuntimeError("cancelled")

    proxy = WaveObserver(
        SimpleNamespace(wait_for_step_rendered=lambda step, state: (step, state), boom=failing),
        _ledger(tmp_path),
    )

    assert proxy.wait_for_step_rendered("drc", "Success") == ("drc", "Success")
    with pytest.raises(RuntimeError, match="cancelled"):
        proxy.boom("drc")
    # a failed callback releases the lock for its siblings
    assert proxy.wait_for_step_rendered("lvs", "Success") == ("lvs", "Success")


def test_sibling_threads_never_run_callbacks_at_once(tmp_path):
    probe = _OverlapProbe()
    proxy = WaveObserver(probe, _ledger(tmp_path))
    threads = [
        threading.Thread(target=proxy.on_step_started, args=(SimpleNamespace(name=name),))
        for name in ("lvs", "drc")
    ]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert probe.overlapped is False


def test_callbacks_run_under_the_ledger_lock(tmp_path):
    ledger = _ledger(tmp_path)
    held = []
    proxy = WaveObserver(
        SimpleNamespace(on_step_started=lambda _step: held.append(_held_by_caller(ledger))),
        ledger,
    )

    proxy.on_step_started(SimpleNamespace(name="drc"))

    assert held == [True]


def test_an_interrupt_makes_every_cancellation_poll_raise(tmp_path):
    polls = []
    proxy = WaveObserver(
        SimpleNamespace(raise_if_cancelled=lambda: polls.append("polled")), _ledger(tmp_path)
    )

    proxy.raise_if_cancelled()
    proxy.interrupt()
    with pytest.raises(KeyboardInterrupt):
        proxy.raise_if_cancelled()

    assert polls == ["polled"]


def test_the_snapshot_commit_holds_the_ledger_lock(tmp_path, monkeypatch):
    ledger = _ledger(tmp_path)
    workspace = SimpleNamespace(flow=ledger)
    held = []

    def commit(_workspace, *, workspace_id, cause):
        held.append(_held_by_caller(ledger))
        return {"workspaceId": workspace_id}

    monkeypatch.setattr(snapshot, "ensure_engineering_snapshot", lambda _w: {"workspaceId": "w"})
    monkeypatch.setattr(snapshot, "commit_engineering_snapshot", commit)

    _EngineeringCommitSink(workspace).on_step_completed(SimpleNamespace(name="drc"), "Success")

    assert held == [True]
