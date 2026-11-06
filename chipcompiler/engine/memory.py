"""Raw host and cgroup memory capacity facts."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MemoryStatus:
    total_mb: float
    available_mb: float


def read_memory_status() -> MemoryStatus:
    try:
        fields = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
        available = int(fields["MemAvailable"].split()[0]) / 1024
        total = int(fields["MemTotal"].split()[0]) / 1024
        for line in Path("/proc/self/cgroup").read_text().splitlines():
            if "memory" in line.split(":", 2)[1].split(","):
                return MemoryStatus(0.0, 0.0)
            if not line.startswith("0::"):
                continue
            root = Path("/sys/fs/cgroup")
            relative = line.split("::", 1)[1].lstrip("/")
            if ".." in relative.split("/"):
                return MemoryStatus(0.0, 0.0)
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
        return MemoryStatus(max(0.0, total), max(0.0, available))
    except (OSError, ValueError, KeyError, IndexError):
        return MemoryStatus(0.0, 0.0)
