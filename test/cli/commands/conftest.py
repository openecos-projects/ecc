"""Shared fixtures for CLI command tests."""

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

    def fake_run_flow_via_worker(workspace_dir):
        for inst in DummyFlow.instances:
            inst.run_called = True
        return DummyFlow.run_steps_value

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
    monkeypatch.setattr(
        "chipcompiler.cli.command_handlers.project._run_flow_via_worker",
        fake_run_flow_via_worker,
    )

    return SimpleNamespace(capture=capture, flow=DummyFlow)
