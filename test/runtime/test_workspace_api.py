import json
import queue
import threading
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from chipcompiler.data import StateEnum
from chipcompiler.data.workspace.layout import EccOutput
from chipcompiler.runtime.requests import (
    CandidateBindInputRequest,
    CandidateMaterializeRequest,
    CandidateRerunRequest,
    DbEnsureRequest,
    DbReleaseRequest,
    FlowRunRequest,
    FlowRunStepRequest,
    WorkspaceCreateRequest,
    WorkspaceExtractFoundationRequest,
    WorkspaceIdRequest,
    WorkspaceInfoRequest,
    WorkspaceOpenRequest,
    WorkspaceSyncConfigRequest,
)
from chipcompiler.runtime.sessions import WorkspaceSessionRegistry
from chipcompiler.runtime.workspace_api import RuntimeApiError, WorkspaceRuntimeApi


class DummyEngineDB:
    def __init__(self, flow):
        self.flow = flow
        self.initialized = False
        self.close_calls = 0

    def has_init(self):
        return self.initialized

    def create_db_engine(self, step):
        self.flow.init_db_engine_calls += 1
        self.flow.init_db_engine_steps.append(None if step is None else step.name)
        self.flow.init_db_engine_inputs.append(
            (
                None if step is None else getattr(step, "input_def", ""),
                None if step is None else getattr(step, "input_verilog", ""),
            )
        )
        self.flow.call_order.append(("init_db_engine",))
        self.initialized = self.flow.next_init_success
        return self.initialized

    def close(self):
        if not self.initialized:
            return
        self.close_calls += 1
        self.initialized = False


class DummyFlow:
    instances = []
    next_run_states = []
    next_init_success = True
    successful_steps = set()
    workspace_step_specs = None

    def __init__(self, workspace):
        self.workspace = workspace
        self.added_steps = []
        self.created = False
        self.prepared_for_rerun = False
        self.run_steps_calls = []
        self.run_calls = []
        self.flow_init_db_engine_calls = 0
        self.init_db_engine_calls = 0
        self.init_db_engine_steps = []
        self.init_db_engine_inputs = []
        self.call_order = []
        specs = self.workspace_step_specs or (
            {"name": "Synthesis", "tool": "yosys"},
            {"name": "Floorplan", "tool": "ecc"},
        )
        self.workspace_steps = [SimpleNamespace(**spec) for spec in specs]
        self.completed_steps = set()
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

    def run_steps(self, *, rerun=False):
        self.run_steps_calls.append(rerun)
        success = True
        for workspace_step in self.workspace_steps:
            self.init_db_engine()
            state = self.run_step(workspace_step, rerun=rerun)
            if state != StateEnum.Success:
                success = False
                break
        return success

    def init_db_engine(self):
        self.flow_init_db_engine_calls += 1
        self.call_order.append(("flow_init_db_engine",))
        if self.engine_db is None:
            self.engine_db = DummyEngineDB(self)
        workspace_step = self.workspace_steps[0]
        for candidate in self.workspace_steps:
            if candidate.name not in self.completed_steps:
                workspace_step = candidate
                break
        return self.engine_db.create_db_engine(workspace_step)

    def run_step(self, workspace_step, *, rerun=False):
        name = workspace_step if isinstance(workspace_step, str) else workspace_step.name
        self.run_calls.append((name, rerun))
        self.call_order.append(("run_step", name, rerun))
        state = DummyFlow.next_run_states.pop(0) if DummyFlow.next_run_states else StateEnum.Success
        if state == StateEnum.Success:
            self.completed_steps.add(name)
            workspace_step_object = self.get_workspace_step(name)
            if getattr(workspace_step_object, "tool", "") == "sizer":
                if self.engine_db is not None:
                    self.engine_db.close()
                self.engine_db = None
        return state

    def get_workspace_step(self, name):
        for step in self.workspace_steps:
            if step.name == name:
                return step
        return None

    def get_step(self, name, tool):
        for step in self.workspace.flow.data.get("steps", []):
            if step.get("name") == name and step.get("tool") == tool:
                return step
        return None

    def save(self):
        return True

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


def _install_runtime_mocks(monkeypatch, tmp_path, *, create_workspace_files=True):
    capture = {
        "create_kwargs": None,
        "input_filelist_lines": [],
        "loaded": [],
        "workspace_entries_when_create_called": [],
    }
    DummyFlow.instances = []
    DummyFlow.next_run_states = []
    DummyFlow.next_init_success = True
    DummyFlow.successful_steps = set()
    DummyFlow.workspace_step_specs = None

    def fake_create_workspace(**kwargs):
        capture["create_kwargs"] = kwargs
        input_filelist = kwargs.get("input_filelist")
        if input_filelist and Path(input_filelist).exists():
            capture["input_filelist_lines"] = (
                Path(input_filelist).read_text(encoding="utf-8").splitlines()
            )
        workspace_dir = Path(kwargs["directory"])
        if workspace_dir.is_dir():
            capture["workspace_entries_when_create_called"] = sorted(
                path.name for path in workspace_dir.iterdir()
            )
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
    if create_workspace_files:
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
            sdc="/constraints/top.sdc",
        )
    )

    assert set(result) == {"workspaceId", "directory"}
    assert result["directory"] == str(ws.resolve())
    assert result["workspaceId"].startswith("workspace-")
    assert isinstance(capture["create_kwargs"]["pdk_json"], str)
    assert capture["create_kwargs"]["sdc"] == "/constraints/top.sdc"
    assert DummyFlow.instances[0].created
    assert api.sessions.get_session(result["workspaceId"]).directory == ws.resolve()


