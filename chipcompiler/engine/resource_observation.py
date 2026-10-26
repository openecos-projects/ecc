"""Best-effort Linux resource facts with explicit execution attribution limits."""

import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread
from uuid import uuid4

from chipcompiler.project.runtime_processes import boot_id, host_id

_PROC = Path("/proc")
_INTERVAL_SECONDS = 0.2
_CONCURRENCY_ENV = {
    "current_flows": "ECC_EXPERIENCE_CURRENT_FLOWS",
    "max_concurrent": "ECC_EXPERIENCE_MAX_CONCURRENT",
    "trial_threads": "ECC_EXPERIENCE_TRIAL_THREADS",
}
_OUTCOMES = {"success", "failed", "oom", "timeout", "cancelled", "unknown"}


def _stat(pid: int) -> tuple[str, int, int]:
    raw = (_PROC / str(pid) / "stat").read_text(encoding="ascii")
    fields = raw[raw.rfind(")") + 2 :].split()
    return fields[19], int(fields[1]), max(0, int(fields[21])) * os.sysconf("SC_PAGE_SIZE")


class ResourceObservation:
    def __init__(
        self,
        pid: int,
        *,
        isolated: bool,
        step: str,
        tool: str,
        concurrency: dict | None = None,
    ):
        self.pid = pid
        self.isolated = isolated
        self.step = step
        self.tool = tool
        self.attempt_id = f"step-attempt-{uuid4().hex}"
        self.started_at = datetime.now(UTC).isoformat()
        self.started = time.monotonic()
        self.start_id = None
        self.boot_id = None
        self.host_id = None
        self.peak_rss_bytes = None
        self.samples = 0
        self.missed_processes = 0
        self.error = None
        self.stop_event = Event()
        self.thread = None
        self.concurrency = _concurrency_facts(concurrency)
        self.outcome = "unknown"
        self.host = _host_facts()

    def start(self) -> None:
        try:
            self.start_id, _parent, _rss = _stat(self.pid)
            self.boot_id = boot_id()
            self.host_id = host_id()
            self.sample()
            self.thread = Thread(target=self._monitor, daemon=True)
            self.thread.start()
        except (OSError, ValueError, IndexError, RuntimeError) as exc:
            self.error = str(exc) or type(exc).__name__

    def sample(self) -> None:
        try:
            identity, _parent, _rss = _stat(self.pid)
            if identity != self.start_id:
                self.error = "Root PID identity changed"
                return
        except FileNotFoundError:
            return
        total = 0
        pending: list[tuple[int, int | None]] = [(self.pid, None)]
        visited = set()
        while pending and not self.stop_event.is_set():
            pid, expected_parent = pending.pop()
            if pid in visited:
                continue
            visited.add(pid)
            try:
                identity, parent, rss = _stat(pid)
                if (pid == self.pid and identity != self.start_id) or (
                    expected_parent is not None and parent != expected_parent
                ):
                    self.missed_processes += 1
                    continue
                total += rss
                tasks = _PROC / str(pid) / "task"
                for task in tasks.iterdir():
                    try:
                        children = (task / "children").read_text(encoding="ascii").split()
                    except FileNotFoundError:
                        continue
                    pending.extend((int(child), pid) for child in children)
            except FileNotFoundError:
                self.missed_processes += 1
            except (OSError, ValueError, IndexError) as exc:
                self.missed_processes += 1
                self.error = str(exc) or type(exc).__name__
        if total > 0:
            self.peak_rss_bytes = max(self.peak_rss_bytes or 0, total)
            self.samples += 1

    def _monitor(self) -> None:
        while not self.stop_event.wait(_INTERVAL_SECONDS):
            try:
                self.sample()
            except (OSError, ValueError, IndexError, RuntimeError) as exc:
                self.error = str(exc) or type(exc).__name__

    def finish(self, *, outcome: str | None = None) -> dict:
        self.stop_event.set()
        if outcome is not None:
            if outcome not in _OUTCOMES:
                raise ValueError(f"unsupported resource outcome: {outcome}")
            self.outcome = outcome
        if self.thread is not None and self.thread.ident is not None:
            self.thread.join(timeout=2)
            if self.thread.is_alive():
                self.error = "Resource sampler did not stop before finalization"
        reason = self.error
        if self.samples == 0:
            status = "unavailable"
            reason = reason or "Process RSS could not be sampled"
        elif not self.isolated or self.missed_processes or self.error:
            status = "partial"
            reason = reason or (
                "Shared process tree includes other work"
                if not self.isolated
                else "Some processes disappeared or could not be observed"
            )
        else:
            status = "available"
        return {
            "schema_version": 1,
            "kind": "ecc-step-resource-observation",
            "attempt_id": self.attempt_id,
            "step": self.step,
            "tool": self.tool,
            "started_at": self.started_at,
            "finished_at": datetime.now(UTC).isoformat(),
            "elapsed_seconds": max(0.0, time.monotonic() - self.started),
            "root_pid": self.pid,
            "process_start_id": self.start_id,
            "host_id": self.host_id,
            "boot_id": self.boot_id,
            "logical_cpu_count": os.cpu_count(),
            "peak_rss_bytes": self.peak_rss_bytes,
            "sample_count": self.samples,
            "sample_interval_seconds": _INTERVAL_SECONDS,
            "missed_processes": self.missed_processes,
            "method": "linux_proc_stat_rss_sum",
            "scope": "isolated_worker_process_tree" if self.isolated else "shared_process_tree",
            "frozen": bool(getattr(sys, "frozen", False)),
            "host": self.host,
            "concurrency": {
                "current_flows": _positive_int(self.concurrency.get("current_flows", 1)),
                "max_concurrent": _positive_int(self.concurrency.get("max_concurrent", 1)),
                "trial_threads": self.concurrency.get("trial_threads"),
            },
            "measurement": {
                "method": "linux_proc_stat_rss_sum",
                "interval_seconds": _INTERVAL_SECONDS,
                "sample_count": self.samples,
                "missed_processes": self.missed_processes,
                "scope": "isolated_worker_process_tree" if self.isolated else "shared_process_tree",
                "status": status,
            },
            "outcome": {
                "status": self.outcome,
            },
            "status": status,
            "reason": reason,
            "limitations": [
                "Sampled RSS may miss short peaks and double-count shared pages",
                "Elapsed time covers the tool and observation, excluding the rest of the flow",
                "Shared process measurements cannot be attributed to one step",
            ],
        }


