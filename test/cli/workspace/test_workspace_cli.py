import json
import os
import subprocess
import sys
from contextlib import redirect_stdout, suppress
from types import SimpleNamespace

from chipcompiler.cli import main as cli_main
from chipcompiler.data import StateEnum

DEFAULT_WORKSPACE_STEP_SPECS = (
    ("Synthesis", "yosys"),
    ("Floorplan", "ecc"),
)


class DummyEngineDB:
    def __init__(self, flow):
        self.flow = flow
        self.engine = None
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
    fail_create_step_workspaces = False
    successful_steps = set()
    workspace_step_specs = DEFAULT_WORKSPACE_STEP_SPECS

    def __init__(self, workspace):
        self.workspace = workspace
        self.added_steps = []
        self.created = False
        self.cleared = False
        self.prepared_for_rerun = False
        self.run_steps_calls = []
        self.run_calls = []
        self.init_db_engine_calls = 0
        self.init_db_engine_steps = []
        self.call_order = []
        self.workspace_steps = [
            SimpleNamespace(name=name, tool=tool) for name, tool in self.workspace_step_specs
        ]
        self.engine_db = DummyEngineDB(self)
        DummyFlow.instances.append(self)

    def has_init(self):
        return False

    def add_step(self, step, tool, state):
        self.added_steps.append((step, tool, state))
        self.workspace.flow.data.setdefault("steps", []).append(
            {"name": step, "tool": tool, "state": getattr(state, "value", state)}
        )

    def create_step_workspaces(self):
        if DummyFlow.fail_create_step_workspaces:
            raise RuntimeError("tool setup failed")
        self.created = True

    def clear_states(self):
        self.cleared = True

    def init_db_engine(self):
        workspace_step = None
        for step in self.workspace_steps:
            if step.name not in self.successful_steps:
                workspace_step = step
                break
        return self.engine_db.create_db_engine(workspace_step)

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


def _response(capsys):
    out = capsys.readouterr().out
    return json.loads(out)


def _workspace(directory):
    design = SimpleNamespace(
        name="gcd",
        top_module="gcd",
        origin_def="",
        origin_verilog=os.path.join(directory, "origin", "gcd.v"),
        input_filelist="",
    )
    home = SimpleNamespace(path=os.path.join(directory, "home", "home.json"))
    flow = SimpleNamespace(path=os.path.join(directory, "home", "flow.json"), data={"steps": []})
    logger = SimpleNamespace(
        log_section=lambda *args, **kwargs: None,
        info=lambda *args, **kwargs: None,
    )
    return SimpleNamespace(
        directory=directory,
        flow=flow,
        home=home,
        logger=logger,
        design=design,
    )


def _install_runtime_mocks(monkeypatch, tmp_path):
    capture = {"create_kwargs": None, "loaded": []}

    DummyFlow.instances = []
    DummyFlow.next_run_states = []
    DummyFlow.fail_create_step_workspaces = False
    DummyFlow.successful_steps = set()
    DummyFlow.workspace_step_specs = DEFAULT_WORKSPACE_STEP_SPECS

    def fake_create_workspace(**kwargs):
        capture["create_kwargs"] = kwargs
        return _workspace(os.path.abspath(kwargs["directory"]))

    def fake_load_workspace(directory):
        capture["loaded"].append(directory)
        return _workspace(os.path.abspath(directory))

    monkeypatch.setattr("chipcompiler.data.create_workspace", fake_create_workspace)
    monkeypatch.setattr("chipcompiler.data.load_workspace", fake_load_workspace)
    monkeypatch.setattr("chipcompiler.data.init_workspace_config", lambda workspace: None)
    monkeypatch.setattr("chipcompiler.data.refresh_workspace_config", lambda workspace: None)
    monkeypatch.setattr("chipcompiler.engine.EngineFlow", DummyFlow)
    monkeypatch.setattr(
        "chipcompiler.rtl2gds.build_rtl2gds_flow",
        lambda: [("Synthesis", "yosys", "Unstart")],
    )

    ws = tmp_path / "workspace"
    (ws / "home").mkdir(parents=True)
    (ws / "home" / "parameters.json").write_text("{}")
    (ws / "home" / "flow.json").write_text('{"steps":[]}')
    (ws / "home" / "home.json").write_text("{}")
    return capture, ws


