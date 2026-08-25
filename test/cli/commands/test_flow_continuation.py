import json
import os
from pathlib import Path

from chipcompiler.cli import main as cli_main


def _write_existing_workspace(run_dir, step_names, states=None, preset="rtl2gds"):
    """A valid existing workspace: home/ecc.toml + flow.json with given steps."""
    from chipcompiler.data.workspace_config import save_workspace_config
    from chipcompiler.rtl2gds.builder import build_harden_flow

    chain = [
        (step.value if hasattr(step, "value") else str(step), str(tool))
        for step, tool, _state in build_harden_flow()
    ]
    tools = dict(chain)
    states = states or ["Success"] * len(step_names)
    steps = [
        {
            "name": name,
            "tool": tools[name],
            "state": state,
            "runtime": "",
            "peak memory (mb)": 0,
            "info": {},
        }
        for name, state in zip(step_names, states, strict=True)
    ]
    home = os.path.join(run_dir, "home")
    os.makedirs(home, exist_ok=True)
    with open(os.path.join(home, "flow.json"), "w") as f:
        json.dump({"steps": steps}, f)
    assert save_workspace_config(
        run_dir,
        {"pdk": "ics55", "design": "gcd", "top_module": "gcd", "clock": "clk"},
        {"preset": preset},
    )


def _set_flow_preset(project_dir, preset):
    toml_path = os.path.join(project_dir, "ecc.toml")
    with open(toml_path) as f:
        content = f.read()
    content = content.replace('preset = "rtl2gds"', f'preset = "{preset}"')
    with open(toml_path, "w") as f:
        f.write(content)


RTL2GDS_NAMES = [
    "Synthesis",
    "Floorplan",
    "fixFanout",
    "place",
    "CTS",
    "legalization",
    "route",
    "drc",
    "lvs",
    "filler",
]


def _flow_states(run_dir):
    with open(os.path.join(run_dir, "home", "flow.json")) as f:
        return {s["name"]: s["state"] for s in json.load(f)["steps"]}


def _flow_section(run_dir):
    from chipcompiler.data.workspace_config import load_workspace_config

    return load_workspace_config(run_dir)["_flow"]


def _records(capsys):
    return json.loads(capsys.readouterr().out)["records"]


class TestFlowContinuation:
    def test_prefix_extension_appends_suffix_and_runs_only_it(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        monkeypatch,
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: None,
        )
        os.makedirs(os.path.join(project_dir, "runs", ".keep"), exist_ok=True)
        _set_flow_preset(project_dir, "rcx")
        run_dir = os.path.join(project_dir, "runs", "default")
        _write_existing_workspace(run_dir, RTL2GDS_NAMES)

        created = {}

        class Flow:
            def __init__(self, workspace):
                self.workspace = workspace

            def create_step_workspaces(self, *, executable_steps=None):
                created["executable"] = executable_steps

            def run_steps(self):
                return True

        monkeypatch.setattr("chipcompiler.engine.EngineFlow", Flow)

        rc = cli_main.run(["run", "--project", project_dir, "--json"])

        assert rc == 0
        states = _flow_states(run_dir)
        # Exactly RCX + sta appended as Unstart; prefix states untouched.
        assert list(states) == RTL2GDS_NAMES + ["RCX", "sta"]
        assert all(states[name] == "Success" for name in RTL2GDS_NAMES)
        # The adopted target is the widened preset.
        assert _flow_section(run_dir) == {"preset": "rcx"}
        # Only the suffix was scheduled for execution.
        assert created["executable"] == {"RCX", "sta"}
        records = _records(capsys)
        assert records[0]["status"] == "success"
        assert records[0]["appended_steps"] == ["RCX", "sta"]

    def test_noop_when_flow_already_complete(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        monkeypatch,
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: None,
        )
        os.makedirs(os.path.join(project_dir, "runs", ".keep"), exist_ok=True)
        run_dir = os.path.join(project_dir, "runs", "default")
        _write_existing_workspace(run_dir, RTL2GDS_NAMES)

        class Flow:
            def __init__(self, workspace):
                self.workspace = workspace

            def create_step_workspaces(self, *, executable_steps=None):
                raise AssertionError("no-op run must not rebuild step workspaces")

        monkeypatch.setattr("chipcompiler.engine.EngineFlow", Flow)

        rc = cli_main.run(["run", "--project", project_dir, "--json"])

        assert rc == 0
        records = _records(capsys)
        assert records[0]["status"] == "success"
        assert records[0]["no_op"] is True

    def test_set_rejected_on_existing_run(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        monkeypatch,
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: None,
        )
        os.makedirs(os.path.join(project_dir, "runs", ".keep"), exist_ok=True)
        run_dir = os.path.join(project_dir, "runs", "default")
        _write_existing_workspace(run_dir, RTL2GDS_NAMES)
        flow_before = Path(run_dir, "home", "flow.json").read_bytes()

        rc = cli_main.run(
            ["run", "--project", project_dir, "--set", "synth.max_fanout=16", "--json"]
        )

        assert rc != 0
        (record,) = _records(capsys)
        assert record["error"] == "set_requires_fresh_run"
        assert Path(run_dir, "home", "flow.json").read_bytes() == flow_before

    def test_params_warning_on_existing_run(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        monkeypatch,
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: None,
        )
        os.makedirs(os.path.join(project_dir, "runs", ".keep"), exist_ok=True)
        with open(os.path.join(project_dir, "ecc.toml"), "a") as f:
            f.write("\n[params.synth]\nmax_fanout = 16\n")
        run_dir = os.path.join(project_dir, "runs", "default")
        _write_existing_workspace(run_dir, RTL2GDS_NAMES)

        class Flow:
            def __init__(self, workspace):
                self.workspace = workspace

            def create_step_workspaces(self, *, executable_steps=None):
                raise AssertionError("no-op run must not rebuild step workspaces")

        monkeypatch.setattr("chipcompiler.engine.EngineFlow", Flow)

        rc = cli_main.run(["run", "--project", project_dir, "--json"])

        assert rc == 0
        records = _records(capsys)
        warning = [r for r in records if r.get("warning") == "params_ignored_on_existing_run"]
        assert len(warning) == 1

    def test_malformed_workspace_config_is_config_invalid_not_invalid_workspace(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        monkeypatch,
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        os.makedirs(os.path.join(project_dir, "runs", ".keep"), exist_ok=True)
        run_dir = os.path.join(project_dir, "runs", "default")
        _write_existing_workspace(run_dir, RTL2GDS_NAMES)
        Path(run_dir, "home", "ecc.toml").write_text("[params\nbroken =")

        rc = cli_main.run(["run", "--project", project_dir, "--json"])

        assert rc != 0
        (record,) = _records(capsys)
        assert record["error"] == "workspace_config_invalid"
