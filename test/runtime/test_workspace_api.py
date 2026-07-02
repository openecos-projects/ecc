import json
import queue
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from chipcompiler.data import StateEnum
from chipcompiler.runtime.requests import (
    FlowRunRequest,
    FlowRunStepRequest,
    WorkspaceCreateRequest,
    WorkspaceIdRequest,
    WorkspaceInfoRequest,
    WorkspaceOpenRequest,
    WorkspaceSyncConfigRequest,
)
from chipcompiler.runtime.workspace_api import RuntimeApiError, WorkspaceRuntimeApi


class DummyEngineDB:
    def __init__(self, flow):
        self.flow = flow
        self.initialized = False

    def has_init(self):
        return self.initialized

    def create_db_engine(self, step):
        self.flow.init_db_engine_calls += 1
        self.flow.init_db_engine_steps.append(None if step is None else step.name)
        self.flow.call_order.append(("init_db_engine",))
        self.initialized = True
        return True


class DummyFlow:
    instances = []
    next_run_states = []
    successful_steps = set()

    def __init__(self, workspace):
        self.workspace = workspace
        self.added_steps = []
        self.created = False
        self.prepared_for_rerun = False
        self.run_steps_calls = []
        self.run_calls = []
        self.init_db_engine_calls = 0
        self.init_db_engine_steps = []
        self.call_order = []
        self.workspace_steps = [
            SimpleNamespace(name="Synthesis", tool="yosys"),
            SimpleNamespace(name="Floorplan", tool="ecc"),
        ]
        self.engine_db = DummyEngineDB(self)
        DummyFlow.instances.append(self)

    def has_init(self):
        return False

    def add_step(self, step, tool, state):
        self.added_steps.append((step, tool, state))
        self.workspace.flow.data.setdefault("steps", []).append(
            {"name": step, "tool": tool, "state": state}
        )

    def create_step_workspaces(self):
        self.created = True

    def run_steps(self, rerun=False):
        self.run_steps_calls.append(rerun)
        success = True
        for workspace_step in self.workspace_steps:
            state = self.run_step(workspace_step, rerun)
            if state != StateEnum.Success:
                success = False
                break
        return success

    def run_step(self, workspace_step, rerun=False):
        name = workspace_step if isinstance(workspace_step, str) else workspace_step.name
        self.run_calls.append((name, rerun))
        self.call_order.append(("run_step", name, rerun))
        if DummyFlow.next_run_states:
            return DummyFlow.next_run_states.pop(0)
        return StateEnum.Success

    def get_workspace_step(self, name):
        for step in self.workspace_steps:
            if step.name == name:
                return step
        return None

    def check_state(self, name, tool, state):
        return getattr(state, "value", state) == StateEnum.Success.value and name in (
            self.successful_steps
        )


def _workspace(directory: Path):
    design = SimpleNamespace(
        name="gcd",
        top_module="gcd",
        origin_def="",
        origin_verilog=directory / "origin" / "gcd.v",
        input_filelist="",
    )
    return SimpleNamespace(
        directory=directory.resolve(),
        design=design,
        flow=SimpleNamespace(path=directory / "home" / "flow.json", data={"steps": []}),
        home=SimpleNamespace(path=directory / "home" / "home.json"),
    )


def _install_runtime_mocks(monkeypatch, tmp_path):
    capture = {"create_kwargs": None, "loaded": []}
    DummyFlow.instances = []
    DummyFlow.next_run_states = []
    DummyFlow.successful_steps = set()

    def fake_create_workspace(**kwargs):
        capture["create_kwargs"] = kwargs
        return _workspace(Path(kwargs["directory"]))

    def fake_load_workspace(directory):
        capture["loaded"].append(directory)
        return _workspace(Path(directory))

    monkeypatch.setattr("chipcompiler.data.create_workspace", fake_create_workspace)
    monkeypatch.setattr("chipcompiler.data.load_workspace", fake_load_workspace)
    monkeypatch.setattr("chipcompiler.data.refresh_workspace_config", lambda workspace: None)
    monkeypatch.setattr("chipcompiler.data.prepare_workspace_for_rerun", lambda ws, flow: None)
    monkeypatch.setattr("chipcompiler.engine.EngineFlow", DummyFlow)
    monkeypatch.setattr(
        "chipcompiler.rtl2gds.build_rtl2gds_flow",
        lambda: [("Synthesis", "yosys", "Unstart")],
    )

    ws = tmp_path / "workspace"
    (ws / "home").mkdir(parents=True)
    (ws / "home" / "parameters.json").write_text("{}")
    (ws / "home" / "flow.json").write_text(json.dumps({"steps": []}))
    (ws / "home" / "home.json").write_text("{}")
    return capture, ws