def test_create_input_json_success_writes_server_shape(monkeypatch, tmp_path, capsys):
    capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    request_path = tmp_path / "request.json"
    request_path.write_text(
        json.dumps(
            {
                "directory": str(ws),
                "pdk": "ics55",
                "pdk_root": "/pdk",
                "parameters": {"Design": "gcd", "Top module": "gcd"},
                "origin_def": "",
                "origin_verilog": "in.v",
                "filelist": "",
                "rtl_list": [],
            }
        )
    )

    rc = cli_main.run(["workspace", "create", "--input-json", str(request_path), "--json"])

    data = _response(capsys)
    assert rc == 0
    assert data == {
        "cmd": "create_workspace",
        "response": "success",
        "data": {"directory": os.path.abspath(ws), "workspace_id": os.path.abspath(ws)},
        "message": [f"create workspace success : {os.path.abspath(ws)}"],
    }
    assert capture["create_kwargs"]["directory"] == str(ws)
    assert capture["create_kwargs"]["input_filelist"] == ""
    assert DummyFlow.instances[0].created
    assert DummyFlow.instances[0].added_steps == [("Synthesis", "yosys", "Unstart")]


def test_create_input_json_from_stdin(monkeypatch, tmp_path, capsys):
    capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "sys.stdin",
        SimpleNamespace(
            read=lambda: json.dumps(
                {
                    "directory": str(ws),
                    "pdk": "ics55",
                    "parameters": {},
                    "rtl_list": [],
                }
            )
        ),
    )

    rc = cli_main.run(["workspace", "create", "--input-json", "-", "--json"])

    data = _response(capsys)
    assert rc == 0
    assert data["response"] == "success"
    assert capture["create_kwargs"]["directory"] == str(ws)


def test_create_input_json_resolves_relative_rtl_from_json_dir(
    monkeypatch,
    tmp_path,
    capsys,
):
    capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    request_path = project / "request.json"
    request_path.write_text(
        json.dumps(
            {
                "directory": str(ws),
                "pdk": "ics55",
                "filelist": "",
                "rtl_list": ["rtl/top.v"],
            }
        )
    )

    rc = cli_main.run(["workspace", "create", "--input-json", str(request_path), "--json"])

    data = _response(capsys)
    assert rc == 0
    assert data["response"] == "success"
    assert os.path.basename(capture["create_kwargs"]["input_filelist"]) == "filelist"
    assert (ws / "filelist").read_text().splitlines() == [str(project / "rtl" / "top.v")]


def test_create_input_json_resolves_relative_filelist_from_json_dir(
    monkeypatch,
    tmp_path,
    capsys,
):
    capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    request_path = project / "request.json"
    request_path.write_text(
        json.dumps(
            {
                "directory": str(ws),
                "pdk": "ics55",
                "filelist": "rtl/files.f",
                "rtl_list": [],
            }
        )
    )
    monkeypatch.chdir(tmp_path)

    rc = cli_main.run(["workspace", "create", "--input-json", str(request_path), "--json"])

    data = _response(capsys)
    assert rc == 0
    assert data["response"] == "success"
    assert capture["create_kwargs"]["input_filelist"] == str(project / "rtl" / "files.f")


def test_create_input_json_resolves_relative_origin_inputs_from_json_dir(
    monkeypatch,
    tmp_path,
    capsys,
):
    capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    request_path = project / "request.json"
    request_path.write_text(
        json.dumps(
            {
                "directory": str(ws),
                "pdk": "ics55",
                "origin_def": "inputs/top.def",
                "origin_verilog": "inputs/top.v",
                "filelist": "",
                "rtl_list": [],
            }
        )
    )
    monkeypatch.chdir(tmp_path)

    rc = cli_main.run(["workspace", "create", "--input-json", str(request_path), "--json"])

    data = _response(capsys)
    assert rc == 0
    assert data["response"] == "success"
    assert capture["create_kwargs"]["origin_def"] == str(project / "inputs" / "top.def")
    assert capture["create_kwargs"]["origin_verilog"] == str(project / "inputs" / "top.v")


def test_refresh_config_cli_calls_workspace_refresh(monkeypatch, tmp_path, capsys):
    capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    refreshed = []

    def fake_refresh_workspace_config(workspace):
        refreshed.append(workspace.directory)

    monkeypatch.setattr("chipcompiler.data.refresh_workspace_config", fake_refresh_workspace_config)

    rc = cli_main.run(["workspace", "refresh-config", "--directory", str(ws), "--json"])

    data = _response(capsys)
    assert rc == 0
    assert data == {
        "cmd": "refresh_config",
        "response": "success",
        "data": {"directory": os.path.abspath(ws), "refreshed": True},
        "message": [f"refresh workspace config success : {os.path.abspath(ws)}"],
    }
    assert capture["loaded"] == [str(ws)]
    assert refreshed == [os.path.abspath(ws)]


