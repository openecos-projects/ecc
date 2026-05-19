import json
import os
from types import SimpleNamespace

from chipcompiler.cli import main as cli_main
from chipcompiler.data import StateEnum


class DummyFlow:
    instances = []
    next_run_states = []
    fail_create_step_workspaces = False

    def __init__(self, workspace):
        self.workspace = workspace
        self.added_steps = []
        self.created = False
        self.cleared = False
        self.run_steps_calls = []
        self.run_calls = []
        self.workspace_steps = [
            SimpleNamespace(name="Synthesis", tool="yosys"),
            SimpleNamespace(name="Floorplan", tool="ecc"),
        ]
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
        if DummyFlow.next_run_states:
            return DummyFlow.next_run_states.pop(0)
        return StateEnum.Success

    def get_workspace_step(self, name):
        for step in self.workspace_steps:
            if step.name == name:
                return step
        return None


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

    def fake_create_workspace(**kwargs):
        capture["create_kwargs"] = kwargs
        return _workspace(os.path.abspath(kwargs["directory"]))

    def fake_load_workspace(directory):
        capture["loaded"].append(directory)
        return _workspace(os.path.abspath(directory))

    monkeypatch.setattr("chipcompiler.data.create_workspace", fake_create_workspace)
    monkeypatch.setattr("chipcompiler.data.load_workspace", fake_load_workspace)
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


def test_create_flags_assemble_data_and_param_json(monkeypatch, tmp_path, capsys):
    capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    params_path = tmp_path / "params.json"
    params_path.write_text(json.dumps({"Design": "gcd", "Core": {"Margin": [1, 2]}}))
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
    assert kwargs["parameters"] == {"Design": "gcd", "Core": {"Margin": [1, 2]}}
    assert os.path.basename(kwargs["input_filelist"]) == "filelist"
    assert (ws / "filelist").read_text().splitlines() == [
        str(project / "a.v"),
        str(project / "b.v"),
    ]


def test_create_rejects_mixed_input_json_and_field_flags(tmp_path, capsys):
    request_path = tmp_path / "request.json"
    request_path.write_text("{}")

    rc = cli_main.run(
        [
            "workspace",
            "create",
            "--input-json",
            str(request_path),
            "--directory",
            str(tmp_path / "ws"),
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


def test_run_flow_rerun_clears_states_and_stops_on_failure(monkeypatch, tmp_path, capsys):
    _capture, ws = _install_runtime_mocks(monkeypatch, tmp_path)
    DummyFlow.next_run_states = [StateEnum.Success, StateEnum.Imcomplete]

    rc = cli_main.run(["workspace", "run-flow", "--directory", str(ws), "--rerun", "--json"])

    data = _response(capsys)
    flow = DummyFlow.instances[0]
    assert rc == 1
    assert data["cmd"] == "run_flow"
    assert data["response"] == "failed"
    assert data["data"] == {"rerun": True}
    assert flow.cleared
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
    assert flow.run_steps_calls == [False]
    assert flow.run_calls == [("Synthesis", False), ("Floorplan", False)]


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


def test_workspace_json_output_suppresses_runtime_stdout(monkeypatch, tmp_path, capsys):
    from chipcompiler.cli.workspace_response import workspace_response

    _capture, _ws = _install_runtime_mocks(monkeypatch, tmp_path)

    def noisy_create(_request):
        print("lower runtime wrote to stdout")
        return workspace_response(
            "create_workspace",
            "error",
            message=["create workspace flow failed : boom"],
        )

    monkeypatch.setattr(
        "chipcompiler.cli.workspace_app.create_workspace_from_request",
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
        "chipcompiler.cli.config._validate_pdk_contents",
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
        os.path.join("chipcompiler", "cli", "workspace_app.py"),
        os.path.join("chipcompiler", "cli", "workspace_request.py"),
        os.path.join("chipcompiler", "cli", "workspace_response.py"),
        os.path.join("chipcompiler", "cli", "workspace_service.py"),
    ]
    for module_path in module_paths:
        assert os.path.exists(module_path)

    with open(os.path.join("chipcompiler", "cli", "main.py"), encoding="utf-8") as f:
        main_source = f.read()
    assert "workspace_create.add_argument" not in main_source
    assert "workspace_run_flow.add_argument" not in main_source

    with open(os.path.join("chipcompiler", "cli", "workspace_service.py"), encoding="utf-8") as f:
        service_source = f.read()
    assert "typer" not in service_source
    assert "print(" not in service_source


def test_workspace_modules_do_not_import_ecos_server():
    module_paths = [
        os.path.join("chipcompiler", "cli", "workspace_app.py"),
        os.path.join("chipcompiler", "cli", "workspace_request.py"),
        os.path.join("chipcompiler", "cli", "workspace_response.py"),
        os.path.join("chipcompiler", "cli", "workspace_service.py"),
    ]
    for module_path in module_paths:
        assert os.path.exists(module_path)
        with open(module_path, encoding="utf-8") as f:
            source = f.read()
        assert "ecos_server" not in source