def test_candidate_runtime_methods_bind_existing_workspace_artifacts(monkeypatch, tmp_path):
    _capture, workspace_dir = _install_runtime_mocks(monkeypatch, tmp_path)
    api = WorkspaceRuntimeApi()
    created = api.create_workspace(WorkspaceCreateRequest(directory=str(workspace_dir)))
    calls = []

    monkeypatch.setattr(
        "chipcompiler.data.export_candidate_capabilities",
        lambda workspace: calls.append(("export", workspace.directory))
        or {"registry_sha256": "registry"},
    )
    monkeypatch.setattr(
        "chipcompiler.data.bind_candidate_input",
        lambda workspace, flow, target, source, candidate: calls.append(
            ("bind", workspace.directory, flow, target, source, candidate)
        )
        or {"receipt_sha256": "input"},
    )
    monkeypatch.setattr(
        "chipcompiler.data.materialize_candidate_config",
        lambda workspace, target, patch, candidate: calls.append(
            ("materialize", workspace.directory, target, patch, candidate)
        )
        or {"receipt_sha256": "materialization"},
    )

    capabilities = api.export_candidate_capabilities(WorkspaceIdRequest(created["workspaceId"]))
    binding = api.bind_candidate_input(
        CandidateBindInputRequest(
            workspace_id=created["workspaceId"],
            target_step="place",
            source_step="fixFanout",
            candidate_id="candidate_0001",
        )
    )
    materialization = api.materialize_candidate(
        CandidateMaterializeRequest(
            workspace_id=created["workspaceId"],
            target_step="place",
            candidate_id="candidate_0001",
            patch=[{"knob_id": "place.target_density", "value": 0.6}],
        )
    )

    assert capabilities == {"registry_sha256": "registry"}
    assert binding == {"receipt_sha256": "input"}
    assert materialization == {"receipt_sha256": "materialization"}
    assert [call[0] for call in calls] == ["export", "bind", "materialize"]


def test_create_workspace_forwards_dynamic_flow_config(monkeypatch, tmp_path):
    capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    flow_config = {
        "start_step": "Synthesis",
        "end_step": "Harden",
        "steps": ["Synthesis", "RCX", "sta", "Harden"],
    }

    WorkspaceRuntimeApi().create_workspace(
        WorkspaceCreateRequest(directory=str(ws), flow_config=flow_config)
    )

    assert capture["create_kwargs"]["flow_config"] == flow_config


def test_create_workspace_writes_rtl_list_filelist_outside_workspace(
    monkeypatch,
    tmp_path,
):
    capture, ws = _install_runtime_mocks(
        monkeypatch,
        tmp_path,
        create_workspace_files=False,
    )
    project = tmp_path / "project"
    project.mkdir()
    rtl_paths = [str(project / "a.v"), str(project / "b.v")]
    api = WorkspaceRuntimeApi()

    api.create_workspace(
        WorkspaceCreateRequest(
            directory=str(ws),
            pdk="ics55",
            parameters={"Design": "gcd"},
            rtl_list=rtl_paths,
        )
    )

    input_filelist = Path(capture["create_kwargs"]["input_filelist"])
    assert input_filelist.name == "filelist"
    assert not input_filelist.is_relative_to(ws)
    assert capture["input_filelist_lines"] == rtl_paths
    assert capture["workspace_entries_when_create_called"] == []
    assert not (ws / "filelist").exists()


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


def test_create_workspace_with_inline_pdk_json_uses_real_data_api(monkeypatch, tmp_path):
    pdk_root = tmp_path / "pdk"
    tech = pdk_root / "tech.lef"
    lef = pdk_root / "stdcell.lef"
    liberty = pdk_root / "stdcell.lib"
    for path in (tech, lef, liberty):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("VERSION 5.8 ;\n")

    workspace_dir = tmp_path / "workspace"
    monkeypatch.setattr(
        "chipcompiler.runtime.workspace_api.build_flow_for_workspace",
        lambda _workspace: SimpleNamespace(),
    )

    api = WorkspaceRuntimeApi()
    result = api.create_workspace(
        WorkspaceCreateRequest(
            directory=str(workspace_dir),
            pdk="ics55",
            pdk_json={
                "name": "ics55",
                "root": str(pdk_root),
                "tech": str(tech),
                "lefs": [str(lef)],
                "libs": [str(liberty)],
            },
            parameters={
                "Design": "gcd",
                "Top module": "gcd",
                "Clock": "clk",
            },
        )
    )

    assert result["directory"] == str(workspace_dir.resolve())
    pdk_config_path = workspace_dir / "home" / "pdk.json"
    assert pdk_config_path.is_file()
    parameters = json.loads((workspace_dir / "home" / "parameters.json").read_text())
    assert parameters["PDK Config"] == str(pdk_config_path.resolve())
    assert api.sessions.get_session(result["workspaceId"]).directory == workspace_dir.resolve()


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