def start_observation(
    pid: int,
    *,
    isolated: bool,
    step: str,
    tool: str,
    concurrency: dict | None = None,
) -> ResourceObservation:
    observation = ResourceObservation(
        pid, isolated=isolated, step=step, tool=tool, concurrency=concurrency
    )
    observation.start()
    return observation


def _host_facts() -> dict:
    cpu_model = None
    physical = set()
    try:
        physical_id = core_id = None
        for line in (
            Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace").splitlines()
        ):
            key, separator, value = line.partition(":")
            if not separator:
                continue
            key = key.strip()
            value = value.strip()
            if key == "model name" and cpu_model is None:
                cpu_model = value
            elif key == "physical id":
                physical_id = value
            elif key == "core id":
                core_id = value
                if physical_id is not None:
                    physical.add((physical_id, core_id))
    except OSError:
        pass
    total_memory = None
    try:
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            if line.startswith("MemTotal:"):
                total_memory = int(line.split()[1]) * 1024
                break
    except (OSError, ValueError, IndexError):
        pass
    try:
        load = list(os.getloadavg())
    except (OSError, AttributeError):
        load = None
    return {
        "cpu_model": cpu_model,
        "physical_cores": len(physical) or None,
        "logical_cores": os.cpu_count(),
        "total_memory_bytes": total_memory,
        "load_average": load,
        "frozen": bool(getattr(sys, "frozen", False)),
    }


def _concurrency_facts(explicit: dict | None) -> dict:
    values: dict[str, object] = {}
    for key, variable in _CONCURRENCY_ENV.items():
        value = os.environ.get(variable)
        if value is not None and value.strip():
            values[key] = value
    if explicit:
        values.update(explicit)
    return {
        "current_flows": _positive_int(values.get("current_flows", 1)),
        "max_concurrent": _positive_int(values.get("max_concurrent", 1)),
        "trial_threads": values.get("trial_threads"),
    }


def _positive_int(value: object) -> int:
    if isinstance(value, str):
        try:
            value = int(value)
        except ValueError:
            return 1
    return value if type(value) is int and value >= 1 else 1
