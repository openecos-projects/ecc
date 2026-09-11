import importlib.util
import os
import sys
from pathlib import Path

import agent.rpc_server


def _load_entrypoint_module():
    project_root = Path(__file__).parents[2]
    module_path = project_root / "packaging" / "run_ecc.py"
    spec = importlib.util.spec_from_file_location("ecc_packaged_entrypoint", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_agent_rpc_alias_selects_agent_entrypoint(monkeypatch):
    module = _load_entrypoint_module()
    calls = []

    monkeypatch.setattr(sys, "argv", [os.path.join("dist", "ecc-agent-rpc")])
    monkeypatch.setattr(agent.rpc_server, "main", lambda: calls.append("agent") or 7)

    assert module.main() == 7

    assert calls == ["agent"]


def test_packaged_entrypoint_propagates_exit_code():
    project_root = Path(__file__).parents[2]
    source = (project_root / "packaging" / "run_ecc.py").read_text()

    assert "raise SystemExit(main())" in source
