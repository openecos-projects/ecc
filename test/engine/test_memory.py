import pytest

from chipcompiler.data import Workspace, WorkspaceStep
from chipcompiler.engine import memory as memory_probe
from chipcompiler.engine.flow import EngineFlow
from chipcompiler.engine.memory import MemoryStatus
from chipcompiler.tools.ecc import sta_parallel as sta


def _map_memory_files(tmp_path, monkeypatch):
    files = {
        "/proc/meminfo": "MemTotal: 33554432 kB\nMemAvailable: 16777216 kB\n",
        "/proc/self/cgroup": "0::/test/child\n",
        "/sys/fs/cgroup/test/memory.max": str(16384 * 1024**2),
        "/sys/fs/cgroup/test/memory.current": "0",
    }
    for name, content in files.items():
        path = tmp_path / name.lstrip("/")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def mapped_path(value):
        return tmp_path / value.lstrip("/")

    monkeypatch.setattr(memory_probe, "Path", mapped_path)
    return mapped_path


def _checker_workers(tmp_path, steps=3):
    workspace = Workspace(directory=tmp_path)
    flow = EngineFlow(workspace)
    steps = [WorkspaceStep(name=f"checker-{index}", tool="ecc") for index in range(steps)]
    records = [flow.init_flow_step(step.name, step.tool, "Unstart") for step in steps]
    for record in records:
        record["peak memory (mb)"] = 1024
    workspace.flow.data = {"schema_version": 2, "steps": records}
    return flow._checker_parallelism(steps)


def test_cgroup_capacity_bounds_checker_without_double_reserve(tmp_path, monkeypatch):
    _map_memory_files(tmp_path, monkeypatch)

    assert memory_probe.read_memory_status() == MemoryStatus(total_mb=16384, available_mb=16384)
    assert sta._memory_headroom_mb() == pytest.approx(14745.6)
    assert _checker_workers(tmp_path) == 3


@pytest.mark.parametrize("failure", ["v1", "missing"])
def test_probe_failure_forces_serial_checker_and_zero_sta_headroom(tmp_path, monkeypatch, failure):
    mapped_path = _map_memory_files(tmp_path, monkeypatch)
    if failure == "v1":
        mapped_path("/proc/self/cgroup").write_text("5:memory:/test\n", encoding="utf-8")
    else:
        mapped_path("/proc/meminfo").unlink()

    assert memory_probe.read_memory_status() == MemoryStatus(0.0, 0.0)
    assert sta._memory_headroom_mb() == 0
    assert _checker_workers(tmp_path) == 1
