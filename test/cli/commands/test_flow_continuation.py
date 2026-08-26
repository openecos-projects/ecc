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
        record, hint = _records(capsys)
        assert record["error"] == "set_requires_fresh_run"
        assert hint["warning"] == "legacy_layout_detected"
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
        record, hint = _records(capsys)
        assert record["error"] == "workspace_config_invalid"
        assert hint["warning"] == "legacy_layout_detected"


def _tree_snapshot(root):
    """{relpath: (kind, payload)} for every entry under root — files carry
    their bytes, symlinks their target, directories a marker — so a created
    file, a created empty directory, or a new link all fail the comparison.
    The is_symlink check comes first: is_file()/is_dir() follow links."""
    root_path = Path(root)
    snapshot = {}
    for path in sorted(root_path.rglob("*")):
        rel = str(path.relative_to(root_path))
        if path.is_symlink():
            snapshot[rel] = ("link", str(path.readlink()))
        elif path.is_file():
            snapshot[rel] = ("file", path.read_bytes())
        elif path.is_dir():
            snapshot[rel] = ("dir", None)
        else:
            snapshot[rel] = ("other", None)
    return snapshot


def _write_manifest_with_workspace(project_dir, run_dir, pdk_root):
    manifest_path = os.path.join(project_dir, "project.json")
    with open(manifest_path, "w") as f:
        json.dump(
            {
                "schema_version": 1,
                "design_name": "gcd",
                "root_path": project_dir,
                "base_design": {
                    "pdk": "ics55",
                    "pdk_root": str(pdk_root),
                    "top_module": "gcd",
                    "clock": "clk",
                    "rtl_list": ["rtl/gcd.v"],
                    "parameters": {"design": "gcd", "frequency_max": 100},
                },
                "workspaces": [
                    {
                        "workspace_id": "ws_0001",
                        "workspace_path": run_dir,
                        "status": "failed",
                    }
                ],
            },
            f,
            indent=2,
        )
    return manifest_path


