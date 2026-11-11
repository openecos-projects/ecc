"""Flow observers: notification, the run's engineering sink, and wave serialization.

Everything the engine does with the optional observer a caller passes to
``EngineFlow.run_steps`` / ``run_step`` lives here:

* ``notify_*`` publish step events without letting a non-fatal observer break
  the flow;
* ``ExecutionObserver`` wraps the caller's event sink and records which steps
  ran and which failed;
* ``_EngineeringCommitSink`` is the default sink (run-id marker, snapshot
  commit, cancellation);
* ``WaveObserver`` is what the sibling steps of a parallel analysis wave
  share: their callbacks run under the ledger lock, and an interrupt stops
  the running steps.
"""

import logging
import threading
from collections.abc import Callable
from copy import deepcopy
from typing import Any

from chipcompiler.data import ADVISORY_FLOW_STEPS, StateEnum
from chipcompiler.data.workspace.flow_ledger import ledger_lock
from chipcompiler.data.workspace.flow_types import FlowStepEntry

logger = logging.getLogger(__name__)


def notify_flow_observer(observer, method_name: str, *args) -> None:
    """Keep optional GUI observers outside the flow engine's failure domain."""
    if observer is None:
        return
    callback = getattr(observer, method_name, None)
    if not callable(callback):
        return
    try:
        callback(*args)
    except (Exception, SystemExit):
        if getattr(observer, "fatal_observer", False):
            raise
        logger.exception("flow observer callback failed: %s", method_name)


def raise_if_cancelled(observer) -> None:
    """Let the observer abort the run at a step boundary.

    Unlike ``notify_flow_observer`` the observer's error always propagates:
    swallowing a cancellation would keep running a flow the user stopped.
    """
    callback = getattr(observer, "raise_if_cancelled", None)
    if callable(callback):
        callback()


def notify_step_completed(
    flow,
    observer,
    workspace_step,
    state,
    error,
    previous_step: FlowStepEntry | None,
) -> None:
    """Publish completion and restore Ongoing state when a fatal commit fails.

    ``EngineFlow.run_step`` calls this inside the ledger transaction that
    persisted the terminal state, so no sibling step publishes a snapshot
    holding a state this rollback then withdraws.
    """
    try:
        notify_flow_observer(observer, "on_step_completed", workspace_step, state, error)
    except (Exception, SystemExit):
        if previous_step is not None:
            with ledger_lock(flow.workspace.flow):
                current = flow.get_step(workspace_step.name, workspace_step.tool)
                if current is not None:
                    current.clear()
                    current.update(deepcopy(previous_step))
                    if not flow.save():
                        raise RuntimeError(
                            "failed to roll back flow state after completion commit failure"
                        ) from None
        raise


def notify_subflow_stages(observer, workspace_step, subflow_steps: list[dict]) -> None:
    """Publish finalized subflow stages; a failure here never fails the step."""
    try:
        for subflow_step in subflow_steps:
            notify_flow_observer(observer, "on_subflow_stage", workspace_step, subflow_step)
    except (Exception, SystemExit):
        logger.exception("Failed to publish the subflow of %s", workspace_step.name)


class ExecutionObserver:
    def __init__(self, delegate: Any):
        self.delegate = delegate
        self.fatal_observer = bool(getattr(delegate, "fatal_observer", False))
        self.executed_steps: list[str] = []
        #: Blocking failures in completion order; steps of a parallel wave
        #: complete in any order, so ``execute`` reports them in flow order.
        self.failed_steps: list[str] = []

    @property
    def failed_step(self) -> str | None:
        return self.failed_steps[0] if self.failed_steps else None

    def on_step_completed(self, step: Any, state: Any, error: str | None = None) -> None:
        name = getattr(step, "name", None)
        if isinstance(name, str) and name:
            if getattr(state, "value", state) == StateEnum.Success.value:
                self.executed_steps.append(name)
            elif not (
                name in ADVISORY_FLOW_STEPS
                and getattr(state, "value", state) == StateEnum.Imcomplete.value
            ):
                self.failed_steps.append(name)
        self._delegate_call("on_step_completed", step, state, error)

    @property
    def runtime_operation(self):
        return getattr(self.delegate, "runtime_operation", None)

    @property
    def execution(self):
        return getattr(self.delegate, "execution", None)

    def raise_if_cancelled(self) -> None:
        self._delegate_call("raise_if_cancelled")

    def on_step_started(self, step: Any) -> None:
        self._delegate_call("on_step_started", step)

    def on_step_skipped(self, step: Any) -> None:
        self._delegate_call("on_step_skipped", step)

    def on_subflow_stage(self, step: Any, subflow_step: Any) -> None:
        self._delegate_call("on_subflow_stage", step, subflow_step)

    def on_step_diagnostic(self, step: Any, diagnostic: dict[str, Any]) -> None:
        self._delegate_call("on_step_diagnostic", step, diagnostic)

    def on_rerun_prepared(self, *args, **kwargs) -> None:
        self._delegate_call("on_rerun_prepared", *args, **kwargs)

    def wait_for_step_rendered(self, step: Any, state: Any) -> bool:
        result = self._delegate_call("wait_for_step_rendered", step, state)
        return True if result is None else bool(result)

    def _delegate_call(self, name: str, *args, **kwargs):
        callback = getattr(self.delegate, name, None)
        if callable(callback):
            return callback(*args, **kwargs)
        return None