def test_create_workspace_replaces_existing_same_directory_session(monkeypatch, tmp_path):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    api = WorkspaceRuntimeApi()

    opened = api.open_workspace(WorkspaceOpenRequest(directory=str(ws)))
    opened_session = api.sessions.get_session(opened["workspaceId"])
    opened_session.db_handle = object()
    created = api.create_workspace(WorkspaceCreateRequest(directory=str(ws)))

    assert created["workspaceId"] != opened["workspaceId"]
    assert opened_session.db_handle is None
    with pytest.raises(RuntimeApiError, match="workspace session not found"):
        api.workspace_home(WorkspaceIdRequest(workspace_id=opened["workspaceId"]))
    created_session = api.sessions.get_session(created["workspaceId"])
    assert created_session.workspace is not opened_session.workspace


def test_open_workspace_reuses_existing_same_directory_session(monkeypatch, tmp_path):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    api = WorkspaceRuntimeApi()

    first = api.open_workspace(WorkspaceOpenRequest(directory=str(ws)))
    first_session = api.sessions.get_session(first["workspaceId"])
    second = api.open_workspace(WorkspaceOpenRequest(directory=str(ws)))

    assert second["workspaceId"] == first["workspaceId"]
    assert api.sessions.get_session(second["workspaceId"]).workspace is first_session.workspace


def test_extract_foundation_returns_manifest_receipt(monkeypatch, tmp_path):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    captured = {}

    class FakeExtractor:
        def __init__(self, directory, *, profile):
            captured["directory"] = directory
            captured["profile"] = profile

        def extract(self, **kwargs):
            captured["kwargs"] = kwargs
            manifest = ws / "foundation_data/ecc/manifest.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(
                '{"contract_name":"foundation_data/ecc","schema_version":"v1"}',
                encoding="utf-8",
            )

    monkeypatch.setattr("chipcompiler.data.foundation.FoundationExtractor", FakeExtractor)
    api = WorkspaceRuntimeApi()
    workspace_id = api.open_workspace(WorkspaceOpenRequest(directory=str(ws)))["workspaceId"]

    result = api.extract_foundation(WorkspaceExtractFoundationRequest(workspace_id=workspace_id))

    assert result == {
        "manifestRef": "foundation_data/ecc/manifest.json",
        "manifestSha256": sha256(
            b'{"contract_name":"foundation_data/ecc","schema_version":"v1"}'
        ).hexdigest(),
        "contractName": "foundation_data/ecc",
        "schemaVersion": "v1",
    }
    assert captured == {
        "directory": str(ws.resolve()),
        "profile": "iccd_full_v1",
        "kwargs": {
            "include_raw_refs": False,
            "materialize_audit_tables": True,
            "route_detail_level": "full",
        },
    }


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


def test_refresh_config_releases_active_session_db(monkeypatch, tmp_path):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    api = WorkspaceRuntimeApi(persistent_db_enabled=True)
    workspace_id = api.open_workspace(WorkspaceOpenRequest(directory=str(ws)))["workspaceId"]
    api.db_ensure(DbEnsureRequest(workspace_id=workspace_id, step="Floorplan"))
    db_handle = api.sessions.get_session(workspace_id).db_handle

    result = api.refresh_config(WorkspaceIdRequest(workspace_id=workspace_id))

    assert result == {"directory": str(ws.resolve()), "refreshed": True}
    assert db_handle.close_calls == 1
    assert api.sessions.get_session(workspace_id).db_handle is None


def test_sync_config_releases_active_session_db_only_when_parameters_change(
    monkeypatch,
    tmp_path,
):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    config_dir = ws / "config"
    config_dir.mkdir()
    config_path = config_dir / "route.json"
    config_path.write_text("{}")
    changed = [False, True]

    monkeypatch.setattr(
        "chipcompiler.data.sync_workspace_config_to_parameters",
        lambda _workspace, _path: changed.pop(0),
    )
    api = WorkspaceRuntimeApi(persistent_db_enabled=True)
    workspace_id = api.open_workspace(WorkspaceOpenRequest(directory=str(ws)))["workspaceId"]
    api.db_ensure(DbEnsureRequest(workspace_id=workspace_id, step="Floorplan"))
    db_handle = api.sessions.get_session(workspace_id).db_handle

    unchanged = api.sync_config(
        WorkspaceSyncConfigRequest(workspace_id=workspace_id, config_path=str(config_path))
    )
    assert unchanged["parametersChanged"] is False
    assert unchanged["refreshed"] is False
    assert db_handle.close_calls == 0

    changed_result = api.sync_config(
        WorkspaceSyncConfigRequest(workspace_id=workspace_id, config_path=str(config_path))
    )

    assert changed_result["parametersChanged"] is True
    assert changed_result["refreshed"] is True
    assert db_handle.close_calls == 1
    assert api.sessions.get_session(workspace_id).db_handle is None


