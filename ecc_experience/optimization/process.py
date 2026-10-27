"""Invoke the public ECC CLI with bounded process-group lifetime and disk logs."""

import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path

from chipcompiler.cli.core.exit_codes import EXIT_TIMEOUT
from chipcompiler.project.runtime_processes import RuntimeProcessError, _process_start_id
from ecc_experience.command_receipts import prepare_request, read_receipt


@dataclass(frozen=True)
class Invocation:
    exit_code: int
    stdout: Path
    stderr: Path


def cli_prefix() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, "-m", "chipcompiler.cli.main"]


@contextmanager
def cancellation_signals():
    def interrupted(_signum, _frame):
        raise KeyboardInterrupt

    if threading.current_thread() is not threading.main_thread():
        yield
        return
    previous = signal.signal(signal.SIGTERM, interrupted)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


class CliRunner:
    def __init__(self, output: Path, deadline: float, *, durable_receipts: bool = False):
        self.output = output
        self.deadline = deadline
        self.sequence = 0
        self.durable_receipts = durable_receipts
        self._sequence_lock = threading.Lock()
        self._environment = threading.local()

    def set_environment(self, values: dict[str, str] | None) -> None:
        if values:
            self._environment.values = {key: str(value) for key, value in values.items()}
        else:
            self.clear_environment()

    def clear_environment(self) -> None:
        if hasattr(self._environment, "values"):
            del self._environment.values

    def invoke(
        self,
        arguments: list[str],
        *,
        deadline: float,
        on_prepared: Callable[[dict], None] | None = None,
    ) -> Invocation:
        with self._sequence_lock:
            self.sequence += 1
            sequence = self.sequence
        prefix = self.output / f"command-{sequence:04d}"
        stdout = prefix.with_suffix(".stdout.log")
        stderr = prefix.with_suffix(".stderr.log")
        timeout = min(self.deadline, deadline) - time.monotonic()
        if timeout <= 0:
            return Invocation(EXIT_TIMEOUT, stdout, stderr)
        request = prepare_request(prefix, arguments) if self.durable_receipts else None
        if request is not None and on_prepared is not None:
            on_prepared({**request.metadata(), "stdout": str(stdout), "stderr": str(stderr)})
        command = ["_experience-command-worker", str(request.path)] if request else arguments
        with stdout.open("xb") as output_stream, stderr.open("xb") as error_stream:
            environment = getattr(self._environment, "values", None)
            process = subprocess.Popen(
                [*cli_prefix(), *command],
                stdout=output_stream,
                stderr=error_stream,
                start_new_session=True,
                env={**os.environ, **environment} if environment else None,
            )
            try:
                exit_code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self._stop(process, cooperative=arguments[0] == "run")
                exit_code = EXIT_TIMEOUT
            except BaseException:
                self._stop(process, cooperative=arguments[0] == "run")
                raise
        if request is not None and exit_code != EXIT_TIMEOUT:
            receipt = read_receipt(request, request.fingerprint)
            if receipt is not None and receipt["status"] == "complete":
                exit_code = receipt["exit_code"]
        return Invocation(exit_code, stdout, stderr)

    @staticmethod
    def _stop(process: subprocess.Popen, *, cooperative: bool) -> None:
        if process.poll() is not None:
            return
        if cooperative:
            with suppress(ProcessLookupError):
                os.kill(process.pid, signal.SIGUSR1)
            with suppress(subprocess.TimeoutExpired):
                process.wait(timeout=10)
                return
        identities: list[tuple[int, str]] = []

        def signal_identity(pid: int, identity: str, signum: int) -> None:
            with suppress(OSError, RuntimeProcessError):
                if _process_start_id(pid) == identity:
                    os.kill(pid, signum)

        def freeze_tree(pid: int) -> None:
            try:
                identity = _process_start_id(pid)
            except (OSError, RuntimeProcessError):
                return
            signal_identity(pid, identity, signal.SIGSTOP)
            identities.append((pid, identity))
            children = set()
            for task in Path(f"/proc/{pid}/task").glob("*/children"):
                with suppress(OSError):
                    children.update(int(child) for child in task.read_text().split())
            for child in children:
                freeze_tree(child)

        freeze_tree(process.pid)
        for pid, identity in reversed(identities):
            signal_identity(pid, identity, signal.SIGKILL)
        process.wait()
        deadline = time.monotonic() + 5
        while identities and time.monotonic() < deadline:
            remaining = []
            for pid, identity in identities:
                with suppress(OSError, RuntimeProcessError):
                    if _process_start_id(pid) == identity:
                        remaining.append((pid, identity))
            identities = remaining
            if identities:
                time.sleep(0.01)
        if identities:
            raise OSError("Failed to stop the complete ECC subprocess tree")
