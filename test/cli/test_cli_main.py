#!/usr/bin/env python

from types import SimpleNamespace

import pytest

from chipcompiler.cli import main as cli_main


class DummyFlow:
    has_init_value = False
    run_steps_value = True
    instances = []

    def __init__(self, workspace):
        self.workspace = workspace
        self.added_steps = []
        self.create_called = False
        self.run_called = False
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


def _common_args(workspace, rtl, pdk_root):
    return [
        "--workspace",
        str(workspace),
        "--rtl",
        str(rtl),
        "--design",
        "top_design",
        "--top",
        "top",
        "--clock",
        "clk",
        "--pdk-root",
        str(pdk_root),
    ]


def _install_cli_mocks(monkeypatch):
    capture = {
        "create_kwargs": None,
        "log_workspace_calls": 0,
    }
    workspace_obj = SimpleNamespace(name="workspace")

    DummyFlow.instances = []
    DummyFlow.has_init_value = False
    DummyFlow.run_steps_value = True

    def fake_create_workspace(**kwargs):
        capture["create_kwargs"] = kwargs
        return workspace_obj

    def fake_log_workspace(workspace):
        assert workspace is workspace_obj
        capture["log_workspace_calls"] += 1

    monkeypatch.setattr(cli_main, "create_workspace", fake_create_workspace)
    monkeypatch.setattr(cli_main, "EngineFlow", DummyFlow)
    monkeypatch.setattr(cli_main, "build_rtl2gds_flow", lambda: [("Synthesis", "yosys", "Unstart")])
    monkeypatch.setattr(cli_main, "log_workspace", fake_log_workspace)

    return capture


def test_cli_rtl_mode_calls_create_workspace_correctly(tmp_path, monkeypatch):
    rtl = tmp_path / "top.v"
    rtl.write_text("module top(input clk); endmodule\n")
    pdk_root = tmp_path / "ics55"
    pdk_root.mkdir()
    workspace_dir = tmp_path / "ws"

    capture = _install_cli_mocks(monkeypatch)
    rc = cli_main.run(_common_args(workspace_dir, rtl, pdk_root))

    assert rc == 0
    assert capture["create_kwargs"]["origin_verilog"] == str(rtl.resolve())
    assert capture["create_kwargs"]["input_filelist"] == ""
    assert capture["create_kwargs"]["pdk"] == "ics55"
    assert capture["create_kwargs"]["parameters"]["Design"] == "top_design"
    assert capture["create_kwargs"]["parameters"]["Top module"] == "top"
    assert capture["create_kwargs"]["parameters"]["Clock"] == "clk"
    assert capture["create_kwargs"]["parameters"]["Frequency max [MHz]"] == 100.0
    assert DummyFlow.instances[0].create_called is True
    assert DummyFlow.instances[0].run_called is True
    assert capture["log_workspace_calls"] == 1


def test_cli_filelist_mode_calls_create_workspace_correctly(tmp_path, monkeypatch):
    rtl_source = tmp_path / "a.v"
    rtl_source.write_text("module a(); endmodule\n")
    filelist = tmp_path / "design.f"
    filelist.write_text("a.v\n")
    pdk_root = tmp_path / "ics55"
    pdk_root.mkdir()
    workspace_dir = tmp_path / "ws"

    capture = _install_cli_mocks(monkeypatch)
    rc = cli_main.run(_common_args(workspace_dir, filelist, pdk_root))

    assert rc == 0
    assert capture["create_kwargs"]["origin_verilog"] == ""
    assert capture["create_kwargs"]["input_filelist"] == str(filelist.resolve())


def test_cli_unknown_suffix_fallback_to_filelist(tmp_path, monkeypatch):
    rtl_source = tmp_path / "b.v"
    rtl_source.write_text("module b(); endmodule\n")
    filelist_like = tmp_path / "design.listing"
    filelist_like.write_text("b.v\n")
    pdk_root = tmp_path / "ics55"
    pdk_root.mkdir()
    workspace_dir = tmp_path / "ws"

    capture = _install_cli_mocks(monkeypatch)
    rc = cli_main.run(_common_args(workspace_dir, filelist_like, pdk_root))

    assert rc == 0
    assert capture["create_kwargs"]["origin_verilog"] == ""
    assert capture["create_kwargs"]["input_filelist"] == str(filelist_like.resolve())


def test_cli_requires_mandatory_arguments():
    with pytest.raises(SystemExit) as exc_info:
        cli_main.run([])
    assert exc_info.value.code == 2


def test_cli_returns_nonzero_when_run_steps_failed(tmp_path, monkeypatch):
    rtl = tmp_path / "top.v"
    rtl.write_text("module top(input clk); endmodule\n")
    pdk_root = tmp_path / "ics55"
    pdk_root.mkdir()
    workspace_dir = tmp_path / "ws"

    _install_cli_mocks(monkeypatch)
    DummyFlow.run_steps_value = False

    rc = cli_main.run(_common_args(workspace_dir, rtl, pdk_root))
    assert rc == 1