def test_sync_config_cli_rejects_path_outside_workspace_config(monkeypatch, tmp_path, capsys):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text("{}")

    rc = cli_main.run([
        "workspace",
        "sync-config",
        "--directory",
        str(ws),
        "--config-path",
        str(outside),
        "--json",
    ])

    data = _response(capsys)
    assert rc == 1
    assert data["cmd"] == "sync_config"
    assert data["response"] == "failed"
    assert data["data"]["config_path"] == os.path.abspath(outside)
    assert "outside workspace config directory" in data["message"][0]


def test_sync_config_cli_syncs_parameters_and_refreshes_when_changed(monkeypatch, tmp_path, capsys):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    config_dir = ws / "config"
    config_dir.mkdir()
    config_path = config_dir / "rt_default_config.json"
    config_path.write_text("{}")
    synced = []
    refreshed = []

    def fake_sync_workspace_config_to_parameters(workspace, path):
        synced.append((workspace.directory, path))
        return True

    def fake_refresh_workspace_config(workspace):
        refreshed.append(workspace.directory)

    monkeypatch.setattr(
        "chipcompiler.data.sync_workspace_config_to_parameters",
        fake_sync_workspace_config_to_parameters,
    )
    monkeypatch.setattr("chipcompiler.data.refresh_workspace_config", fake_refresh_workspace_config)

    rc = cli_main.run([
        "workspace",
        "sync-config",
        "--directory",
        str(ws),
        "--config-path",
        str(config_path),
        "--json",
    ])

    data = _response(capsys)
    assert rc == 0
    assert data == {
        "cmd": "sync_config",
        "response": "success",
        "data": {
            "directory": os.path.abspath(ws),
            "config_path": os.path.abspath(config_path),
            "parameters_changed": True,
            "refreshed": True,
        },
        "message": [f"sync workspace config success : {os.path.abspath(config_path)}"],
    }
    assert synced == [(os.path.abspath(ws), os.path.abspath(config_path))]
    assert refreshed == [os.path.abspath(ws)]


def test_create_flags_assemble_data_and_param_json(monkeypatch, tmp_path, capsys):
    capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    params_path = tmp_path / "params.json"
    params_path.write_text(
        json.dumps(
            {
                "Design": "from-json",
                "Top module": "from_json",
                "Clock": "json_clk",
                "Frequency max [MHz]": 50,
                "Core": {"Margin": [1, 2]},
            }
        )
    )
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)

    rc = cli_main.run(
        [
            "workspace",
            "create",
            "--directory",
            str(ws),
            "--pdk",
            "ics55",
            "--pdk-root",
            "/pdk",
            "--origin-def",
            "in.def",
            "--origin-verilog",
            "in.v",
            "--rtl",
            "a.v",
            "--rtl",
            "b.v",
            "--param-json",
            str(params_path),
            "--design",
            "gcd",
            "--top",
            "gcd",
            "--clock",
            "clk",
            "--freq",
            "100",
            "--json",
        ]
    )

    data = _response(capsys)
    assert rc == 0
    assert data["response"] == "success"
    kwargs = capture["create_kwargs"]
    assert kwargs["directory"] == str(ws)
    assert kwargs["pdk"] == "ics55"
    assert kwargs["pdk_root"] == "/pdk"
    assert kwargs["origin_def"] == "in.def"
    assert kwargs["origin_verilog"] == "in.v"
    assert kwargs["parameters"] == {
        "Design": "gcd",
        "Top module": "gcd",
        "Clock": "clk",
        "Frequency max [MHz]": 100.0,
        "Core": {"Margin": [1, 2]},
    }
    assert os.path.basename(kwargs["input_filelist"]) == "filelist"
    assert (ws / "filelist").read_text().splitlines() == [
        str(project / "a.v"),
        str(project / "b.v"),
    ]


def test_create_rejects_mixed_input_json_and_field_flags(tmp_path, capsys):
    request_path = tmp_path / "request.json"
    request_path.write_text("{}")

    for flag, value in (
        ("--directory", str(tmp_path / "ws")),
        ("--design", "gcd"),
        ("--design", ""),
        ("--top", "gcd"),
        ("--clock", "clk"),
        ("--freq", "100"),
        ("--freq", "0"),
    ):
        rc = cli_main.run(
            [
                "workspace",
                "create",
                "--input-json",
                str(request_path),
                flag,
                value,
                "--json",
            ]
        )

        data = _response(capsys)
        assert rc == 1
        assert data["cmd"] == "create_workspace"
        assert data["response"] == "error"
        assert "mutually exclusive" in data["message"][0]