def _assert_call_waits_for_session_lock(api, workspace_id, call, entered):
    session = api.sessions.get_session(workspace_id)
    result_queue = queue.Queue()

    def run_call():
        try:
            result_queue.put(("result", call()))
        except BaseException as exc:  # pragma: no cover - re-raised in test thread
            result_queue.put(("error", exc))

    with session.mutation_lock:
        worker = threading.Thread(target=run_call)
        worker.start()
        assert not entered.wait(0.1)
        assert worker.is_alive()

    worker.join(timeout=2)
    assert not worker.is_alive()
    kind, payload = result_queue.get_nowait()
    if kind == "error":
        raise payload
    assert entered.is_set()
    return payload


def test_create_workspace_returns_plain_runtime_result_and_session(monkeypatch, tmp_path):
    capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    api = WorkspaceRuntimeApi()

    result = api.create_workspace(
        WorkspaceCreateRequest(
            directory=str(ws),
            pdk="ics55",
            pdk_root="/pdk",
            pdk_json={"name": "ics55"},
            parameters={"Design": "gcd"},
            rtl_list=["a.v"],
        )
    )

    assert set(result) == {"workspaceId", "directory"}
    assert result["directory"] == str(ws.resolve())
    assert result["workspaceId"].startswith("workspace-")
    assert isinstance(capture["create_kwargs"]["pdk_json"], str)
    assert DummyFlow.instances[0].created
    assert api.sessions.get_session(result["workspaceId"]).directory == ws.resolve()


def test_create_workspace_materializes_inline_pdk_json_before_data_api(monkeypatch, tmp_path):
    pdk_json = {"name": "ics55", "lef": ["tech.lef"]}
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    seen = {}

    def create_workspace(**kwargs):
        pdk_json_path = Path(kwargs["pdk_json"])
        seen["pdk_json"] = json.loads(pdk_json_path.read_text(encoding="utf-8"))
        return _workspace(Path(kwargs["directory"]))

    monkeypatch.setattr("chipcompiler.data.create_workspace", create_workspace)
    api = WorkspaceRuntimeApi()

    api.create_workspace(
        WorkspaceCreateRequest(
            directory=str(ws),
            pdk="ics55",
            pdk_json=pdk_json,
        )
    )

    assert seen["pdk_json"] == pdk_json


def test_open_workspace_loads_without_creating_step_workspaces(monkeypatch, tmp_path):
    capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    api = WorkspaceRuntimeApi()

    result = api.open_workspace(WorkspaceOpenRequest(directory=str(ws)))

    assert result == {
        "workspaceId": result["workspaceId"],
        "directory": str(ws.resolve()),
    }
    assert capture["loaded"] == [str(ws)]
    assert not DummyFlow.instances[0].created


def test_workspace_home_and_info_use_session_id(monkeypatch, tmp_path):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "chipcompiler.tools.get_step_info",
        lambda workspace, step, id: {"path": Path(workspace.directory) / "layout.png"},
    )
    api = WorkspaceRuntimeApi()
    opened = api.open_workspace(WorkspaceOpenRequest(directory=str(ws)))
    workspace_id = opened["workspaceId"]

    home = api.workspace_home(WorkspaceIdRequest(workspace_id=workspace_id))
    info = api.workspace_info(
        WorkspaceInfoRequest(workspace_id=workspace_id, step="Synthesis", info_id="layout")
    )

    assert home == {"path": str(ws.resolve() / "home" / "home.json")}
    assert info == {
        "step": "Synthesis",
        "id": "layout",
        "info": {"path": str(ws.resolve() / "layout.png")},
    }


