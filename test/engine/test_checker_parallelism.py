"""Memory-bounded worker count for a parallel analysis wave."""

from types import SimpleNamespace
from typing import cast

import chipcompiler.engine.flow.runner as flow_module
from chipcompiler.data import WorkspaceStep
from chipcompiler.data.workspace import Workspace
from chipcompiler.engine.flow.runner import EngineFlow
from chipcompiler.engine.memory import MemoryStatus

CHECKER_NAMES = (
    "lvs",
    "drc",
    "antennaCheck",
    "postRouteLec",
    "RCX",
    "sta",
    "powerAnalysis",
    "emir",
)


def _step(name: str):
    return SimpleNamespace(name=name, tool="ecc")


def test_wave_parallelism_is_capped_by_max_parallel_steps_and_memory(monkeypatch, tmp_path):
    flow = EngineFlow(Workspace(directory=tmp_path))
    steps = [_step(name) for name in CHECKER_NAMES]
    monkeypatch.setattr(flow, "_step_memory_estimate_mb", lambda _step: 4096.0)

    monkeypatch.setattr(flow_module, "read_memory_status", lambda: MemoryStatus(0.0, 128 * 1024))
    assert flow._checker_parallelism(cast(list[WorkspaceStep], steps)) == flow.max_parallel_steps

    monkeypatch.setattr(flow_module, "read_memory_status", lambda: MemoryStatus(0.0, 12 * 1024))
    assert flow._checker_parallelism(cast(list[WorkspaceStep], steps)) == 2
