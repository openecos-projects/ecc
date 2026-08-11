import json
import os
import signal
import subprocess
from collections import deque
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from chipcompiler.runtime.transport import (
    ContentLengthDecoder,
    TransportError,
    encode_content_length_frame,
)
from chipcompiler.utility.json import json_read, json_write


@dataclass(frozen=True)
class WorkerResult:
    success: bool
    response: dict | None = None
    exit_code: int | None = None
    signal_number: int | None = None
    error: str | None = None


class WorkerProcessError(Exception):
    pass


_GRACEFUL_WAIT = 2.0
_FORCEFUL_WAIT = 3.0


class WorkerClient:
    """Manages a worker subprocess running `ecc rpc serve --stdio`."""

    def __init__(self, worker_argv: list[str]):
        self._argv = worker_argv
        self._process: subprocess.Popen | None = None
        self._pgid: int | None = None
        self._decoder = ContentLengthDecoder()
        self._notifications: deque[dict] = deque()

    def start(self) -> subprocess.Popen:
        self._process = subprocess.Popen(
            self._argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        self._pgid = self._process.pid
        return self._process

    @property
    def process(self) -> subprocess.Popen | None:
        return self._process

    @property
    def stderr(self) -> BinaryIO | None:
        if self._process is None:
            return None
        return self._process.stderr

    def send_request(self, method: str, params: dict, request_id: int = 1) -> None:
        if self._process is None or self._process.stdin is None:
            raise WorkerProcessError("worker not started")
        payload = json.dumps(
            {"jsonrpc": "2.0", "method": method, "params": params, "id": request_id},
            separators=(",", ":"),
        )
        frame = encode_content_length_frame(payload)
        try:
            self._process.stdin.write(frame)
            self._process.stdin.flush()
        except OSError as exc:
            raise WorkerProcessError(f"failed to send request: {exc}") from exc

    def read_response(self, request_id: int = 1) -> dict:
        """Read the next RPC response matching request_id.

        Notifications (messages without an 'id' field) are queued internally.
        Malformed JSON raises WorkerProcessError.
        """
        if self._process is None or self._process.stdout is None:
            raise WorkerProcessError("worker not started")
        while True:
            read1 = getattr(self._process.stdout, "read1", None)
            chunk = read1(8192) if read1 is not None else self._process.stdout.read(8192)
            if not chunk:
                raise WorkerProcessError("worker stdout closed before response")
            try:
                messages = self._decoder.feed(chunk)
            except TransportError as exc:
                raise WorkerProcessError(f"protocol error: {exc}") from exc
            for raw in messages:
                try:
                    msg = json.loads(raw)
                except (json.JSONDecodeError, ValueError) as exc:
                    raise WorkerProcessError(f"malformed JSON from worker: {exc}") from exc
                if not isinstance(msg, dict):
                    raise WorkerProcessError("expected JSON object from worker")
                if "id" not in msg:
                    self._notifications.append(msg)
                    continue
                if msg["id"] != request_id:
                    self._notifications.append(msg)
                    continue
                return msg

    def pop_notification(self) -> dict | None:
        if self._notifications:
            return self._notifications.popleft()
        return None

    def request(self, method: str, params: dict, request_id: int = 1) -> WorkerResult:
        try:
            self.send_request(method, params, request_id)
            response = self.read_response(request_id)
        except WorkerProcessError as exc:
            return WorkerResult(success=False, error=str(exc))
        if "error" in response:
            err_msg = response["error"].get("message", "rpc error")
            return WorkerResult(success=False, response=response, error=err_msg)
        return WorkerResult(success=True, response=response)

    def terminate(self) -> int | None:
        proc = self._process
        if proc is None:
            return None
        return _terminate_process_group(proc, self._pgid)

    def is_alive(self) -> bool:
        if self._process is None:
            return False
        return self._process.poll() is None


def _terminate_process_group(proc: subprocess.Popen, pgid: int | None = None) -> int:
    """Escalate signals to the worker process group.

    pgid is cached at start time (the worker pid, since start_new_session=True).
    Signals the group even after the leader has already exited, because
    descendants may still be running.
    """
    if pgid is None:
        pgid = proc.pid

    def _signal_group(sig: int) -> None:
        with suppress(OSError):
            os.killpg(pgid, sig)

    if proc.poll() is None:
        _signal_group(signal.SIGINT)
        try:
            proc.wait(timeout=_GRACEFUL_WAIT)
        except subprocess.TimeoutExpired:
            _signal_group(signal.SIGTERM)
            try:
                proc.wait(timeout=_FORCEFUL_WAIT)
            except subprocess.TimeoutExpired:
                _signal_group(signal.SIGKILL)
                proc.wait()
    else:
        _signal_group(signal.SIGTERM)
        _signal_group(signal.SIGKILL)

    return proc.returncode


def classify_worker_exit(proc: subprocess.Popen) -> WorkerResult:
    """Classify how the worker exited after it is no longer running."""
    code = proc.returncode
    if code is None:
        return WorkerResult(success=False, error="worker still running")
    if code == 0:
        return WorkerResult(success=True, exit_code=0)
    if code < 0:
        sig = -code
        try:
            sig_name = signal.Signals(sig).name
        except ValueError:
            sig_name = str(sig)
        return WorkerResult(
            success=False,
            exit_code=code,
            signal_number=sig,
            error=f"worker killed by {sig_name}",
        )
    return WorkerResult(success=False, exit_code=code, error=f"worker exited with code {code}")


def repair_flow_state(flow_json_path: str | Path, *, active_step: str | None = None) -> list[str]:
    """Repair Ongoing steps left by a crashed worker, setting them to Incomplete.

    If active_step is provided, only that specific step is repaired (operation-scoped).
    If active_step is None, all Ongoing steps are repaired (legacy fallback).

    Returns the list of step names that were repaired.
    Raises OSError if the repaired state cannot be persisted.
    """
    path = Path(flow_json_path)
    data = json_read(path)
    if not data:
        return []

    steps = data.get("steps")
    if not isinstance(steps, list):
        return []

    repaired: list[str] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        if step.get("state") != "Ongoing":
            continue
        step_name = step.get("name", "<unknown>")
        if active_step is not None and step_name != active_step:
            continue
        step["state"] = "Incomplete"
        repaired.append(step_name)

    if repaired:
        json_write(path, data)

    return repaired