def test_reset_flow_releases_active_session_db_before_prepare(monkeypatch, tmp_path):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    prepared = []

    def prepare(workspace, flow):
        prepared.append((workspace.directory, flow))
        assert api.sessions.get_session(workspace_id).db_handle is None

    monkeypatch.setattr("chipcompiler.data.prepare_workspace_for_rerun", prepare)
    api = WorkspaceRuntimeApi(persistent_db_enabled=True)
    workspace_id = api.open_workspace(WorkspaceOpenRequest(directory=str(ws)))["workspaceId"]
    api.db_ensure(DbEnsureRequest(workspace_id=workspace_id, step="Floorplan"))
    db_handle = api.sessions.get_session(workspace_id).db_handle

    result = api.reset_flow(WorkspaceIdRequest(workspace_id=workspace_id))

    assert result == {"directory": str(ws.resolve())}
    assert db_handle.close_calls == 1
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


def test_db_ensure_rejects_disabled_runtime_api(monkeypatch, tmp_path):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    api = WorkspaceRuntimeApi()
    workspace_id = api.open_workspace(WorkspaceOpenRequest(directory=str(ws)))["workspaceId"]

    with pytest.raises(RuntimeApiError) as exc_info:
        api.db_ensure(DbEnsureRequest(workspace_id=workspace_id))

    assert exc_info.value.code == "command_failed"
    assert exc_info.value.message == "persistent_db_disabled"


def test_db_ensure_initializes_requested_step_and_stores_session_db(monkeypatch, tmp_path):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    api = WorkspaceRuntimeApi(persistent_db_enabled=True)
    workspace_id = api.open_workspace(WorkspaceOpenRequest(directory=str(ws)))["workspaceId"]

    result = api.db_ensure(DbEnsureRequest(workspace_id=workspace_id, step="Floorplan"))

    flow = DummyFlow.instances[-1]
    session = api.sessions.get_session(workspace_id)
    assert result == {
        "workspaceId": workspace_id,
        "enabled": True,
        "active": True,
        "reused": False,
        "step": "Floorplan",
    }
    assert flow.init_db_engine_steps == ["Floorplan"]
    assert session.db_handle is flow.engine_db
    assert session.db_handle.has_init()


def test_db_ensure_without_step_uses_flow_selection_rule(monkeypatch, tmp_path):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    api = WorkspaceRuntimeApi(persistent_db_enabled=True)
    workspace_id = api.open_workspace(WorkspaceOpenRequest(directory=str(ws)))["workspaceId"]

    result = api.db_ensure(DbEnsureRequest(workspace_id=workspace_id))

    flow = DummyFlow.instances[-1]
    assert result == {
        "workspaceId": workspace_id,
        "enabled": True,
        "active": True,
        "reused": False,
        "step": "",
    }
    assert flow.flow_init_db_engine_calls == 1
    assert flow.init_db_engine_steps == ["Synthesis"]
    assert api.sessions.get_session(workspace_id).db_handle is flow.engine_db


def test_db_ensure_reuses_initialized_session_db(monkeypatch, tmp_path):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    api = WorkspaceRuntimeApi(persistent_db_enabled=True)
    workspace_id = api.open_workspace(WorkspaceOpenRequest(directory=str(ws)))["workspaceId"]
    first = api.db_ensure(DbEnsureRequest(workspace_id=workspace_id, step="Floorplan"))
    db_handle = api.sessions.get_session(workspace_id).db_handle

    second = api.db_ensure(DbEnsureRequest(workspace_id=workspace_id, step="Floorplan"))

    assert first["reused"] is False
    assert second == {
        "workspaceId": workspace_id,
        "enabled": True,
        "active": True,
        "reused": True,
        "step": "Floorplan",
    }
    assert api.sessions.get_session(workspace_id).db_handle is db_handle


def test_db_ensure_unknown_step_returns_runtime_error(monkeypatch, tmp_path):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    api = WorkspaceRuntimeApi(persistent_db_enabled=True)
    workspace_id = api.open_workspace(WorkspaceOpenRequest(directory=str(ws)))["workspaceId"]

    with pytest.raises(RuntimeApiError) as exc_info:
        api.db_ensure(DbEnsureRequest(workspace_id=workspace_id, step="Missing"))

    assert exc_info.value.code == "command_failed"
    assert exc_info.value.message == "step not found: Missing"
    assert api.sessions.get_session(workspace_id).db_handle is None


def test_db_ensure_does_not_store_uninitialized_db(monkeypatch, tmp_path):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    DummyFlow.next_init_success = False
    api = WorkspaceRuntimeApi(persistent_db_enabled=True)
    workspace_id = api.open_workspace(WorkspaceOpenRequest(directory=str(ws)))["workspaceId"]

    result = api.db_ensure(DbEnsureRequest(workspace_id=workspace_id, step="Floorplan"))

    assert result == {
        "workspaceId": workspace_id,
        "enabled": True,
        "active": False,
        "reused": False,
        "step": "Floorplan",
    }
    assert api.sessions.get_session(workspace_id).db_handle is None


