"""Shared fixtures for CLI command tests."""

import json
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

    def run_steps(self):
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
