"""An existing workspace directory that project.json does not declare (#465).

`ecc workspace delete NAME` keeps the directory by default. `workspace create`
and `ecc run` on that name used to report success without registering it; an
absolute workspace path already registered such a directory.
"""

import json
from pathlib import Path

import pytest

from chipcompiler.cli import main as cli_main
from chipcompiler.data.parameter import Parameters, save_parameter
from test.flow_fixture import step_fields


def _workspace_directory(path: Path, *, design: str = "gcd", state: str = "Unstart") -> Path:
    home = path / "home"
    home.mkdir(parents=True)
    step = {
        "name": "synthesis",
        "tool": "yosys",
        "state": state,
        **step_fields("synthesis", "yosys"),
    }
    (home / "flow.json").write_text(json.dumps({"schema_version": 3, "steps": [step]}))
    assert save_parameter(
        Parameters(
            path=home / "params.toml",
            data={
                "pdk": "ics55",
                "design": design,
                "top_module": design,
                "clock": "clk",
                "frequency_max": 100,
                "_flow": {"start": "synthesis", "end": "synthesis"},
            },
        )
    )
    return home / "flow.json"


@pytest.fixture
def project(create_cli_project, manifest_stubs, monkeypatch):
    """An ecc.toml + project.json project that declares no workspace."""
    project_dir = Path(create_cli_project())
    manifest_stubs.write(project_dir, [])
    monkeypatch.setattr(
        "chipcompiler.cli.project.config._validate_pdk_contents",
        lambda name, root, overrides=None: None,
    )
    return project_dir


def _declared(project_dir: Path) -> dict[str, str]:
    manifest = json.loads((project_dir / "project.json").read_text())
    return {entry["workspace_id"]: entry["workspace_path"] for entry in manifest["workspaces"]}


def _no_engine(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("workspace create must not open the flow")

    monkeypatch.setattr("chipcompiler.engine.EngineFlow", refuse)


def _spy_engine(monkeypatch, flow_json: Path) -> dict:
    """Let an existing-workspace run reach the engine, and record that it did."""
    from chipcompiler.engine.rerun import StepRunResult

    seen = {"runs": 0}

    class Flow:
        def __init__(self, workspace):
            self.workspace = workspace

        def has_init(self):
            return True

        def create_step_workspaces(self, *, executable_steps=None):
            pass

        def load(self):
            from chipcompiler.utility import json_read

            self.workspace.flow.data = json_read(self.workspace.flow.path)
            return bool(self.workspace.flow.data.get("steps", []))

    def run(flow, *_args, **_kwargs):
        seen["runs"] += 1
        return StepRunResult(ok=True, executed=("synthesis",))

    monkeypatch.setattr(
        "chipcompiler.data.load_workspace",
        lambda _path: type(
            "Workspace", (), {"flow": type("FlowData", (), {"path": flow_json, "data": {}})()}
        )(),
    )
    monkeypatch.setattr("chipcompiler.engine.EngineFlow", Flow)
    for name in ("run_resume", "run_from", "run_only"):
        monkeypatch.setattr(f"chipcompiler.engine.rerun.{name}", run)
    monkeypatch.setattr(
        "chipcompiler.engine.rerun.selected_step_names", lambda *_args, **_kwargs: ["synthesis"]
    )
    return seen


def test_workspace_create_registers_an_undeclared_workspace_directory(
    project, monkeypatch, capsys, plain_records
):
    flow_json = _workspace_directory(project / "kept")
    before = flow_json.read_text()
    _no_engine(monkeypatch)

    rc = cli_main.run(["workspace", "create", "kept", "--project", str(project), "--plain"])

    records = plain_records(capsys.readouterr().out)
    assert rc == 0, records
    assert (records[-1]["workspace_id"], records[-1]["status"]) == ("kept", "refreshed")
    assert _declared(project) == {"kept": str(project / "kept")}
    assert flow_json.read_text() == before
    # The workspace can now be selected, which is what `create` promises.
    assert cli_main.run(["status", "--workspace", "kept", "--project", str(project)]) == 0


def test_workspace_create_with_set_registers_nothing(project, monkeypatch, capsys, plain_records):
    _workspace_directory(project / "kept")
    _no_engine(monkeypatch)

    rc = cli_main.run(
        ["workspace", "create", "kept", "--set", "placement:place.target_density=0.5"]
        + ["--project", str(project), "--plain"]
    )

    assert rc == 1
    assert plain_records(capsys.readouterr().out)[-1]["error"] == "set_requires_fresh_run"
    assert _declared(project) == {}


def test_workspace_create_refuses_a_directory_of_another_design(
    project, monkeypatch, capsys, plain_records
):
    _workspace_directory(project / "alien", design="other")
    _no_engine(monkeypatch)

    rc = cli_main.run(["workspace", "create", "alien", "--project", str(project), "--plain"])

    assert rc == 1
    assert plain_records(capsys.readouterr().out)[-1]["error"] == "workspace_not_importable"
    assert _declared(project) == {}


@pytest.mark.parametrize(
    "selector",
    [[], ["--resume"], ["--from", "synthesis"], ["--only", "synthesis", "--force"]],
    ids=["plain", "resume", "from", "only"],
)
def test_run_registers_an_undeclared_workspace_directory_before_it_runs(
    selector, project, monkeypatch, capsys, plain_records
):
    flow_json = _workspace_directory(project / "kept")
    seen = _spy_engine(monkeypatch, flow_json)

    rc = cli_main.run(
        ["run", "--workspace", "kept", *selector, "--project", str(project), "--plain"]
    )

    records = plain_records(capsys.readouterr().out)
    assert rc == 0, records
    assert seen["runs"] == 1
    assert _declared(project) == {"kept": str(project / "kept")}