def test_db_release_closes_and_clears_active_session_db(monkeypatch, tmp_path):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    api = WorkspaceRuntimeApi(persistent_db_enabled=True)
    workspace_id = api.open_workspace(WorkspaceOpenRequest(directory=str(ws)))["workspaceId"]
    api.db_ensure(DbEnsureRequest(workspace_id=workspace_id, step="Floorplan"))
    db_handle = api.sessions.get_session(workspace_id).db_handle

    result = api.db_release(DbReleaseRequest(workspace_id=workspace_id))

    assert result == {"workspaceId": workspace_id, "released": True}
    assert db_handle.close_calls == 1
    assert api.sessions.get_session(workspace_id).db_handle is None


def test_db_release_is_idempotent_when_no_db_is_active(monkeypatch, tmp_path):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    api = WorkspaceRuntimeApi(persistent_db_enabled=True)
    workspace_id = api.open_workspace(WorkspaceOpenRequest(directory=str(ws)))["workspaceId"]

    result = api.db_release(DbReleaseRequest(workspace_id=workspace_id))

    assert result == {"workspaceId": workspace_id, "released": False}


def test_db_release_closes_db_with_injected_session_registry(monkeypatch, tmp_path):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    api = WorkspaceRuntimeApi(
        sessions=WorkspaceSessionRegistry(),
        persistent_db_enabled=True,
    )
    workspace_id = api.open_workspace(WorkspaceOpenRequest(directory=str(ws)))["workspaceId"]
    api.db_ensure(DbEnsureRequest(workspace_id=workspace_id, step="Floorplan"))
    db_handle = api.sessions.get_session(workspace_id).db_handle

    result = api.db_release(DbReleaseRequest(workspace_id=workspace_id))

    assert result == {"workspaceId": workspace_id, "released": True}
    assert db_handle.close_calls == 1
    assert api.sessions.get_session(workspace_id).db_handle is None


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


def test_flow_run_without_active_session_db_closes_transient_db(
    monkeypatch,
    tmp_path,
):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    api = WorkspaceRuntimeApi(persistent_db_enabled=True)
    workspace_id = api.open_workspace(WorkspaceOpenRequest(directory=str(ws)))["workspaceId"]

    result = api.flow_run(FlowRunRequest(workspace_id=workspace_id, rerun=False))

    flow = DummyFlow.instances[-1]
    assert result == {"rerun": False}
    assert not flow.engine_db.has_init()
    assert flow.engine_db.close_calls == 1
    assert api.sessions.get_session(workspace_id).db_handle is None


def test_flow_run_with_active_session_db_injects_and_captures_final_db(
    monkeypatch,
    tmp_path,
):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    api = WorkspaceRuntimeApi(persistent_db_enabled=True)
    workspace_id = api.open_workspace(WorkspaceOpenRequest(directory=str(ws)))["workspaceId"]
    api.db_ensure(DbEnsureRequest(workspace_id=workspace_id, step="Floorplan"))
    db_handle = api.sessions.get_session(workspace_id).db_handle

    result = api.flow_run(FlowRunRequest(workspace_id=workspace_id, rerun=False))

    flow = DummyFlow.instances[-1]
    assert result == {"rerun": False}
    assert flow.engine_db is db_handle
    assert api.sessions.get_session(workspace_id).db_handle is db_handle
    assert db_handle.close_calls == 0


def test_flow_run_rerun_releases_stale_db_and_captures_new_db(monkeypatch, tmp_path):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    prepared = []

    def prepare(workspace, flow):
        prepared.append((workspace.directory, flow))
        assert api.sessions.get_session(workspace_id).db_handle is None

    monkeypatch.setattr("chipcompiler.data.prepare_workspace_for_rerun", prepare)
    api = WorkspaceRuntimeApi(persistent_db_enabled=True)
    workspace_id = api.open_workspace(WorkspaceOpenRequest(directory=str(ws)))["workspaceId"]
    api.db_ensure(DbEnsureRequest(workspace_id=workspace_id, step="Floorplan"))
    stale_db = api.sessions.get_session(workspace_id).db_handle

    result = api.flow_run(FlowRunRequest(workspace_id=workspace_id, rerun=True))

    flow = DummyFlow.instances[-1]
    assert result == {"rerun": True}
    assert stale_db.close_calls == 1
    assert prepared == [(ws.resolve(), flow)]
    assert api.sessions.get_session(workspace_id).db_handle is flow.engine_db
    assert flow.engine_db is not stale_db
    assert flow.engine_db.has_init()


def test_flow_run_sizer_boundary_captures_post_sizer_db(monkeypatch, tmp_path):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    sizer_def = str(ws / "Timing optimization_sizer" / "output" / "sizer.def")
    sizer_verilog = str(ws / "Timing optimization_sizer" / "output" / "sizer.v")
    DummyFlow.workspace_step_specs = (
        {"name": "Floorplan", "tool": "ecc", "input_def": "origin.def"},
        {
            "name": "Timing optimization",
            "tool": "sizer",
            "input_def": "floorplan.def",
            "input_verilog": "floorplan.v",
            "output": {"def": sizer_def, "verilog": sizer_verilog},
        },
        {
            "name": "Legalization",
            "tool": "ecc",
            "input_def": sizer_def,
            "input_verilog": sizer_verilog,
        },
    )
    api = WorkspaceRuntimeApi(persistent_db_enabled=True)
    workspace_id = api.open_workspace(WorkspaceOpenRequest(directory=str(ws)))["workspaceId"]
    api.db_ensure(DbEnsureRequest(workspace_id=workspace_id, step="Floorplan"))
    pre_sizer_db = api.sessions.get_session(workspace_id).db_handle

    result = api.flow_run(FlowRunRequest(workspace_id=workspace_id, rerun=False))

    flow = DummyFlow.instances[-1]
    post_sizer_db = api.sessions.get_session(workspace_id).db_handle
    assert result == {"rerun": False}
    assert pre_sizer_db.close_calls == 1
    assert post_sizer_db is flow.engine_db
    assert post_sizer_db is not pre_sizer_db
    assert post_sizer_db.has_init()
    assert flow.init_db_engine_steps[-1] == "Legalization"
    assert flow.init_db_engine_inputs[-1] == (sizer_def, sizer_verilog)