def test_invalid_json_input_returns_error(monkeypatch, tmp_path, capsys):
    _install_runtime_mocks(monkeypatch, tmp_path)
    request_path = tmp_path / "bad.json"
    request_path.write_text("{")

    rc = cli_main.run(["workspace", "create", "--input-json", str(request_path), "--json"])

    data = _response(capsys)
    assert rc == 1
    assert data["response"] == "error"
    assert "invalid JSON" in data["message"][0]


def test_load_returns_directory_and_workspace_id(monkeypatch, tmp_path, capsys):
    capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)

    rc = cli_main.run(["workspace", "load", "--directory", str(ws), "--json"])

    data = _response(capsys)
    assert rc == 0
    assert data == {
        "cmd": "load_workspace",
        "response": "success",
        "data": {"directory": os.path.abspath(ws), "workspace_id": os.path.abspath(ws)},
        "message": [f"load workspace success : {os.path.abspath(ws)}"],
    }
    assert capture["loaded"] == [str(ws)]
    assert not DummyFlow.instances[0].created


def test_passive_workspace_commands_do_not_create_step_workspaces(
    monkeypatch,
    tmp_path,
    capsys,
):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    DummyFlow.fail_create_step_workspaces = True

    rc = cli_main.run(["workspace", "get-home", "--directory", str(ws), "--json"])

    data = _response(capsys)
    assert rc == 0
    assert data["cmd"] == "get_home"
    assert data["response"] == "success"
    assert not DummyFlow.instances[0].created


def test_get_info_does_not_create_step_workspaces(monkeypatch, tmp_path, capsys):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    DummyFlow.fail_create_step_workspaces = True

    monkeypatch.setattr(
        "chipcompiler.tools.get_step_info",
        lambda workspace, step, id: {"path": step.subflow["path"]},
    )
    rc = cli_main.run(
        [
            "workspace",
            "get-info",
            "--directory",
            str(ws),
            "--step",
            "Synthesis",
            "--id",
            "subflow",
            "--json",
        ]
    )

    data = _response(capsys)
    assert rc == 0
    assert data["response"] == "success"
    assert data["data"]["info"] == {
        "path": os.path.abspath(ws / "Synthesis_yosys" / "subflow.json")
    }
    assert not DummyFlow.instances[0].created


def test_load_accepts_workspace_before_flow_initialization(monkeypatch, tmp_path, capsys):
    capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    (ws / "home" / "flow.json").unlink()

    rc = cli_main.run(["workspace", "load", "--directory", str(ws), "--json"])

    data = _response(capsys)
    assert rc == 0
    assert data["response"] == "success"
    assert capture["loaded"] == [str(ws)]
    assert not DummyFlow.instances[0].created


def test_load_invalid_old_workspace_layout_fails(tmp_path, capsys):
    ws = tmp_path / "workspace"
    ws.mkdir()

    rc = cli_main.run(["workspace", "load", "--directory", str(ws), "--json"])

    data = _response(capsys)
    assert rc == 1
    assert data["cmd"] == "load_workspace"
    assert data["response"] == "failed"
    assert "invalid workspace directory" in data["message"][0]


def test_missing_required_fields_return_json_failed(capsys):
    rc = cli_main.run(["workspace", "load", "--json"])
    data = _response(capsys)
    assert rc == 1
    assert data["cmd"] == "load_workspace"
    assert data["response"] == "failed"
    assert "directory" in data["message"][0]

    rc = cli_main.run(["workspace", "run-step", "--directory", "/missing", "--json"])
    data = _response(capsys)
    assert rc == 1
    assert data["cmd"] == "run_step"
    assert data["response"] == "failed"
    assert "step" in data["message"][0]


def test_run_step_maps_success_and_failure(monkeypatch, tmp_path, capsys):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)

    rc = cli_main.run(
        ["workspace", "run-step", "--directory", str(ws), "--step", "Synthesis", "--json"]
    )
    data = _response(capsys)
    assert rc == 0
    assert data["cmd"] == "run_step"
    assert data["response"] == "success"
    assert data["data"] == {"step": "Synthesis", "state": "Success"}

    DummyFlow.next_run_states = [StateEnum.Imcomplete]
    rc = cli_main.run(
        ["workspace", "run-step", "--directory", str(ws), "--step", "Synthesis", "--json"]
    )
    data = _response(capsys)
    assert rc == 1
    assert data["response"] == "failed"
    assert data["data"] == {"step": "Synthesis", "state": "Incomplete"}


def test_run_step_initializes_engine_db_before_step(monkeypatch, tmp_path, capsys):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)

    rc = cli_main.run(
        ["workspace", "run-step", "--directory", str(ws), "--step", "Synthesis", "--json"]
    )

    data = _response(capsys)
    flow = DummyFlow.instances[0]
    assert rc == 0
    assert data["cmd"] == "run_step"
    assert data["response"] == "success"
    assert flow.init_db_engine_calls == 1
    assert flow.init_db_engine_steps == ["Synthesis"]
    assert flow.call_order == [
        ("init_db_engine",),
        ("run_step", "Synthesis", False),
    ]
    assert flow.run_steps_calls == []


