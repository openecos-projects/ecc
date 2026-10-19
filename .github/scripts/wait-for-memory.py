#!/usr/bin/env python3
"""Check startup headroom on Linux cgroup-v2 CI runners, without ECC imports."""

import argparse
import json
import time
from pathlib import Path
from typing import NamedTuple

PROC = Path("/proc")
CGROUP_ROOT = Path("/sys/fs/cgroup")
GIB = 1024**3


class MemorySnapshot(NamedTuple):
    total_bytes: int
    available_bytes: int
    effective_available_bytes: int


def read_memory() -> MemorySnapshot:
    fields = dict(line.split(":", 1) for line in (PROC / "meminfo").read_text().splitlines())
    total = int(fields["MemTotal"].split()[0]) * 1024
    available = int(fields["MemAvailable"].split()[0]) * 1024
    effective = available

    groups = [line.split(":", 2) for line in (PROC / "self/cgroup").read_text().splitlines()]
    if any("memory" in controllers.split(",") for _, controllers, _ in groups):
        raise ValueError("memory preflight requires cgroup v2, not a v1 memory controller")
    relative = next((path for hierarchy, _, path in groups if hierarchy == "0"), None)
    if relative is None or not relative.startswith("/") or ".." in Path(relative).parts:
        raise ValueError("cannot resolve the runner's cgroup-v2 memory limits")
    directory = CGROUP_ROOT / relative.lstrip("/")
    if not directory.is_dir():
        raise OSError(f"cgroup directory is unavailable: {directory}")

    # A parent slice can impose a tighter limit than this process's leaf group.
    while True:
        limit_path = directory / "memory.max"
        if limit_path.is_file():
            limit = limit_path.read_text().strip()
            if limit != "max":
                remaining = int(limit) - int((directory / "memory.current").read_text())
                effective = min(effective, max(0, remaining))
        if directory == CGROUP_ROOT:
            break
        directory = directory.parent
    return MemorySnapshot(total, available, effective)


def wait_for_memory(minimum_bytes: int, timeout_seconds: int, poll_seconds: int) -> bool:
    started = time.monotonic()
    deadline = started + timeout_seconds
    while True:
        snapshot = read_memory()
        now = time.monotonic()
        print(
            json.dumps(
                {
                    **snapshot._asdict(),
                    "required_bytes": minimum_bytes,
                    "waited_seconds": round(now - started, 2),
                }
            ),
            flush=True,
        )
        if snapshot.effective_available_bytes >= minimum_bytes:
            print("Memory preflight passed; this does not reserve memory for the flow.", flush=True)
            return True
        if now >= deadline:
            print(
                "::error title=Insufficient CI memory::"
                f"Available {snapshot.effective_available_bytes / GIB:.2f} GiB; "
                f"required {minimum_bytes / GIB:.2f} GiB after {timeout_seconds}s. "
                "The design flow was not started.",
                flush=True,
            )
            return False
        time.sleep(min(poll_seconds, deadline - now))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minimum-gib", type=int, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    parser.add_argument("--poll-seconds", type=int, default=10)
    args = parser.parse_args(argv)
    if args.minimum_gib <= 0 or args.timeout_seconds < 0 or args.poll_seconds <= 0:
        parser.error("minimum and poll interval must be positive; timeout must be nonnegative")
    try:
        ready = wait_for_memory(args.minimum_gib * GIB, args.timeout_seconds, args.poll_seconds)
    except (OSError, ValueError, KeyError) as exc:
        print(f"::error title=CI memory probe failed::{exc}", flush=True)
        return 1
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
