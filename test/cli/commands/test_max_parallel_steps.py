"""[flow] max_parallel_steps: config surface and run-time application."""

import contextlib
import json
import os

import pytest

from chipcompiler.cli import main as cli_main
from chipcompiler.cli.project.config import (
    load_project_config,
    resolve_max_parallel_steps,
    validate_project_config,
)
from chipcompiler.data import DEFAULT_MAX_PARALLEL_STEPS
from chipcompiler.data.workspace_config import validate_flow_config
from chipcompiler.engine import ExecutionPlan, StepRunResult
from test.cli.commands.test_flow_continuation import RTL2GDS_NAMES, _write_existing_workspace


def _declare(project_dir, literal):
    with open(os.path.join(project_dir, "ecc.toml"), "a") as f:
        f.write(f"max_parallel_steps = {literal}\n")


@pytest.fixture(autouse=True)
def _pdk_contents_are_valid(monkeypatch):
    monkeypatch.setattr(
        "chipcompiler.cli.project.config._validate_pdk_contents",
        lambda name, root, overrides=None: None,
    )


def _config(project_dir):
    return load_project_config(os.path.join(project_dir, "ecc.toml"))


class TestConfigSurface:
    def test_absent_key_is_none_and_resolves_to_the_default(self, create_cli_project):
        cfg = _config(create_cli_project())

        assert (
            cfg.flow_max_parallel_steps,
            "flow.max_parallel_steps" in cfg._explicit_keys,
            resolve_max_parallel_steps(cfg),
            validate_project_config(cfg),
        ) == (None, False, DEFAULT_MAX_PARALLEL_STEPS, [])

    def test_declared_key_is_explicit_and_wins(self, create_cli_project):
        project_dir = create_cli_project()
        _declare(project_dir, 2)
        cfg = _config(project_dir)

        assert (
            cfg.flow_max_parallel_steps,
            "flow.max_parallel_steps" in cfg._explicit_keys,
            resolve_max_parallel_steps(cfg),
            validate_project_config(cfg),
        ) == (2, True, 2, [])

    def test_a_project_without_ecc_toml_resolves_to_the_default(self):
        assert resolve_max_parallel_steps(None) == DEFAULT_MAX_PARALLEL_STEPS

    @pytest.mark.parametrize(
        ("literal", "shown"),
        [("0", "0"), ("-3", "-3"), ("true", "True"), ("2.5", "2.5"), ('"4"', "'4'")],
    )
    def test_invalid_values_are_rejected(self, create_cli_project, literal, shown):
        project_dir = create_cli_project()
        _declare(project_dir, literal)

        assert validate_project_config(_config(project_dir)) == [
            f"flow.max_parallel_steps must be an integer >= 1, got {shown}"
        ]

    def test_ecc_config_reports_the_value_and_its_source(
        self, capsys, create_cli_project, plain_records
    ):
        project_dir = create_cli_project()

        assert cli_main.run(["config", "--project", project_dir, "--plain"]) == 0
        default = _entry(plain_records(capsys.readouterr().out))
        _declare(project_dir, 2)
        assert cli_main.run(["config", "--project", project_dir, "--plain"]) == 0
        declared = _entry(plain_records(capsys.readouterr().out))

        assert (default, declared) == (
            {
                "config": "flow.max_parallel_steps",
                "scope": "project",
                "resolved": str(DEFAULT_MAX_PARALLEL_STEPS),
                "source": "default",
                "inspect": default["inspect"],
            },
            {
                "config": "flow.max_parallel_steps",
                "scope": "project",
                "value": "2",
                "resolved": "2",
                "source": "ecc.toml",
                "inspect": declared["inspect"],
            },
        )

    def test_check_and_flow_status_load_a_project_declaring_it(self, capsys, create_cli_project):
        project_dir = create_cli_project()
        _declare(project_dir, 2)

        assert cli_main.run(["check", "--project", project_dir]) == 0
        capsys.readouterr()
        assert cli_main.run(["flow", "status", "--project", project_dir, "--json"]) == 0
        records = json.loads(capsys.readouterr().out)

        assert records[0]["status"] == "ok"

    @pytest.mark.parametrize(("literal", "shown"), [("0", "0"), ('"4"', "'4'"), ("true", "True")])
    @pytest.mark.parametrize("command", ["status", "edit"])
    def test_flow_status_and_edit_reject_an_invalid_value_like_check_and_run(
        self, capsys, create_cli_project, command, literal, shown
    ):
        project_dir = create_cli_project()
        _declare(project_dir, literal)
        config = os.path.join(project_dir, "ecc.toml")
        with open(config) as f:
            before = f.read()
        argv = ["flow", command, "--project", project_dir, "--json"]
        if command == "edit":
            argv += ["--disable", "CTS", "--yes"]

        assert cli_main.run(argv) == 1

        assert json.loads(capsys.readouterr().out) == [
            {
                "kind": "error",
                "error": "config_error",
                "reason": f"flow.max_parallel_steps must be an integer >= 1, got {shown}",
                "inspect": f"ecc flow {command} --project {project_dir}",
            }
        ]
        with open(config) as f:
            assert f.read() == before

    def test_flow_edit_can_correct_an_invalid_value_with_the_flag(self, capsys, create_cli_project):
        project_dir = create_cli_project()
        _declare(project_dir, 0)

        assert (
            cli_main.run(
                [
                    "flow",
                    "edit",
                    "--project",
                    project_dir,
                    "--json",
                    "--max-parallel-steps",
                    "2",
                    "--yes",
                ]
            )
            == 0
        )
        capsys.readouterr()

        assert resolve_max_parallel_steps(_config(project_dir)) == 2

    def test_it_is_not_part_of_the_workspace_flow_target(self):
        assert validate_flow_config({"preset": "rtl2gds", "max_parallel_steps": 2}) == (
            validate_flow_config({"preset": "rtl2gds"})
        )