def test_run_step_rerun_initializes_engine_db_before_step(monkeypatch, tmp_path, capsys):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    refresh_calls = []

    def refresh_config(workspace):
        refresh_calls.append(workspace.directory)
        DummyFlow.instances[-1].call_order.append(("refresh_config", workspace.directory))

    monkeypatch.setattr("chipcompiler.data.refresh_workspace_config", refresh_config)

    rc = cli_main.run(
        [
            "workspace",
            "run-step",
            "--directory",
            str(ws),
            "--step",
            "Floorplan",
            "--rerun",
            "--json",
        ]
    )

    data = _response(capsys)
    flow = DummyFlow.instances[0]
    assert rc == 0
    assert data["cmd"] == "run_step"
    assert data["response"] == "success"
    assert flow.init_db_engine_steps == ["Floorplan"]
    assert flow.call_order == [
        ("refresh_config", os.path.abspath(ws)),
        ("init_db_engine",),
        ("run_step", "Floorplan", True),
    ]
    assert refresh_calls == [os.path.abspath(ws)]
    assert flow.run_steps_calls == []


def test_run_step_skip_success_does_not_initialize_engine_db(monkeypatch, tmp_path, capsys):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    DummyFlow.successful_steps = {"Synthesis"}

    rc = cli_main.run(
        ["workspace", "run-step", "--directory", str(ws), "--step", "Synthesis", "--json"]
    )

    data = _response(capsys)
    flow = DummyFlow.instances[0]
    assert rc == 0
    assert data["cmd"] == "run_step"
    assert data["response"] == "success"
    assert flow.init_db_engine_calls == 0
    assert flow.call_order == [("run_step", "Synthesis", False)]


def test_run_step_rerun_initializes_engine_db_from_requested_successful_step(
    monkeypatch,
    tmp_path,
    capsys,
):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    DummyFlow.workspace_step_specs = (
        ("Synthesis", "yosys"),
        ("Floorplan", "ecc"),
        ("fixFanout", "ecc"),
    )
    DummyFlow.successful_steps = {"Synthesis", "Floorplan"}

    rc = cli_main.run(
        [
            "workspace",
            "run-step",
            "--directory",
            str(ws),
            "--step",
            "Floorplan",
            "--rerun",
            "--json",
        ]
    )

    data = _response(capsys)
    flow = DummyFlow.instances[0]
    assert rc == 0
    assert data["cmd"] == "run_step"
    assert data["response"] == "success"
    assert flow.init_db_engine_steps == ["Floorplan"]
    assert flow.call_order == [
        ("init_db_engine",),
        ("run_step", "Floorplan", True),
    ]
    assert flow.run_steps_calls == []


def test_workspace_json_output_survives_runtime_stdio_redirect(
    monkeypatch,
    tmp_path,
    capfd,
):
    from chipcompiler.cli.commands import workspace as workspace_commands
    from chipcompiler.utility.log import redirect_stdio_to_file

    log_path = tmp_path / "step.log"
    redirected_streams = []

    def fake_run_workspace_step(directory, step, rerun):
        os.write(1, b"runtime-fd-output\n")
        redirected_streams.append(redirect_stdio_to_file(str(log_path)))
        print("runtime-output")
        return {
            "cmd": "run_step",
            "response": "success",
            "data": {"step": step, "state": "Success"},
            "message": [f"run step {step} success : {directory}"],
        }

    monkeypatch.setattr(workspace_commands, "run_workspace_step", fake_run_workspace_step)

    saved_stdout = sys.stdout
    saved_stderr = sys.stderr
    saved_stdout_fd = os.dup(1)
    saved_stderr_fd = os.dup(2)
    try:
        rc = cli_main.run(
            [
                "workspace",
                "run-step",
                "--directory",
                str(tmp_path / "workspace"),
                "--step",
                "Synthesis",
                "--json",
            ]
        )
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(saved_stdout_fd, 1)
        os.dup2(saved_stderr_fd, 2)
        os.close(saved_stdout_fd)
        os.close(saved_stderr_fd)
        sys.stdout = saved_stdout
        sys.stderr = saved_stderr
        for stream in redirected_streams:
            with suppress(Exception):
                stream.close()

    capture = capfd.readouterr()
    out = capture.out
    data = json.loads(out)
    assert rc == 0
    assert data["cmd"] == "run_step"
    assert data["response"] == "success"
    assert data["data"] == {"step": "Synthesis", "state": "Success"}
    assert "runtime-fd-output" not in out
    assert "runtime-fd-output" in capture.err
    assert "runtime-output" in log_path.read_text()


