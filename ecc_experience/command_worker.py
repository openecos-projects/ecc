"""Keep command completion evidence alive when a campaign coordinator is lost."""

import ctypes
import os
import signal
import subprocess
import sys
from contextlib import suppress
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from chipcompiler.project.runtime_processes import current_process_identity
from ecc_experience.command_receipts import load_request
from ecc_experience.files import canonical_bytes, safe_child
from ecc_experience.optimization.plan import write_plan
from ecc_experience.optimization.process import cli_prefix


def _enable_subreaper() -> bool:
    if not Path("/proc/self/stat").is_file():
        return False
    try:
        return ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0
    except (OSError, AttributeError):
        return False


def execute(request_path: Path) -> int:
    request = load_request(request_path)
    if request.receipt.exists():
        raise FileExistsError("Command receipt already exists")
    owner = safe_child(request.path.parent, request.receipt.name + ".owner")
    with owner.open("xb") as stream:
        stream.write(canonical_bytes({"request_fingerprint": request.fingerprint}))
    subreaper = _enable_subreaper()
    receipt = {
        "schema_version": 1,
        "kind": "ecc-experience-command-receipt",
        "request_fingerprint": request.fingerprint,
        "worker": asdict(current_process_identity()),
        "started_at": datetime.now(UTC).isoformat(),
        "status": "running",
        "process_tree_quiescent": False,
        "subreaper": subreaper,
    }
    write_plan(request.receipt, receipt)
    child = None
    cancellation_requested = False

    def cancel(_signum, _frame):
        nonlocal cancellation_requested
        cancellation_requested = True
        if child is not None and child.poll() is None:
            with suppress(ProcessLookupError):
                os.kill(child.pid, signal.SIGUSR1)

    signal.signal(signal.SIGUSR1, cancel)
    signal.signal(signal.SIGTERM, cancel)
    try:
        child = subprocess.Popen([*cli_prefix(), *request.arguments])
        if cancellation_requested:
            cancel(None, None)
        exit_code = child.wait()
    except OSError as exc:
        exit_code = 1
        receipt["reason"] = str(exc)
    orphan_exits = []
    if subreaper:
        while True:
            try:
                _pid, status = os.waitpid(-1, 0)
                orphan_exits.append(os.waitstatus_to_exitcode(status))
            except ChildProcessError:
                break
    if exit_code == 0 and any(status != 0 for status in orphan_exits):
        exit_code = 6
    receipt.update(
        status="complete",
        exit_code=exit_code,
        process_tree_quiescent=subreaper,
        orphan_exit_codes=orphan_exits,
        finished_at=datetime.now(UTC).isoformat(),
    )
    write_plan(request.receipt, receipt)
    return exit_code


def main(arguments: list[str]) -> int:
    if len(arguments) != 1:
        return 2
    try:
        return execute(Path(arguments[0]).expanduser().absolute())
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