def test_flow_run_sizer_boundary_failure_captures_post_sizer_db(
    monkeypatch,
    tmp_path,
):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    sizer_def = str(ws / "Timing optimization_sizer" / "output" / "sizer.def")
    sizer_verilog = str(ws / "Timing optimization_sizer" / "output" / "sizer.v")
    DummyFlow.workspace_step_specs = (
        {"name": "Floorplan", "tool": "ecc", "input_def": "origin.def"},
        {
            "name": "Timing optimization",
            "tool": "sizer",
            "input_def": "floorplan.def",
            "input_verilog": "floorplan.v",
            "output": {"def": sizer_def, "verilog": sizer_verilog},
        },
        {
            "name": "Legalization",
            "tool": "ecc",
            "input_def": sizer_def,
            "input_verilog": sizer_verilog,
        },
    )
    DummyFlow.next_run_states = [
        StateEnum.Success,
        StateEnum.Success,
        StateEnum.Imcomplete,
    ]
    api = WorkspaceRuntimeApi(persistent_db_enabled=True)
    workspace_id = api.open_workspace(WorkspaceOpenRequest(directory=str(ws)))["workspaceId"]
    api.db_ensure(DbEnsureRequest(workspace_id=workspace_id, step="Floorplan"))
    pre_sizer_db = api.sessions.get_session(workspace_id).db_handle

    with pytest.raises(RuntimeApiError) as exc_info:
        api.flow_run(FlowRunRequest(workspace_id=workspace_id, rerun=False))

    flow = DummyFlow.instances[-1]
    post_sizer_db = api.sessions.get_session(workspace_id).db_handle
    assert exc_info.value.code == "command_failed"
    assert pre_sizer_db.close_calls == 1
    assert post_sizer_db is flow.engine_db
    assert post_sizer_db is not pre_sizer_db
    assert post_sizer_db.has_init()
    assert flow.init_db_engine_steps[-1] == "Legalization"


def test_flow_run_sizer_boundary_exception_captures_post_sizer_db(
    monkeypatch,
    tmp_path,
):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    DummyFlow.workspace_step_specs = (
        {"name": "Floorplan", "tool": "ecc"},
        {"name": "Timing optimization", "tool": "sizer"},
        {"name": "Legalization", "tool": "ecc"},
    )

    def run_steps_raises_after_post_sizer_db(self, *, rerun=False):
        del rerun
        self.engine_db.close()
        self.engine_db = DummyEngineDB(self)
        self.engine_db.create_db_engine(self.workspace_steps[-1])
        raise ValueError("post-sizer failure")

    monkeypatch.setattr(DummyFlow, "run_steps", run_steps_raises_after_post_sizer_db)
    api = WorkspaceRuntimeApi(persistent_db_enabled=True)
    workspace_id = api.open_workspace(WorkspaceOpenRequest(directory=str(ws)))["workspaceId"]
    api.db_ensure(DbEnsureRequest(workspace_id=workspace_id, step="Floorplan"))
    pre_sizer_db = api.sessions.get_session(workspace_id).db_handle

    with pytest.raises(ValueError, match="post-sizer failure"):
        api.flow_run(FlowRunRequest(workspace_id=workspace_id, rerun=False))

    flow = DummyFlow.instances[-1]
    post_sizer_db = api.sessions.get_session(workspace_id).db_handle
    assert pre_sizer_db.close_calls == 1
    assert post_sizer_db is flow.engine_db
    assert post_sizer_db is not pre_sizer_db
    assert post_sizer_db.has_init()


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
    assert not flow.engine_db.has_init()
    assert flow.engine_db.close_calls == 1
    assert api.sessions.get_session(workspace_id).db_handle is None


def test_flow_run_step_with_active_session_db_injects_and_captures_final_db(
    monkeypatch,
    tmp_path,
):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    api = WorkspaceRuntimeApi(persistent_db_enabled=True)
    workspace_id = api.open_workspace(WorkspaceOpenRequest(directory=str(ws)))["workspaceId"]
    api.db_ensure(DbEnsureRequest(workspace_id=workspace_id, step="Floorplan"))
    db_handle = api.sessions.get_session(workspace_id).db_handle

    result = api.flow_run_step(
        FlowRunStepRequest(workspace_id=workspace_id, step="Floorplan", rerun=False)
    )

    flow = DummyFlow.instances[-1]
    assert result == {"step": "Floorplan", "state": "Success"}
    assert flow.engine_db is db_handle
    assert api.sessions.get_session(workspace_id).db_handle is db_handle
    assert db_handle.close_calls == 0