def test_workspace_json_output_restores_stdout_for_programmatic_run(tmp_path):
    env = os.environ.copy()
    env["MPLCONFIGDIR"] = str(tmp_path / "mplconfig")
    workspace_dir = str(tmp_path / "workspace")
    script = f"""
from chipcompiler.cli import main as cli_main
from chipcompiler.cli.commands import workspace as workspace_commands

workspace_commands.load_workspace = lambda directory: {{
    "cmd": "load_workspace",
    "response": "success",
    "data": {{"directory": directory}},
    "message": [],
}}

rc = cli_main.run(["workspace", "load", "--directory", {workspace_dir!r}, "--json"])
print("after-programmatic-run")
raise SystemExit(rc)
"""

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=os.getcwd(),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    out_lines = completed.stdout.splitlines()
    assert completed.returncode == 0
    assert json.loads(out_lines[0])["response"] == "success"
    assert out_lines[1:] == ["after-programmatic-run"]
    assert "after-programmatic-run" not in completed.stderr


def test_workspace_json_output_honors_redirected_stdout(
    monkeypatch,
    tmp_path,
    capfd,
):
    from chipcompiler.cli.commands import workspace as workspace_commands

    monkeypatch.setattr(
        workspace_commands,
        "load_workspace",
        lambda directory: {
            "cmd": "load_workspace",
            "response": "success",
            "data": {"directory": directory},
            "message": [],
        },
    )
    output_path = tmp_path / "stdout.json"

    saved_stdout = sys.stdout
    saved_stderr = sys.stderr
    saved_stdout_fd = os.dup(1)
    saved_stderr_fd = os.dup(2)
    try:
        with output_path.open("w") as stream, redirect_stdout(stream):
            rc = cli_main.run(
                ["workspace", "load", "--directory", str(tmp_path / "workspace"), "--json"]
            )
        capture = capfd.readouterr()
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(saved_stdout_fd, 1)
        os.dup2(saved_stderr_fd, 2)
        os.close(saved_stdout_fd)
        os.close(saved_stderr_fd)
        sys.stdout = saved_stdout
        sys.stderr = saved_stderr

    redirected_output = output_path.read_text()
    assert rc == 0
    assert redirected_output.startswith("{")
    assert json.loads(redirected_output)["response"] == "success"
    assert capture.out == ""


def test_run_flow_rerun_clears_states_and_stops_on_failure(monkeypatch, tmp_path, capsys):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    DummyFlow.next_run_states = [StateEnum.Success, StateEnum.Imcomplete]
    prepare_calls = []

    def prepare_workspace_for_rerun(workspace, engine_flow):
        prepare_calls.append(workspace.directory)
        engine_flow.prepared_for_rerun = True
        engine_flow.call_order.append(("prepare_rerun", workspace.directory))

    monkeypatch.setattr(
        "chipcompiler.data.prepare_workspace_for_rerun", prepare_workspace_for_rerun
    )

    rc = cli_main.run(["workspace", "run-flow", "--directory", str(ws), "--rerun", "--json"])

    data = _response(capsys)
    flow = DummyFlow.instances[0]
    assert rc == 1
    assert data["cmd"] == "run_flow"
    assert data["response"] == "failed"
    assert data["data"] == {"rerun": True}
    assert not flow.cleared
    assert flow.prepared_for_rerun
    assert prepare_calls == [os.path.abspath(ws)]
    assert flow.call_order[0] == ("prepare_rerun", os.path.abspath(ws))
    assert flow.run_steps_calls == [True]
    assert flow.run_calls == [("Synthesis", True), ("Floorplan", True)]
    assert str(os.path.abspath(ws)) in data["message"][0]


def test_run_flow_resume_avoids_bulk_home_reset(monkeypatch, tmp_path, capsys):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)

    rc = cli_main.run(["workspace", "run-flow", "--directory", str(ws), "--json"])

    data = _response(capsys)
    flow = DummyFlow.instances[0]
    assert rc == 0
    assert data["cmd"] == "run_flow"
    assert data["response"] == "success"
    assert data["data"] == {"rerun": False}
    assert not flow.cleared
    assert not flow.prepared_for_rerun
    assert flow.run_steps_calls == [False]
    assert flow.run_calls == [("Synthesis", False), ("Floorplan", False)]