class _EngineeringCommitSink:
    fatal_observer = True

    def __init__(self, workspace: Any):
        from chipcompiler.engine.snapshot import ensure_engineering_snapshot

        self.workspace = workspace
        self.snapshot = ensure_engineering_snapshot(workspace)

    def on_step_completed(self, _step: Any, state: Any, _error: str | None = None) -> None:
        from chipcompiler.engine.snapshot import commit_engineering_snapshot

        # The snapshot projects the ledger: build and publish it from one
        # consistent ledger view, never beside a sibling step's ledger write.
        with ledger_lock(self.workspace.flow):
            self.snapshot = commit_engineering_snapshot(
                self.workspace,
                workspace_id=self.snapshot["workspaceId"],
                cause=f"flow_step.{getattr(state, 'value', str(state)).lower()}",
            )

    @property
    def execution(self) -> dict[str, Any] | None:
        run_id = getattr(self.workspace, "_ecc_run_id", None)
        if isinstance(run_id, str) and run_id:
            return {"schema_version": 1, "run_id": run_id}
        return None

    def raise_if_cancelled(self) -> None:
        event = getattr(self.workspace, "_ecc_cancel_event", None)
        if event is not None and event.is_set():
            raise RuntimeError("run cancelled at a step boundary")


def event_sink_for_workspace(workspace: Any) -> _EngineeringCommitSink | None:
    if getattr(workspace, "directory", None):
        return _EngineeringCommitSink(workspace)
    return None


def execution_observer(event_sink: Any) -> ExecutionObserver:
    return ExecutionObserver(event_sink)


class WaveObserver:
    """The observer the steps of a parallel analysis wave share.

    Sibling steps call it from their threads (step started/completed/skipped,
    subflow stages, cancellation polls). Every callable attribute runs under
    the ledger lock: the lock ``EngineFlow.run_step`` holds for each ledger
    transaction, including the one that persists a step's terminal state,
    publishes its completion (the snapshot commit) and rolls the state back
    when that commit fails. A callback therefore never overlaps another one or
    a sibling's ledger transaction, and there is no second lock whose order
    could invert against it. Non-callable attributes (``execution``,
    ``runtime_operation``, ``fatal_observer``, ...) and missing ones are
    forwarded unchanged, so ``getattr(observer, name, default)`` probes behave
    as on the wrapped observer, which may be None.

    ``interrupt()`` makes ``raise_if_cancelled`` raise ``KeyboardInterrupt``.
    Running steps poll it while their worker runs, so Ctrl-C stops every step
    of the wave the way it stops a step running on the main thread: the worker
    is terminated and the step stays Ongoing, which the next ``ecc run``
    resumes.
    """

    def __init__(self, observer: Any, ledger: Any):
        self._observer = observer
        self._ledger = ledger
        self._interrupted = threading.Event()

    def interrupt(self) -> None:
        self._interrupted.set()

    def raise_if_cancelled(self) -> None:
        if self._interrupted.is_set():
            raise KeyboardInterrupt
        callback = getattr(self._observer, "raise_if_cancelled", None)
        if callable(callback):
            self._locked(callback)()

    def __getattr__(self, name: str) -> Any:
        value = getattr(self._observer, name)
        if not callable(value):
            return value
        return self._locked(value)

    def _locked(self, callback: Callable[..., Any]) -> Callable[..., Any]:
        def call(*args: Any, **kwargs: Any) -> Any:
            with ledger_lock(self._ledger):
                return callback(*args, **kwargs)

        return call