def test_refresh_sync_and_reset_flow_use_session(monkeypatch, tmp_path):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    refreshed = []
    synced = []
    prepared = []

    monkeypatch.setattr(
        "chipcompiler.data.refresh_workspace_config",
        lambda workspace: refreshed.append(workspace.directory),
    )
    monkeypatch.setattr(
        "chipcompiler.data.sync_workspace_config_to_parameters",
        lambda workspace, path: synced.append((workspace.directory, path)) or True,
    )
    monkeypatch.setattr(
        "chipcompiler.data.prepare_workspace_for_rerun",
        lambda workspace, flow: prepared.append((workspace.directory, flow)),
    )
    config_dir = ws / "config"
    config_dir.mkdir()
    config_path = config_dir / "route.json"
    config_path.write_text("{}")
    api = WorkspaceRuntimeApi()
    workspace_id = api.open_workspace(WorkspaceOpenRequest(directory=str(ws)))["workspaceId"]

    refresh = api.refresh_config(WorkspaceIdRequest(workspace_id=workspace_id))
    sync = api.sync_config(
        WorkspaceSyncConfigRequest(
            workspace_id=workspace_id,
            config_path=str(config_path),
        )
    )
    reset = api.reset_flow(WorkspaceIdRequest(workspace_id=workspace_id))

    assert refresh == {"directory": str(ws.resolve()), "refreshed": True}
    assert sync == {
        "directory": str(ws.resolve()),
        "configPath": str(config_path.resolve()),
        "parametersChanged": True,
        "refreshed": True,
    }
    assert reset == {"directory": str(ws.resolve())}
    assert refreshed == [ws.resolve(), ws.resolve()]
    assert synced == [(ws.resolve(), config_path.resolve())]
    assert prepared == [(ws.resolve(), DummyFlow.instances[-1])]


def test_refresh_config_waits_for_session_mutation_lock(monkeypatch, tmp_path):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    api = WorkspaceRuntimeApi()
    workspace_id = api.open_workspace(WorkspaceOpenRequest(directory=str(ws)))["workspaceId"]
    entered = threading.Event()

    def refresh_config(_workspace):
        entered.set()

    monkeypatch.setattr("chipcompiler.data.refresh_workspace_config", refresh_config)

    _assert_call_waits_for_session_lock(
        api=api,
        workspace_id=workspace_id,
        call=lambda: api.refresh_config(WorkspaceIdRequest(workspace_id=workspace_id)),
        entered=entered,
    )


def test_sync_config_waits_for_session_mutation_lock(monkeypatch, tmp_path):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    config_dir = ws / "config"
    config_dir.mkdir()
    config_path = config_dir / "route.json"
    config_path.write_text("{}")
    api = WorkspaceRuntimeApi()
    workspace_id = api.open_workspace(WorkspaceOpenRequest(directory=str(ws)))["workspaceId"]
    entered = threading.Event()

    def sync_config(_workspace, _path):
        entered.set()
        return False

    monkeypatch.setattr("chipcompiler.data.sync_workspace_config_to_parameters", sync_config)

    _assert_call_waits_for_session_lock(
        api=api,
        workspace_id=workspace_id,
        call=lambda: api.sync_config(
            WorkspaceSyncConfigRequest(
                workspace_id=workspace_id,
                config_path=str(config_path),
            )
        ),
        entered=entered,
    )


def test_reset_flow_waits_for_session_mutation_lock(monkeypatch, tmp_path):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    api = WorkspaceRuntimeApi()
    workspace_id = api.open_workspace(WorkspaceOpenRequest(directory=str(ws)))["workspaceId"]
    entered = threading.Event()

    def build_flow(_workspace):
        entered.set()
        return SimpleNamespace()

    monkeypatch.setattr("chipcompiler.runtime.workspace_api.build_flow_for_workspace", build_flow)
    monkeypatch.setattr("chipcompiler.data.prepare_workspace_for_rerun", lambda _ws, _flow: None)

    _assert_call_waits_for_session_lock(
        api=api,
        workspace_id=workspace_id,
        call=lambda: api.reset_flow(WorkspaceIdRequest(workspace_id=workspace_id)),
        entered=entered,
    )