def test_run_flow_rerun_stops_when_prepare_fails(monkeypatch, tmp_path, capsys):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)

    def prepare_workspace_for_rerun(workspace, engine_flow):
        raise RuntimeError("cleanup failed")

    monkeypatch.setattr(
        "chipcompiler.data.prepare_workspace_for_rerun", prepare_workspace_for_rerun
    )

    rc = cli_main.run(["workspace", "run-flow", "--directory", str(ws), "--rerun", "--json"])

    data = _response(capsys)
    flow = DummyFlow.instances[0]
    assert rc == 1
    assert data["cmd"] == "run_flow"
    assert data["response"] == "error"
    assert data["data"] == {"rerun": True}
    assert "cleanup failed" in data["message"][0]
    assert flow.run_steps_calls == []
    assert flow.run_calls == []


def test_get_info_success_warning_and_exception(monkeypatch, tmp_path, capsys):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)

    monkeypatch.setattr(
        "chipcompiler.tools.get_step_info",
        lambda workspace, step, id: {"path": "/tmp/layout.png"},
    )
    rc = cli_main.run(
        [
            "workspace",
            "get-info",
            "--directory",
            str(ws),
            "--step",
            "Synthesis",
            "--id",
            "layout",
            "--json",
        ]
    )
    data = _response(capsys)
    assert rc == 0
    assert data["response"] == "success"
    assert data["data"] == {
        "step": "Synthesis",
        "id": "layout",
        "info": {"path": "/tmp/layout.png"},
    }

    monkeypatch.setattr("chipcompiler.tools.get_step_info", lambda workspace, step, id: {})
    rc = cli_main.run(
        [
            "workspace",
            "get-info",
            "--directory",
            str(ws),
            "--step",
            "Synthesis",
            "--id",
            "layout",
            "--json",
        ]
    )
    data = _response(capsys)
    assert rc == 0
    assert data["response"] == "warning"
    assert data["data"]["info"] == {}

    def raise_info(workspace, step, id):
        raise RuntimeError("boom")

    monkeypatch.setattr("chipcompiler.tools.get_step_info", raise_info)
    rc = cli_main.run(
        [
            "workspace",
            "get-info",
            "--directory",
            str(ws),
            "--step",
            "Synthesis",
            "--id",
            "layout",
            "--json",
        ]
    )
    data = _response(capsys)
    assert rc == 1
    assert data["response"] == "error"
    assert "boom" in data["message"][0]


def test_get_info_unknown_step_returns_failed(monkeypatch, tmp_path, capsys):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)

    rc = cli_main.run(
        [
            "workspace",
            "get-info",
            "--directory",
            str(ws),
            "--step",
            "Missing",
            "--id",
            "layout",
            "--json",
        ]
    )

    data = _response(capsys)
    assert rc == 1
    assert data["cmd"] == "get_info"
    assert data["response"] == "failed"
    assert "step not found" in data["message"][0]


def test_get_home_returns_path_and_failed_when_missing(monkeypatch, tmp_path, capsys):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)

    rc = cli_main.run(["workspace", "get-home", "--directory", str(ws), "--json"])
    data = _response(capsys)
    assert rc == 0
    assert data["cmd"] == "get_home"
    assert data["response"] == "success"
    assert data["data"] == {"path": os.path.abspath(ws / "home" / "home.json")}

    (ws / "home" / "home.json").unlink()
    rc = cli_main.run(["workspace", "get-home", "--directory", str(ws), "--json"])
    data = _response(capsys)
    assert rc == 1
    assert data["response"] == "failed"


def test_load_repairs_partial_home_json_without_changing_response(monkeypatch, tmp_path, capsys):
    ws = tmp_path / "workspace"
    home_dir = ws / "home"
    origin_dir = ws / "origin"
    home_dir.mkdir(parents=True)
    origin_dir.mkdir()
    (origin_dir / "gcd.v").write_text("module gcd(input clk); endmodule\n")
    (home_dir / "parameters.json").write_text(
        json.dumps(
            {
                "PDK": "mock",
                "Design": "gcd",
                "Top module": "gcd",
                "Clock": "clk",
                "Frequency max [MHz]": 100,
            }
        )
    )
    (home_dir / "flow.json").write_text(json.dumps({"steps": []}))
    (home_dir / "home.json").write_text(
        json.dumps(
            {
                "flow": str(home_dir / "flow.json"),
                "parameters": str(home_dir / "parameters.json"),
                "layout": "keep-layout",
                "metrics": {"pin dist.": "keep-pin"},
            }
        )
    )
    monkeypatch.setattr("chipcompiler.data.pdk.PDK.validate", lambda self: None)
    monkeypatch.setattr(
        "chipcompiler.cli.workspace.service.build_flow_for_workspace",
        lambda workspace, create_step_workspaces=True: DummyFlow(workspace),
    )

    rc = cli_main.run(["workspace", "load", "--directory", str(ws), "--json"])

    response = _response(capsys)
    repaired = json.loads((home_dir / "home.json").read_text())
    assert rc == 0
    assert response == {
        "cmd": "load_workspace",
        "response": "success",
        "data": {"directory": os.path.abspath(ws), "workspace_id": os.path.abspath(ws)},
        "message": [f"load workspace success : {os.path.abspath(ws)}"],
    }
    assert repaired["layout"] == "keep-layout"
    assert repaired["metrics"] == {"pin dist.": "keep-pin"}
    assert repaired["monitor"] == {
        "step": [],
        "memory": [],
        "runtime": [],
        "instance": [],
        "frequency": [],
    }
    assert repaired["checklist"] == str(home_dir / "checklist.json")