class TestFlowMismatchZeroMutation:
    def test_manifest_backed_mismatch_leaves_every_surface_untouched(
        self, tmp_path, capsys, create_cli_project, minimal_ics55_pdk_factory
    ):
        """AC-14: a divergent persisted flow fails with flow_mismatch and zero
        mutation — the whole workspace tree (paths and bytes, lock files and
        home initialization included) and the manifest are identical before
        and after the rejected run."""
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        run_dir = os.path.join(project_dir, "ws_0001")
        # The persisted ledger diverges from the configured preset at step one
        # (every preset chain starts with Synthesis).
        _write_existing_workspace(run_dir, ["place"])
        output_path = os.path.join(run_dir, "Synthesis_yosys", "output", "gcd.v")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w") as f:
            f.write("module gcd; endmodule // sentinel\n")
        manifest_path = _write_manifest_with_workspace(project_dir, run_dir, pdk_root)

        tree_before = _tree_snapshot(run_dir)
        manifest_before = Path(manifest_path).read_bytes()

        rc = cli_main.run(["run", "--project", project_dir, "--json"])

        assert rc != 0
        errors = [r for r in _records(capsys) if r.get("error") == "flow_mismatch"]
        assert len(errors) == 1
        assert _tree_snapshot(run_dir) == tree_before
        assert Path(manifest_path).read_bytes() == manifest_before

    def test_legacy_parameters_mismatch_never_migrates(
        self, tmp_path, capsys, create_cli_project, minimal_ics55_pdk_factory
    ):
        """AC-14 with a legacy-parameters workspace: the mismatch refusal must
        not migrate parameters.json, create ecc.toml/lock/home.json, or touch
        any other path."""
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        run_dir = os.path.join(project_dir, "ws_0001")
        home = os.path.join(run_dir, "home")
        os.makedirs(home)
        # Legacy shape: long-key parameters.json, no ecc.toml, and a ledger
        # that diverges from the project preset at step one.
        with open(os.path.join(home, "parameters.json"), "w") as f:
            json.dump(
                {
                    "PDK": "ics55",
                    "Design": "gcd",
                    "Top module": "gcd",
                    "Clock": "clk",
                    "Frequency max [MHz]": 250,
                },
                f,
            )
        with open(os.path.join(home, "flow.json"), "w") as f:
            json.dump(
                {
                    "steps": [
                        {
                            "name": "place",
                            "tool": "ecc",
                            "state": "Success",
                            "runtime": "",
                            "peak memory (mb)": 0,
                            "info": {},
                        }
                    ]
                },
                f,
            )
        manifest_path = _write_manifest_with_workspace(project_dir, run_dir, pdk_root)

        tree_before = _tree_snapshot(run_dir)
        manifest_before = Path(manifest_path).read_bytes()

        rc = cli_main.run(["run", "--project", project_dir, "--json"])

        assert rc != 0
        errors = [r for r in _records(capsys) if r.get("error") == "flow_mismatch"]
        assert len(errors) == 1
        assert _tree_snapshot(run_dir) == tree_before
        assert Path(manifest_path).read_bytes() == manifest_before

    def test_existing_run_rejects_symlinked_legacy_target(
        self, tmp_path, capsys, create_cli_project, minimal_ics55_pdk_factory, monkeypatch
    ):
        """A symlinked legacy run target must never be executed or mutated:
        the run fails loud with run_target_unsafe and the external workspace
        behind the link is left byte-identical."""
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: None,
        )
        external = tmp_path / "external-ws"
        _write_existing_workspace(str(external), RTL2GDS_NAMES)
        os.symlink(str(external), os.path.join(project_dir, "runs", "default"))

        flow_before = (external / "home" / "flow.json").read_bytes()
        rc = cli_main.run(["run", "--project", project_dir, "--json"])

        assert rc != 0
        errors = [r for r in _records(capsys) if r.get("error") == "run_target_unsafe"]
        assert len(errors) == 1
        assert (external / "home" / "flow.json").read_bytes() == flow_before

    def test_existing_run_rejects_symlinked_manifest_target(
        self, tmp_path, capsys, create_cli_project, minimal_ics55_pdk_factory
    ):
        """A declared workspace whose directory is a symlink into an
        external tree never reaches the engine: the manifest layer rejects it
        (manifest_invalid), with the dispatch ownership guard as the backup
        line behind it. The external tree is left untouched either way."""
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        external = tmp_path / "external-ws"
        _write_existing_workspace(str(external), RTL2GDS_NAMES)
        run_dir = os.path.join(project_dir, "ws_0001")
        os.symlink(str(external), run_dir)
        _write_manifest_with_workspace(project_dir, run_dir, pdk_root)

        flow_before = (external / "home" / "flow.json").read_bytes()
        rc = cli_main.run(["run", "--project", project_dir, "--json"])

        assert rc != 0
        errors = [
            r
            for r in _records(capsys)
            if r.get("error") in {"manifest_invalid", "run_target_unsafe"}
        ]
        assert len(errors) == 1
        assert (external / "home" / "flow.json").read_bytes() == flow_before

    def test_flow_exception_marks_manifest_status_failed(
        self, tmp_path, capsys, create_cli_project, minimal_ics55_pdk_factory, monkeypatch
    ):
        """A handled engine exception must not leave the manifest status at
        running: the write-back records failed."""
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: None,
        )
        run_dir = os.path.join(project_dir, "ws_0001")
        _write_existing_workspace(run_dir, RTL2GDS_NAMES, states=["Unstart"] * len(RTL2GDS_NAMES))
        manifest_path = _write_manifest_with_workspace(project_dir, run_dir, pdk_root)

        class Flow:
            def __init__(self, workspace):
                self.workspace = workspace

            def create_step_workspaces(self, *, executable_steps=None):
                return None

            def run_steps(self):
                raise RuntimeError("engine exploded")

        monkeypatch.setattr("chipcompiler.engine.EngineFlow", Flow)

        rc = cli_main.run(["run", "--project", project_dir, "--json"])

        assert rc != 0
        manifest = json.loads(Path(manifest_path).read_text())
        assert manifest["workspaces"][0]["status"] == "failed"
        errors = [r for r in _records(capsys) if r.get("error") == "flow_failed"]
        assert len(errors) == 1