def test_flow_run_step_successful_sizer_releases_active_session_db(
    monkeypatch,
    tmp_path,
):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    DummyFlow.workspace_step_specs = (
        {"name": "Floorplan", "tool": "ecc"},
        {"name": "Timing optimization", "tool": "sizer"},
    )
    api = WorkspaceRuntimeApi(persistent_db_enabled=True)
    workspace_id = api.open_workspace(WorkspaceOpenRequest(directory=str(ws)))["workspaceId"]
    api.db_ensure(DbEnsureRequest(workspace_id=workspace_id, step="Floorplan"))
    pre_sizer_db = api.sessions.get_session(workspace_id).db_handle

    result = api.flow_run_step(
        FlowRunStepRequest(
            workspace_id=workspace_id,
            step="Timing optimization",
            rerun=False,
        )
    )

    flow = DummyFlow.instances[-1]
    assert result == {"step": "Timing optimization", "state": "Success"}
    assert flow.engine_db is None
    assert pre_sizer_db.close_calls == 1
    assert api.sessions.get_session(workspace_id).db_handle is None


def test_flow_run_step_sizer_exception_clears_closed_session_db(
    monkeypatch,
    tmp_path,
):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    DummyFlow.workspace_step_specs = (
        {"name": "Floorplan", "tool": "ecc"},
        {"name": "Timing optimization", "tool": "sizer"},
    )

    def run_step_raises_after_sizer_boundary(self, workspace_step, *, rerun=False):
        del workspace_step, rerun
        self.engine_db.close()
        self.engine_db = None
        raise ValueError("sizer failure")

    monkeypatch.setattr(DummyFlow, "run_step", run_step_raises_after_sizer_boundary)
    api = WorkspaceRuntimeApi(persistent_db_enabled=True)
    workspace_id = api.open_workspace(WorkspaceOpenRequest(directory=str(ws)))["workspaceId"]
    api.db_ensure(DbEnsureRequest(workspace_id=workspace_id, step="Floorplan"))
    pre_sizer_db = api.sessions.get_session(workspace_id).db_handle

    with pytest.raises(ValueError, match="sizer failure"):
        api.flow_run_step(
            FlowRunStepRequest(
                workspace_id=workspace_id,
                step="Timing optimization",
                rerun=False,
            )
        )

    assert pre_sizer_db.close_calls == 1
    assert api.sessions.get_session(workspace_id).db_handle is None


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


def test_flow_run_step_rerun_verifies_and_reapplies_candidate_input(monkeypatch, tmp_path):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    candidate_calls = []

    monkeypatch.setattr(
        "chipcompiler.data.validate_candidate_step_contract",
        lambda workspace, step: candidate_calls.append(("validate", workspace.directory, step))
        or "gcd-rerun-place",
    )
    monkeypatch.setattr(
        "chipcompiler.data.reapply_candidate_input_binding",
        lambda workspace, flow, step: candidate_calls.append(
            ("reapply", workspace.directory, flow, step)
        ),
    )
    api = WorkspaceRuntimeApi()
    workspace_id = api.open_workspace(WorkspaceOpenRequest(directory=str(ws)))["workspaceId"]

    result = api.flow_run_step(
        FlowRunStepRequest(workspace_id=workspace_id, step="Floorplan", rerun=True)
    )

    flow = DummyFlow.instances[-1]
    assert result == {"step": "Floorplan", "state": "Success"}
    assert candidate_calls == [
        ("validate", ws.resolve(), "Floorplan"),
        ("reapply", ws.resolve(), flow, "Floorplan"),
    ]


def test_flow_run_step_rejects_an_invalid_candidate_before_tool_execution(monkeypatch, tmp_path):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)

    def reject_candidate(*_args):
        raise ValueError("candidate receipt mismatch")

    monkeypatch.setattr(
        "chipcompiler.data.validate_candidate_step_contract",
        reject_candidate,
    )
    api = WorkspaceRuntimeApi()
    workspace_id = api.open_workspace(WorkspaceOpenRequest(directory=str(ws)))["workspaceId"]

    with pytest.raises(RuntimeApiError, match="candidate receipt mismatch"):
        api.flow_run_step(
            FlowRunStepRequest(workspace_id=workspace_id, step="Floorplan", rerun=True)
        )

    assert DummyFlow.instances[-1].run_calls == []