def _entry(records):
    (entry,) = [r for r in records if r.get("config") == "flow.max_parallel_steps"]
    return entry


class TestRunApplication:
    def test_fresh_run_applies_the_declared_value_to_the_engine(
        self, capsys, create_cli_project, flow_mocks
    ):
        project_dir = create_cli_project()
        _declare(project_dir, 2)

        assert cli_main.run(["run", "--project", project_dir]) == 0

        (flow,) = flow_mocks.flow.instances
        assert flow.max_parallel_steps == 2
        # a run-time knob: never written into the workspace flow target
        assert flow_mocks.capture["create_kwargs"]["flow_config"] is None

    def test_fresh_run_without_the_key_uses_the_default(self, create_cli_project, flow_mocks):
        assert cli_main.run(["run", "--project", create_cli_project()]) == 0

        (flow,) = flow_mocks.flow.instances
        assert flow.max_parallel_steps == DEFAULT_MAX_PARALLEL_STEPS

    def test_invalid_value_fails_the_run_before_a_workspace_exists(
        self, capsys, create_cli_project, flow_mocks
    ):
        project_dir = create_cli_project()
        _declare(project_dir, 0)

        assert cli_main.run(["run", "--project", project_dir]) == 1
        assert "flow.max_parallel_steps must be an integer >= 1" in capsys.readouterr().out
        assert flow_mocks.capture["create_kwargs"] is None

    def test_terminal_run_executes_through_the_engine_under_the_progress_sink(
        self, monkeypatch, create_cli_project, flow_mocks
    ):
        import chipcompiler.cli.rendering.progress as progress

        calls = []
        sink = object()

        @contextlib.contextmanager
        def fake_sink(engine_flow, ctx, project, stderr):
            calls.append("sink opened")
            yield sink
            calls.append("sink closed")

        @contextlib.contextmanager
        def fake_preserve():
            calls.append("stdio saved")
            yield
            calls.append("stdio restored")

        def fake_execute(engine_flow, plan, *, event_sink=None):
            calls.append(("execute", plan, event_sink))
            return type("Result", (), {"succeeded": True})()

        monkeypatch.setattr(progress, "should_enable_run_progress", lambda ctx, stderr: True)
        monkeypatch.setattr(progress, "run_progress_event_sink", fake_sink)
        monkeypatch.setattr(progress, "preserve_cli_stdio", fake_preserve)
        monkeypatch.setattr("chipcompiler.engine.execute", fake_execute)

        assert cli_main.run(["run", "--project", create_cli_project()]) == 0

        assert calls == [
            "stdio saved",
            "sink opened",
            ("execute", ExecutionPlan(intent="run"), sink),
            "sink closed",
            "stdio restored",
        ]

    @pytest.mark.parametrize("declared", [None, 2])
    def test_resume_applies_the_declared_value_to_the_engine(
        self,
        tmp_path,
        create_cli_project,
        minimal_ics55_pdk_factory,
        monkeypatch,
        declared,
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        _write_existing_workspace(
            os.path.join(project_dir, "default"),
            RTL2GDS_NAMES,
            states=["Success", "Success", "Incomplete"] + ["Unstart"] * (len(RTL2GDS_NAMES) - 3),
            pdk_root=pdk_root,
        )
        if declared is not None:
            _declare(project_dir, declared)
        seen = []

        class Flow:
            def __init__(self, workspace):
                self.workspace = workspace

            def create_step_workspaces(self, *, executable_steps=None):
                return None

            def load(self):
                from chipcompiler.utility import json_read

                self.workspace.flow.data = json_read(self.workspace.flow.path)
                return True

        def run_resume(flow, *, through=None, event_sink=None):
            seen.append(flow.max_parallel_steps)
            return StepRunResult(ok=True, executed=())

        monkeypatch.setattr("chipcompiler.engine.EngineFlow", Flow)
        monkeypatch.setattr("chipcompiler.engine.rerun.run_resume", run_resume)

        assert cli_main.run(["run", "--project", project_dir]) == 0

        assert seen == [declared or DEFAULT_MAX_PARALLEL_STEPS]

    def test_existing_workspace_is_not_a_flow_mismatch_after_the_key_is_added(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        monkeypatch,
        plain_records,
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        _write_existing_workspace(
            os.path.join(project_dir, "default"), RTL2GDS_NAMES, pdk_root=pdk_root
        )
        _declare(project_dir, 2)

        class Flow:
            def __init__(self, workspace):
                self.workspace = workspace

        monkeypatch.setattr("chipcompiler.engine.EngineFlow", Flow)

        assert cli_main.run(["run", "--project", project_dir, "--plain"]) == 0

        (record, *_rest) = plain_records(capsys.readouterr().out)
        assert (record["status"], record["no_op"]) == ("success", "True")