def test_workspace_help_uses_typer_app(capsys):
    rc = cli_main.run(["workspace", "--help"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "Usage: ecc workspace" in out
    assert "create" in out
    assert "run-flow" in out


def test_workspace_create_help_lists_existing_options(capsys):
    rc = cli_main.run(["workspace", "create", "--help"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "Usage: ecc workspace create" in out
    assert "--input-json" in out
    assert "--directory" in out
    assert "--param-json" in out
    assert "--design" in out
    assert "--top" in out
    assert "--clock" in out
    assert "--freq" in out


def test_workspace_json_output_suppresses_runtime_stdout(monkeypatch, tmp_path, capsys):
    from chipcompiler.cli.workspace.response import workspace_response

    _capture, _ws = _install_runtime_mocks(monkeypatch, tmp_path)

    def noisy_create(_request):
        print("lower runtime wrote to stdout")
        return workspace_response(
            "create_workspace",
            "error",
            message=["create workspace flow failed : boom"],
        )

    monkeypatch.setattr(
        "chipcompiler.cli.commands.workspace.create_workspace_from_request",
        noisy_create,
    )

    rc = cli_main.run(["workspace", "create", "--directory", str(tmp_path / "ws"), "--json"])

    out = capsys.readouterr().out
    assert rc == 1
    assert json.loads(out) == {
        "cmd": "create_workspace",
        "response": "error",
        "data": {},
        "message": ["create workspace flow failed : boom"],
    }


def test_workspace_create_rejects_positional_directory(capsys):
    rc = cli_main.run(["workspace", "create", "gcd"])

    captured = capsys.readouterr()
    assert rc != 0
    assert "unexpected extra argument" in captured.err.lower()


def test_unknown_workspace_subcommand_returns_nonzero(capsys):
    rc = cli_main.run(["workspace", "missing-command"])

    captured = capsys.readouterr()
    assert rc != 0
    assert "no such command" in captured.err.lower()


def test_non_workspace_commands_stay_on_argparse_path(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        "chipcompiler.cli.project.config._validate_pdk_contents",
        lambda name, root: None,
    )
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "ecc.toml").write_text("[design\n")

    rc = cli_main.run(["check", "--project", str(project_dir)])

    out = capsys.readouterr().out
    assert rc == 1
    assert "malformed ecc.toml" in out


def test_workspace_modules_keep_runtime_boundaries():
    module_paths = [
        os.path.join("chipcompiler", "cli", "commands", "workspace.py"),
        os.path.join("chipcompiler", "cli", "workspace", "request.py"),
        os.path.join("chipcompiler", "cli", "workspace", "response.py"),
        os.path.join("chipcompiler", "cli", "workspace", "service.py"),
    ]
    for module_path in module_paths:
        assert os.path.exists(module_path)

    with open(os.path.join("chipcompiler", "cli", "main.py"), encoding="utf-8") as f:
        main_source = f.read()
    assert "workspace_create.add_argument" not in main_source
    assert "workspace_run_flow.add_argument" not in main_source
    assert "workspace_app" not in main_source
    assert "workspace_legacy" not in main_source

    with open(
        os.path.join("chipcompiler", "cli", "workspace", "service.py"), encoding="utf-8"
    ) as f:
        service_source = f.read()
    assert "typer" not in service_source
    assert "print(" not in service_source


def test_workspace_modules_do_not_import_ecos_server():
    module_paths = [
        os.path.join("chipcompiler", "cli", "commands", "workspace.py"),
        os.path.join("chipcompiler", "cli", "workspace", "request.py"),
        os.path.join("chipcompiler", "cli", "workspace", "response.py"),
        os.path.join("chipcompiler", "cli", "workspace", "service.py"),
    ]
    for module_path in module_paths:
        assert os.path.exists(module_path)
        with open(module_path, encoding="utf-8") as f:
            source = f.read()
        assert "ecos_server" not in source
