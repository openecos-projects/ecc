import json
import os

from chipcompiler.cli import main as cli_main


class TestCliProvenance:
    def test_run_set_reports_cli_source_in_config(
        self, tmp_path, monkeypatch, capsys, create_cli_project
    ):
        from types import SimpleNamespace

        project_dir = create_cli_project()
        workspace_obj = SimpleNamespace(name="workspace")

        def fake_create(**kwargs):
            run_dir = kwargs["directory"]
            os.makedirs(os.path.join(run_dir, "home"), exist_ok=True)
            return workspace_obj

        monkeypatch.setattr("chipcompiler.data.create_workspace", fake_create)
        monkeypatch.setattr(
            "chipcompiler.engine.EngineFlow",
            type(
                "DummyFlow",
                (),
                {
                    "__init__": lambda self, workspace: None,
                    "has_init": lambda self: False,
                    "add_step": lambda self, **kw: None,
                    "create_step_workspaces": lambda self: None,
                    "run_steps": lambda self: True,
                },
            ),
        )
        monkeypatch.setattr(
            "chipcompiler.rtl2gds.build_rtl2gds_flow",
            lambda: [("Synthesis", "yosys", "Unstart")],
        )
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root: None,
        )
        monkeypatch.setattr(
            "chipcompiler.cli.rendering.progress.should_enable_run_progress",
            lambda *a, **kw: False,
        )

        rc = cli_main.run(
            [
                "run",
                "--project",
                project_dir,
                "--set",
                "synth.max_fanout=16",
            ]
        )
        assert rc == 0
        capsys.readouterr()

        # Verify provenance file was written
        provenance = os.path.join(
            project_dir, "runs", "default", "home", "cli-param-overrides.json"
        )
        assert os.path.isfile(provenance)
        with open(provenance) as f:
            data = json.load(f)
        assert data["synth.max_fanout"] == 16

    def test_config_resolved_shows_cli_source(
        self, tmp_path, monkeypatch, capsys, create_cli_project
    ):
        from types import SimpleNamespace

        project_dir = create_cli_project()
        workspace_obj = SimpleNamespace(name="workspace")

        def fake_create(**kwargs):
            run_dir = kwargs["directory"]
            os.makedirs(os.path.join(run_dir, "home"), exist_ok=True)
            return workspace_obj

        monkeypatch.setattr("chipcompiler.data.create_workspace", fake_create)
        monkeypatch.setattr(
            "chipcompiler.engine.EngineFlow",
            type(
                "DummyFlow",
                (),
                {
                    "__init__": lambda self, workspace: None,
                    "has_init": lambda self: False,
                    "add_step": lambda self, **kw: None,
                    "create_step_workspaces": lambda self: None,
                    "run_steps": lambda self: True,
                },
            ),
        )
        monkeypatch.setattr(
            "chipcompiler.rtl2gds.build_rtl2gds_flow",
            lambda: [("Synthesis", "yosys", "Unstart")],
        )
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root: None,
        )
        monkeypatch.setattr(
            "chipcompiler.cli.rendering.progress.should_enable_run_progress",
            lambda *a, **kw: False,
        )

        # Run with --set
        rc = cli_main.run(
            [
                "run",
                "--project",
                project_dir,
                "--set",
                "synth.max_fanout=16",
            ]
        )
        assert rc == 0
        capsys.readouterr()

        # Now inspect config --resolved
        rc = cli_main.run(["config", "--resolved", "--project", project_dir, "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        param_records = [r for r in data["records"] if r.get("kind") == "param"]
        fanout = next(r for r in param_records if r["key"] == "synth.max_fanout")
        assert fanout["value"] == 16
        assert fanout["source"] == "cli"

    def test_config_resolved_toml_plus_cli_precedence(
        self, tmp_path, monkeypatch, capsys, create_cli_project
    ):
        from types import SimpleNamespace

        project_dir = create_cli_project()
        workspace_obj = SimpleNamespace(name="workspace")

        # Set a TOML override first
        cli_main.run(["param", "set", "synth.max_fanout", "16", "--project", project_dir])
        capsys.readouterr()

        def fake_create(**kwargs):
            run_dir = kwargs["directory"]
            os.makedirs(os.path.join(run_dir, "home"), exist_ok=True)
            return workspace_obj

        monkeypatch.setattr("chipcompiler.data.create_workspace", fake_create)
        monkeypatch.setattr(
            "chipcompiler.engine.EngineFlow",
            type(
                "DummyFlow",
                (),
                {
                    "__init__": lambda self, workspace: None,
                    "has_init": lambda self: False,
                    "add_step": lambda self, **kw: None,
                    "create_step_workspaces": lambda self: None,
                    "run_steps": lambda self: True,
                },
            ),
        )
        monkeypatch.setattr(
            "chipcompiler.rtl2gds.build_rtl2gds_flow",
            lambda: [("Synthesis", "yosys", "Unstart")],
        )
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root: None,
        )
        monkeypatch.setattr(
            "chipcompiler.cli.rendering.progress.should_enable_run_progress",
            lambda *a, **kw: False,
        )

        # Run with different CLI override
        rc = cli_main.run(
            [
                "run",
                "--project",
                project_dir,
                "--set",
                "synth.max_fanout=32",
            ]
        )
        assert rc == 0
        capsys.readouterr()

        rc = cli_main.run(["config", "--resolved", "--project", project_dir, "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        param_records = [r for r in data["records"] if r.get("kind") == "param"]
        fanout = next(r for r in param_records if r["key"] == "synth.max_fanout")
        assert fanout["value"] == 32
        assert fanout["source"] == "cli"
