"""Shared fixtures for CLI command tests."""

import json
import os
import shutil
from types import SimpleNamespace

import pytest


class DummyFlow:
    has_init_value = False
    run_steps_value = True
    instances = []

    def __init__(self, workspace):
        self.workspace = workspace
        self.added_steps = []
        self.create_called = False
        self.run_called = False
        self.workspace_steps = []
        DummyFlow.instances.append(self)

    def has_init(self):
        return self.has_init_value

    def add_step(self, step, tool, state):
        self.added_steps.append((step, tool, state))

    def create_step_workspaces(self):
        self.create_called = True

    def run_steps(self, **_kwargs):
        self.run_called = True
        return self.run_steps_value

    def run_step(self, workspace_step):
        from chipcompiler.data import StateEnum

        self.run_called = True
        return StateEnum.Success if self.run_steps_value else StateEnum.Imcomplete


@pytest.fixture
def flow_mocks(monkeypatch):
    """Install create_workspace/EngineFlow mocks for `ecc run` tests.

    Returns a namespace with `capture` (the create_workspace kwargs) and
    `flow` (the DummyFlow class, for instance/state assertions).
    """
    capture = {"create_kwargs": None}
    workspace_obj = SimpleNamespace(name="workspace")

    DummyFlow.instances = []
    DummyFlow.has_init_value = False
    DummyFlow.run_steps_value = True

    def fake_create_workspace(**kwargs):
        capture["create_kwargs"] = kwargs
        return workspace_obj

    monkeypatch.setattr("chipcompiler.data.create_workspace", fake_create_workspace)
    monkeypatch.setattr("chipcompiler.engine.EngineFlow", DummyFlow)
    monkeypatch.setattr(
        "chipcompiler.rtl2gds.builder.build_rtl2gds_flow",
        lambda: [("Synthesis", "yosys", "Unstart")],
    )
    monkeypatch.setattr(
        "chipcompiler.cli.project.config._validate_pdk_contents",
        lambda name, root, overrides=None: None,
    )

    return SimpleNamespace(capture=capture, flow=DummyFlow)


@pytest.fixture
def manifest_stubs(capsys):
    """Shared manifest-project scaffolding: project.json writer, workspace
    entry builder, and JSON record reader bound to capsys."""

    def _write(project_dir, workspaces, **overrides):
        rtl = project_dir / "rtl" / "gcd.v"
        rtl.parent.mkdir(parents=True, exist_ok=True)
        rtl.write_text("module gcd(input clk); endmodule\n")
        (project_dir / "pdk").mkdir(exist_ok=True)
        document = {
            "schema_version": 1,
            "design_name": "gcd",
            "root_path": str(project_dir),
            "base_design": {
                "pdk": "ics55",
                "pdk_root": str(project_dir / "pdk"),
                "top_module": "gcd",
                "clock": "clk",
                "rtl_list": ["rtl/gcd.v"],
                "parameters": {"design": "gcd", "frequency_max": 100},
            },
            "workspaces": workspaces,
        }
        document.update(overrides)
        (project_dir / "project.json").write_text(json.dumps(document))

    def _entry(project_dir, workspace_id, status="success"):
        return {
            "workspace_id": workspace_id,
            "workspace_path": str(project_dir / workspace_id),
            "status": status,
        }

    def _records():
        return json.loads(capsys.readouterr().out)["records"]

    return SimpleNamespace(write=_write, entry=_entry, records=_records)


@pytest.fixture
def spy_mutations(monkeypatch):
    """Factory installing chmod/rmtree spies AT CALL TIME.

    Overwrite-guard tests call it after their own setup chmods, so only
    the command-under-test's mutations are recorded."""

    def _install():
        calls = {"chmod": [], "rmtree": []}
        real_chmod = os.chmod
        real_rmtree = shutil.rmtree

        def chmod_spy(path, mode, **kwargs):
            calls["chmod"].append(path)
            return real_chmod(path, mode, **kwargs)

        def rmtree_spy(path, *args, **kwargs):
            calls["rmtree"].append(path)
            return real_rmtree(path, *args, **kwargs)

        monkeypatch.setattr(os, "chmod", chmod_spy)
        monkeypatch.setattr(shutil, "rmtree", rmtree_spy)
        return calls

    return _install


@pytest.fixture
def legacy_hint():
    """The expected legacy_layout_detected record for a project path."""

    def _build(project_dir):
        return {
            "kind": "warning",
            "warning": "legacy_layout_detected",
            "reason": "this project uses the legacy runs/ layout; run 'ecc migrate' to upgrade",
            "migrate": f"ecc migrate --project {project_dir} --yes",
        }

    return _build


@pytest.fixture
def create_legacy_workspace():
    """Factory: a real runs/<run_id> workspace with a Synthesis..Floorplan
    flow ledger cut from the canonical chain.

    *states* holds (first step state, last step state); steps between them
    inherit the first state."""

    def _create(project_dir, pdk_root, run_id, states):
        from chipcompiler.data import create_workspace
        from chipcompiler.data.workspace_config import flow_steps_in_range
        from chipcompiler.rtl2gds.builder import build_harden_flow

        rtl_path = os.path.join(project_dir, "rtl", "gcd.v")
        os.makedirs(os.path.dirname(rtl_path), exist_ok=True)
        with open(rtl_path, "w") as f:
            f.write("module gcd(input clk, output y); assign y = clk; endmodule\n")

        run_dir = os.path.join(project_dir, "runs", run_id)
        workspace = create_workspace(
            directory=run_dir,
            origin_def="",
            origin_verilog=rtl_path,
            pdk="ics55",
            parameters={"pdk": "ics55", "design": "gcd", "top_module": "gcd", "clock": "clk"},
            pdk_root=str(pdk_root),
        )
        assert workspace is not None

        chain = [
            (step.value if hasattr(step, "value") else str(step), str(tool))
            for step, tool, _state in build_harden_flow()
        ]
        tools = dict(chain)
        names = flow_steps_in_range("Synthesis", "Floorplan")
        step_states = [states[0]] * (len(names) - 1) + [states[1]]
        steps = [
            {
                "name": name,
                "tool": tools[name],
                "state": state,
                "runtime": "",
                "peak memory (mb)": 0,
                "info": {},
            }
            for name, state in zip(names, step_states, strict=True)
        ]
        with open(os.path.join(run_dir, "home", "flow.json"), "w") as f:
            json.dump({"steps": steps}, f)
        return run_dir

    return _create