@pytest.mark.parametrize(
    ("execution_scope", "end_step", "expected_run_calls", "cleared_steps"),
    [
        ("single_step", "place", [("place", True)], ("place",)),
        ("full_flow", "CTS", [("place", True), ("CTS", True)], ("place", "CTS")),
    ],
)
def test_candidate_rerun_rebuilds_the_requested_scope(
    monkeypatch,
    tmp_path,
    execution_scope,
    end_step,
    expected_run_calls,
    cleared_steps,
):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    DummyFlow.workspace_step_specs = (
        {"name": "fixFanout", "tool": "ecc", "output": {"dir": ws / "fixFanout_ecc/output"}},
        {
            "name": "place",
            "tool": "dreamplace",
            "output": EccOutput(dir=ws / "place_dreamplace/output"),
            "analysis": {"dir": ws / "place_dreamplace/analysis"},
        },
        {
            "name": "CTS",
            "tool": "ecc",
            "output": {"dir": ws / "CTS_ecc/output"},
            "analysis": {"dir": ws / "CTS_ecc/analysis"},
        },
        {
            "name": "legalization",
            "tool": "dreamplace",
            "output": {"dir": ws / "legalization_dreamplace/output"},
            "analysis": {"dir": ws / "legalization_dreamplace/analysis"},
        },
    )
    for path in (
        ws / "place_dreamplace/output",
        ws / "CTS_ecc/output",
        ws / "place_dreamplace/analysis",
        ws / "CTS_ecc/analysis",
        ws / "legalization_dreamplace/output",
        ws / "legalization_dreamplace/analysis",
    ):
        path.mkdir(parents=True)
        (path / "stale").write_text("stale")
    calls = []
    monkeypatch.setattr(
        "chipcompiler.data.bind_candidate_input",
        lambda workspace, flow, target, source, candidate: calls.append(
            ("bind", target, source, candidate)
        )
        or {},
    )
    monkeypatch.setattr(
        "chipcompiler.data.materialize_candidate_config",
        lambda workspace, target, patch, candidate: calls.append(
            ("materialize", target, patch, candidate)
        )
        or {},
    )
    monkeypatch.setattr(
        "chipcompiler.data.validate_candidate_step_contract",
        lambda _workspace, _target: "gcd-rerun-place",
    )
    monkeypatch.setattr(
        "chipcompiler.data.reapply_candidate_input_binding",
        lambda _workspace, _flow, target: calls.append(("reapply", target)) or {},
    )
    api = WorkspaceRuntimeApi()
    workspace_id = api.open_workspace(WorkspaceOpenRequest(directory=str(ws)))["workspaceId"]
    session = api.sessions.get_session(workspace_id)
    session.workspace.flow.data = {
        "steps": [
            {"name": "fixFanout", "tool": "ecc", "state": "Success"},
            {"name": "place", "tool": "dreamplace", "state": "Success"},
            {"name": "CTS", "tool": "ecc", "state": "Success"},
        ]
    }

    result = api.candidate_rerun(
        CandidateRerunRequest(
            workspace_id=workspace_id,
            candidate_id="gcd-rerun-place",
            target_step="place",
            end_step=end_step,
            patch=[{"knob_id": "place.target_density", "value": 0.55}],
            execution_scope=execution_scope,
        )
    )

    assert result == {
        "end_step": end_step,
        "execution_scope": execution_scope,
        "target_step": "place",
    }
    assert calls == [
        ("bind", "place", "fixFanout", "gcd-rerun-place"),
        (
            "materialize",
            "place",
            [{"knob_id": "place.target_density", "value": 0.55}],
            "gcd-rerun-place",
        ),
        ("reapply", "place"),
    ]
    assert DummyFlow.instances[-1].run_calls == expected_run_calls
    directories = {
        "place": (ws / "place_dreamplace/output", ws / "place_dreamplace/analysis"),
        "CTS": (ws / "CTS_ecc/output", ws / "CTS_ecc/analysis"),
        "legalization": (
            ws / "legalization_dreamplace/output",
            ws / "legalization_dreamplace/analysis",
        ),
    }
    for step, paths in directories.items():
        if step in cleared_steps:
            assert all(list(path.iterdir()) == [] for path in paths)
        else:
            assert all((path / "stale").is_file() for path in paths)


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


@pytest.mark.parametrize(
    "db_value",
    [None, "", "some/db/path"],
)
def test_build_workspace_step_for_info_forwards_db_from_any_predecessor(tmp_path, db_value):
    # Regression: a Yosys (synthesis) predecessor has output.db == None on the
    # base OutputPaths contract, so reconstructing the next step must not crash.
    from pathlib import Path

    from chipcompiler.data import (
        EccOutput,
        EccStep,
        OriginDesign,
        Workspace,
        YosysStep,
    )
    from chipcompiler.runtime.workspace_api import _build_workspace_step_for_info

    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
    )

    # Yosys predecessor: db is the base default (None) -> must reconstruct cleanly.
    yosys_prev = YosysStep(name="Synthesis")
    ecc_step = _build_workspace_step_for_info(
        workspace, {"name": "Floorplan", "tool": "ecc"}, yosys_prev
    )
    assert isinstance(ecc_step, EccStep)

    # ECC/sizer predecessor: db forwarded unchanged (None / "" / a real path).
    ecc_prev = EccStep(
        name="place",
        output=EccOutput(
            def_=tmp_path / "p.def",
            verilog=tmp_path / "p.v",
            db=Path(db_value) if db_value else db_value,
        ),
    )
    next_step = _build_workspace_step_for_info(workspace, {"name": "CTS", "tool": "ecc"}, ecc_prev)
    assert isinstance(next_step, EccStep)
    # A real db path is forwarded into the next step's input.db; "" / None -> None.
    if db_value:
        assert next_step.input.db == Path(db_value)
    else:
        assert next_step.input.db is None