def test_unknown_session_returns_structured_runtime_error():
    api = WorkspaceRuntimeApi()

    with pytest.raises(RuntimeApiError) as exc_info:
        api.workspace_home(WorkspaceIdRequest(workspace_id="missing"))

    assert exc_info.value.code == "workspace_session_not_found"


def test_runtime_modules_do_not_import_typer_or_click():
    for path in Path("chipcompiler/runtime").glob("*.py"):
        source = path.read_text()
        assert "import typer" not in source
        assert "import click" not in source


def test_flow_run_uses_run_steps_and_prepare_on_rerun(monkeypatch, tmp_path):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    prepared = []
    monkeypatch.setattr(
        "chipcompiler.data.prepare_workspace_for_rerun",
        lambda workspace, flow: prepared.append((workspace.directory, flow)),
    )
    api = WorkspaceRuntimeApi()
    workspace_id = api.open_workspace(WorkspaceOpenRequest(directory=str(ws)))["workspaceId"]

    result = api.flow_run(FlowRunRequest(workspace_id=workspace_id, rerun=True))

    flow = DummyFlow.instances[-1]
    assert result == {"rerun": True}
    assert prepared == [(ws.resolve(), flow)]
    assert flow.run_steps_calls == [True]


def test_flow_run_step_initializes_db_before_direct_step(monkeypatch, tmp_path):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    api = WorkspaceRuntimeApi()
    workspace_id = api.open_workspace(WorkspaceOpenRequest(directory=str(ws)))["workspaceId"]

    result = api.flow_run_step(
        FlowRunStepRequest(workspace_id=workspace_id, step="Synthesis", rerun=False)
    )

    flow = DummyFlow.instances[-1]
    assert result == {"step": "Synthesis", "state": "Success"}
    assert flow.init_db_engine_steps == ["Synthesis"]
    assert flow.call_order == [
        ("init_db_engine",),
        ("run_step", "Synthesis", False),
    ]
    assert flow.run_steps_calls == []


def test_flow_run_step_rerun_refreshes_before_db_init(monkeypatch, tmp_path):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    refreshed = []

    def refresh_config(workspace):
        refreshed.append(workspace.directory)
        DummyFlow.instances[-1].call_order.append(("refresh_config", workspace.directory))

    monkeypatch.setattr("chipcompiler.data.refresh_workspace_config", refresh_config)
    api = WorkspaceRuntimeApi()
    workspace_id = api.open_workspace(WorkspaceOpenRequest(directory=str(ws)))["workspaceId"]

    result = api.flow_run_step(
        FlowRunStepRequest(workspace_id=workspace_id, step="Floorplan", rerun=True)
    )

    flow = DummyFlow.instances[-1]
    assert result == {"step": "Floorplan", "state": "Success"}
    assert refreshed == [ws.resolve()]
    assert flow.call_order == [
        ("refresh_config", ws.resolve()),
        ("init_db_engine",),
        ("run_step", "Floorplan", True),
    ]


def test_flow_run_step_skips_successful_step_without_db_init(monkeypatch, tmp_path):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    DummyFlow.successful_steps = {"Synthesis"}
    api = WorkspaceRuntimeApi()
    workspace_id = api.open_workspace(WorkspaceOpenRequest(directory=str(ws)))["workspaceId"]

    result = api.flow_run_step(
        FlowRunStepRequest(workspace_id=workspace_id, step="Synthesis", rerun=False)
    )

    flow = DummyFlow.instances[-1]
    assert result == {"step": "Synthesis", "state": "Success"}
    assert flow.init_db_engine_calls == 0
    assert flow.call_order == [("run_step", "Synthesis", False)]


def test_flow_run_step_unknown_step_returns_runtime_error(monkeypatch, tmp_path):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    api = WorkspaceRuntimeApi()
    workspace_id = api.open_workspace(WorkspaceOpenRequest(directory=str(ws)))["workspaceId"]

    with pytest.raises(RuntimeApiError) as exc_info:
        api.flow_run_step(
            FlowRunStepRequest(workspace_id=workspace_id, step="Missing", rerun=False)
        )

    assert exc_info.value.code == "command_failed"
    assert "step not found" in exc_info.value.message
