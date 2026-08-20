import json
import os
from types import SimpleNamespace

import pytest

from chipcompiler.cli import main as cli_main
from chipcompiler.cli.command_handlers import project as project_module

_REAL_RUN_FLOW_VIA_WORKER = project_module._run_flow_via_worker


def _set_flow_preset(project_dir, preset):
    toml_path = os.path.join(project_dir, "ecc.toml")
    with open(toml_path) as f:
        content = f.read()
    content = content.replace('preset = "rtl2gds"', f'preset = "{preset}"')
    with open(toml_path, "w") as f:
        f.write(content)


def _patch_all_flow_builders(monkeypatch):
    markers = {}
    for attr in ("build_rtl2gds_flow", "build_rcx_flow", "build_harden_flow", "build_syn_sta_flow"):
        steps = [("Synthesis", "yosys", "Unstart"), (attr, "ecc", "Unstart")]
        markers[attr] = steps
        monkeypatch.setattr(f"chipcompiler.rtl2gds.builder.{attr}", lambda steps=steps: steps)
    return markers


class TestRun:
    def test_run_calls_create_workspace(self, tmp_path, create_cli_project, flow_mocks):
        project_dir = create_cli_project()

        rc = cli_main.run(["run", "--project", project_dir])
        assert rc == 0
        assert flow_mocks.capture["create_kwargs"]["directory"] == os.path.join(
            project_dir, "runs", "default"
        )

    def test_run_adds_flow_steps_when_no_init(self, tmp_path, create_cli_project, flow_mocks):
        project_dir = create_cli_project()

        rc = cli_main.run(["run", "--project", project_dir])
        assert rc == 0
        assert len(flow_mocks.flow.instances[0].added_steps) > 0

    def test_run_calls_create_and_run(self, tmp_path, create_cli_project, flow_mocks):
        project_dir = create_cli_project()

        rc = cli_main.run(["run", "--project", project_dir])
        assert rc == 0
        assert flow_mocks.flow.instances[0].create_called
        assert flow_mocks.flow.instances[0].run_called

    def test_run_overwrite_removes_existing(
        self, tmp_path, create_cli_project, create_flow_json, flow_mocks
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir, profile="main")

        rc = cli_main.run(["run", "--project", project_dir, "--overwrite"])
        assert rc == 0

    def test_run_fails_if_flow_json_exists(self, tmp_path, create_cli_project, create_flow_json):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir, profile="main")

        rc = cli_main.run(["run", "--project", project_dir])
        assert rc == 1

    def test_missing_worker_fails_before_creating_the_run(
        self, tmp_path, capsys, monkeypatch, create_cli_project, flow_mocks
    ):
        """A missing worker binary fails before run_dir is created, so a
        retry after fixing the worker is a clean run."""
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        monkeypatch.setattr(
            project_module,
            "_worker_binary_missing_error",
            lambda: "worker binary not found: /nonexistent/ecc",
        )

        rc = cli_main.run(["run", "--project", project_dir, "--json"])

        record = json.loads(capsys.readouterr().out)["records"][0]
        assert rc == 1
        assert record["error"] == "worker_unavailable"
        assert "worker binary not found" in record["reason"]
        assert not os.path.exists(run_dir)

    def test_missing_worker_preserves_an_overwrite_target(
        self, tmp_path, capsys, monkeypatch, create_cli_project, create_flow_json, flow_mocks
    ):
        """With --overwrite, the preflight fires before the old run is
        deleted; the existing run directory survives intact."""
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir, profile="main")
        monkeypatch.setattr(
            project_module,
            "_worker_binary_missing_error",
            lambda: "worker binary not found: /nonexistent/ecc",
        )

        rc = cli_main.run(["run", "--project", project_dir, "--overwrite", "--json"])

        record = json.loads(capsys.readouterr().out)["records"][0]
        assert rc == 1
        assert record["error"] == "worker_unavailable"
        assert os.path.isfile(os.path.join(run_dir, "home", "flow.json"))

    def test_run_fails_on_config_error(self, tmp_path):
        project_dir = tmp_path / "bad"
        project_dir.mkdir()
        (project_dir / "ecc.toml").write_text("[design]\n")
        rc = cli_main.run(["run", "--project", str(project_dir)])
        assert rc == 1

    def test_run_fails_when_create_workspace_returns_none(
        self, tmp_path, monkeypatch, create_cli_project, flow_mocks
    ):
        project_dir = create_cli_project()

        def fake_create(**kwargs):
            return None

        monkeypatch.setattr("chipcompiler.data.create_workspace", fake_create)
        rc = cli_main.run(["run", "--project", project_dir])
        assert rc == 1

    def test_run_fails_when_run_steps_false(self, tmp_path, create_cli_project, flow_mocks):
        project_dir = create_cli_project()
        flow_mocks.flow.run_steps_value = False

        rc = cli_main.run(["run", "--project", project_dir])
        assert rc == 1

    def test_run_json_uses_non_progress_path(
        self, tmp_path, capsys, create_cli_project, flow_mocks
    ):
        project_dir = create_cli_project()

        rc = cli_main.run(["run", "--project", project_dir, "--json"])
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "records" in data
        assert data["records"][0]["status"] == "success"
        assert flow_mocks.flow.instances[0].run_called

    def test_run_jsonl_uses_non_progress_path(
        self, tmp_path, capsys, create_cli_project, flow_mocks
    ):
        project_dir = create_cli_project()

        rc = cli_main.run(["run", "--project", project_dir, "--jsonl"])
        assert rc == 0
        out = capsys.readouterr().out
        objects = [json.loads(ln) for ln in out.strip().split("\n")]
        assert any("status" in obj for obj in objects)
        assert flow_mocks.flow.instances[0].run_called

    def test_run_json_no_progress_on_stderr(self, tmp_path, capsys, create_cli_project, flow_mocks):
        project_dir = create_cli_project()

        rc = cli_main.run(["run", "--project", project_dir, "--json"])
        assert rc == 0
        err = capsys.readouterr().err
        assert "step=" not in err

    def test_run_preserves_final_records(self, tmp_path, capsys, create_cli_project, flow_mocks):
        project_dir = create_cli_project()

        rc = cli_main.run(["run", "--project", project_dir, "--json"])
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        record = data["records"][0]
        assert record["run"] == "default"
        assert record["status"] == "success"
        assert "inspect_cmd" in record
        assert "metrics_cmd" not in record
        assert "log_cmd" in record


class TestRunFlowPreset:
    @pytest.mark.parametrize(
        "preset,builder_attr",
        [
            ("rtl2gds", "build_rtl2gds_flow"),
            ("rcx", "build_rcx_flow"),
            ("harden", "build_harden_flow"),
            ("syn_sta", "build_syn_sta_flow"),
        ],
    )
    def test_run_dispatches_builder_for_preset(
        self, tmp_path, monkeypatch, create_cli_project, flow_mocks, preset, builder_attr
    ):
        project_dir = create_cli_project()
        _set_flow_preset(project_dir, preset)
        markers = _patch_all_flow_builders(monkeypatch)

        rc = cli_main.run(["run", "--project", project_dir])

        assert rc == 0
        assert flow_mocks.flow.instances[0].added_steps == markers[builder_attr]

    def test_run_overwrite_rebuilds_flow_with_new_preset(
        self, tmp_path, monkeypatch, create_cli_project, create_flow_json, flow_mocks
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir, profile="main")
        _set_flow_preset(project_dir, "harden")
        markers = _patch_all_flow_builders(monkeypatch)

        rc = cli_main.run(["run", "--project", project_dir, "--overwrite"])

        assert rc == 0
        assert flow_mocks.flow.instances[0].added_steps == markers["build_harden_flow"]

    def test_run_forwards_pdk_overrides(self, tmp_path, create_cli_project, flow_mocks):
        project_dir = create_cli_project()
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path, "a") as f:
            f.write('\n[pdk.overrides]\ndont_use = ["ICG*"]\n')

        rc = cli_main.run(["run", "--project", project_dir])
        assert rc == 0
        create_kwargs = flow_mocks.capture["create_kwargs"]
        assert create_kwargs is not None
        assert create_kwargs["pdk_overrides"] == {"dont_use": ["ICG*"]}

    def test_run_forwards_resolved_pdk_override_paths(
        self, tmp_path, create_cli_project, flow_mocks
    ):
        project_dir = create_cli_project()
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path, "a") as f:
            f.write(
                "\n[pdk.overrides]\n"
                'sdc = "constraints/design.sdc"\n'
                'lefs = ["IP/STD_cell/x.lef"]\n'
                f'spef = "{tmp_path}/absolute.spef"\n'
                'dont_use = ["ICG*"]\n'
            )

        rc = cli_main.run(["run", "--project", project_dir])

        assert rc == 0
        create_kwargs = flow_mocks.capture["create_kwargs"]
        assert create_kwargs is not None
        assert create_kwargs["pdk_overrides"] == {
            "sdc": os.path.join(project_dir, "constraints", "design.sdc"),
            "lefs": [os.path.join(str(tmp_path / "ics55"), "IP", "STD_cell", "x.lef")],
            "spef": str(tmp_path / "absolute.spef"),
            "dont_use": ["ICG*"],
        }

    def test_run_forwards_absolute_paths_with_relative_env_pdk_root(
        self, tmp_path, monkeypatch, create_cli_project, flow_mocks
    ):
        project_dir = create_cli_project(pdk_root="")
        (tmp_path / "ics55").mkdir(exist_ok=True)
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path, "a") as f:
            f.write('\n[pdk.overrides]\nlefs = ["IP/STD_cell/x.lef"]\n')
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("CHIPCOMPILER_ICS55_PDK_ROOT", "ics55")

        rc = cli_main.run(["run", "--project", project_dir])

        assert rc == 0
        create_kwargs = flow_mocks.capture["create_kwargs"]
        assert create_kwargs is not None
        assert create_kwargs["pdk_overrides"] == {
            "lefs": [os.path.join(str(tmp_path / "ics55"), "IP", "STD_cell", "x.lef")],
        }


class TestWorkspaceRun:
    @pytest.fixture
    def workspace_mocks(self, monkeypatch, tmp_path):
        from chipcompiler.runtime.worker_operation import OperationResult

        seen = SimpleNamespace(
            load_path=None,
            has_init=True,
            calls=None,
            result=OperationResult(success=True, exit_code=0),
            binary_error=None,
            steps=[
                {"name": "Synthesis", "tool": "yosys", "state": "Success"},
                {"name": "place", "tool": "ecc", "state": "Imcomplete"},
                {"name": "CTS", "tool": "ecc", "state": "Unstart"},
            ],
        )

        class Flow:
            def __init__(self, workspace):
                self.workspace = workspace

            def has_init(self):
                return seen.has_init

        def fake_load_workspace(path):
            seen.load_path = path
            return SimpleNamespace(
                name="workspace",
                flow=SimpleNamespace(data={"steps": [dict(step) for step in seen.steps]}),
            )

        class FakeOperation:
            def run_sequence(self, calls):
                seen.calls = calls
                return seen.result

        monkeypatch.setattr("chipcompiler.data.load_workspace", fake_load_workspace)
        monkeypatch.setattr("chipcompiler.engine.EngineFlow", Flow)
        monkeypatch.setattr(
            "chipcompiler.cli.command_handlers.workspace_run._make_run_operation",
            lambda workspace_path, **kwargs: FakeOperation(),
        )
        monkeypatch.setattr(
            "chipcompiler.cli.command_handlers.workspace_run._worker_binary_missing_error",
            lambda: seen.binary_error,
        )
        monkeypatch.setattr(
            "chipcompiler.data.create_workspace",
            lambda **_kwargs: pytest.fail("workspace mode must not create a workspace"),
        )
        return seen

    def _write_post_run_flow(self, workspace, steps):
        home = os.path.join(workspace, "home")
        os.makedirs(home, exist_ok=True)
        with open(os.path.join(home, "flow.json"), "w") as f:
            json.dump({"steps": steps}, f)

    def test_only_force_wiring(self, workspace_mocks, tmp_path, capsys):
        workspace = str(tmp_path / "workspace")

        rc = cli_main.run(["run", "--workspace", workspace, "--only", "place", "--force", "--json"])

        record = json.loads(capsys.readouterr().out)["records"][0]
        assert rc == 0
        assert workspace_mocks.load_path == workspace
        assert workspace_mocks.calls == [
            ("flow.run_step", {"step": "place", "rerun": True, "invalidate_dependents": True})
        ]
        assert record["run"] == "workspace"
        assert record["status"] == "success"
        assert record["workspace"] == workspace
        assert record["executed_steps"] == ["place"]
        assert record["no_op"] is False

    def test_only_without_force_runs_step(self, workspace_mocks, tmp_path):
        workspace = str(tmp_path / "workspace")

        rc = cli_main.run(["run", "--workspace", workspace, "--only", "place", "--json"])

        assert rc == 0
        assert workspace_mocks.calls == [
            ("flow.run_step", {"step": "place", "rerun": True, "invalidate_dependents": True})
        ]

    def test_only_success_step_without_force_is_noop(self, workspace_mocks, tmp_path, capsys):
        workspace_mocks.steps = [
            {"name": "Synthesis", "tool": "yosys", "state": "Success"},
            {"name": "place", "tool": "ecc", "state": "Success"},
        ]
        workspace = str(tmp_path / "workspace")

        rc = cli_main.run(["run", "--workspace", workspace, "--only", "place", "--json"])

        record = json.loads(capsys.readouterr().out)["records"][0]
        assert rc == 0
        assert workspace_mocks.calls is None
        assert record == {
            "run": "workspace",
            "status": "success",
            "workspace": workspace,
            "executed_steps": [],
            "no_op": True,
        }

    def test_default_selector_is_resume(self, workspace_mocks, tmp_path, capsys):
        workspace = str(tmp_path / "workspace")

        rc = cli_main.run(["run", "--workspace", workspace, "--json"])

        record = json.loads(capsys.readouterr().out)["records"][0]
        assert rc == 0
        # The persisted suffix is driven step by step: an unscoped flow.run
        # would resume from the first non-success step, which may sit before
        # the selected boundary.
        assert workspace_mocks.calls == [
            ("flow.run_step", {"step": "place", "rerun": True, "reset_dependents": True}),
            ("flow.run_step", {"step": "CTS", "rerun": True}),
        ]
        assert record["executed_steps"] == ["place", "CTS"]

    def test_from_step_wiring(self, workspace_mocks, tmp_path, capsys):
        workspace = str(tmp_path / "workspace")

        rc = cli_main.run(["run", "--workspace", workspace, "--from", "CTS", "--json"])

        record = json.loads(capsys.readouterr().out)["records"][0]
        assert rc == 0
        assert workspace_mocks.calls == [
            ("flow.run_step", {"step": "CTS", "rerun": True, "reset_dependents": True}),
        ]
        assert record["executed_steps"] == ["CTS"]

    def test_preflight_rejects_an_unavailable_tool_before_any_mutation(
        self, workspace_mocks, tmp_path, capsys, monkeypatch
    ):
        """A later step with an unavailable tool fails before the first
        worker call — nothing is invalidated or deleted."""
        import chipcompiler.tools.eda as eda_module

        real_load = eda_module.load_eda_module

        def fake_load(tool, *, check_dependency=True):
            if tool == "ecc" and check_dependency:
                return None  # CTS's tool is unavailable
            return real_load(tool, check_dependency=check_dependency)

        monkeypatch.setattr("chipcompiler.tools.eda.load_eda_module", fake_load)
        workspace = str(tmp_path / "workspace")

        rc = cli_main.run(["run", "--workspace", workspace, "--from", "place", "--json"])

        record = json.loads(capsys.readouterr().out)["records"][0]
        assert rc != 0
        assert record["error"] == "config_error"
        assert workspace_mocks.calls is None or workspace_mocks.calls == []

    def test_from_step_never_runs_steps_before_the_boundary(
        self, workspace_mocks, tmp_path, capsys
    ):
        # Regression: with a failed step BEFORE the --from boundary, the
        # previous run_step+flow.run sequence let flow.run resume from that
        # earlier step, executing outside the requested suffix.
        workspace_mocks.steps = [
            {"name": "Synthesis", "tool": "yosys", "state": "Imcomplete"},
            {"name": "place", "tool": "ecc", "state": "Imcomplete"},
            {"name": "CTS", "tool": "ecc", "state": "Unstart"},
        ]
        workspace = str(tmp_path / "workspace")

        rc = cli_main.run(["run", "--workspace", workspace, "--from", "place", "--json"])

        record = json.loads(capsys.readouterr().out)["records"][0]
        assert rc == 0
        assert workspace_mocks.calls == [
            ("flow.run_step", {"step": "place", "rerun": True, "reset_dependents": True}),
            ("flow.run_step", {"step": "CTS", "rerun": True}),
        ]
        assert record["executed_steps"] == ["place", "CTS"]

    def test_resume_all_success_is_noop(self, workspace_mocks, tmp_path, capsys):
        workspace_mocks.steps = [
            {"name": "Synthesis", "tool": "yosys", "state": "Success"},
            {"name": "place", "tool": "ecc", "state": "Success"},
        ]
        workspace = str(tmp_path / "workspace")

        rc = cli_main.run(["run", "--workspace", workspace, "--resume", "--json"])

        record = json.loads(capsys.readouterr().out)["records"][0]
        assert rc == 0
        assert workspace_mocks.calls is None
        assert record["no_op"] is True
        assert record["executed_steps"] == []

    def test_failed_run_reports_failed_step_and_resume(self, workspace_mocks, tmp_path, capsys):
        from chipcompiler.runtime.worker_operation import OperationResult

        workspace_mocks.result = OperationResult(
            success=False, error="run step place failed with state Imcomplete"
        )
        workspace = str(tmp_path / "workspace")
        self._write_post_run_flow(
            workspace,
            [
                {"name": "Synthesis", "tool": "yosys", "state": "Success"},
                {"name": "place", "tool": "ecc", "state": "Imcomplete"},
                {"name": "CTS", "tool": "ecc", "state": "Unstart"},
            ],
        )

        rc = cli_main.run(["run", "--workspace", workspace, "--only", "place", "--force", "--json"])

        record = json.loads(capsys.readouterr().out)["records"][0]
        assert rc == 1
        assert record["status"] == "failed"
        assert record["executed_steps"] == []
        assert record["failed_step"] == "place"
        assert record["resume_cmd"] == f"ecc run --workspace {workspace} --resume"
        assert "place" in record["error"]

    def test_failed_suffix_run_reports_executed_prefix(self, workspace_mocks, tmp_path, capsys):
        from chipcompiler.runtime.worker_operation import OperationResult

        # place's worker call completed; CTS's failed.
        workspace_mocks.result = OperationResult(
            success=False, error="run flow failed", completed_calls=1
        )
        workspace = str(tmp_path / "workspace")

        rc = cli_main.run(["run", "--workspace", workspace, "--resume", "--json"])

        record = json.loads(capsys.readouterr().out)["records"][0]
        assert rc == 1
        assert record["executed_steps"] == ["place"]
        assert record["failed_step"] == "CTS"

    def test_worker_startup_failure_reports_no_executed_steps(
        self, workspace_mocks, tmp_path, capsys
    ):
        """A worker that dies before the first call must not report
        already-successful selected steps as executed."""
        from chipcompiler.runtime.worker_operation import OperationResult

        # --from on an all-success suffix re-selects every step; the worker
        # fails during startup, so zero calls completed.
        workspace_mocks.steps = [
            {"name": "Synthesis", "tool": "yosys", "state": "Success"},
            {"name": "place", "tool": "ecc", "state": "Success"},
        ]
        workspace_mocks.result = OperationResult(
            success=False, error="worker stdout closed before response", completed_calls=0
        )
        workspace = str(tmp_path / "workspace")

        rc = cli_main.run(["run", "--workspace", workspace, "--from", "Synthesis", "--json"])

        record = json.loads(capsys.readouterr().out)["records"][0]
        assert rc == 1
        assert record["executed_steps"] == []
        assert record["failed_step"] == "Synthesis"
        assert "worker stdout closed" in record["error"]

    def test_missing_worker_binary_returns_structured_failure(
        self, workspace_mocks, tmp_path, capsys
    ):
        workspace_mocks.binary_error = "worker binary not found: /missing/ecc"
        workspace = str(tmp_path / "workspace")

        rc = cli_main.run(["run", "--workspace", workspace, "--json"])

        record = json.loads(capsys.readouterr().out)["records"][0]
        assert rc == 1
        assert record["status"] == "failed"
        assert "not found" in record["error"]
        assert workspace_mocks.calls is None

    def test_non_executable_worker_is_a_preflight_error(self, tmp_path, monkeypatch):
        from chipcompiler.cli.command_handlers.workspace_run import _worker_binary_missing_error

        fake_ecc = tmp_path / "ecc"
        fake_ecc.write_text("#!/bin/sh\n")
        fake_ecc.chmod(0o644)  # exists, but not executable
        monkeypatch.setattr(
            "chipcompiler.runtime.worker_operation._default_worker_argv",
            lambda: [str(fake_ecc), "rpc", "serve", "--stdio"],
        )

        error = _worker_binary_missing_error()
        assert error is not None
        assert "not executable" in error

    def test_invalid_workspace(self, tmp_path, capsys):
        rc = cli_main.run(["run", "--workspace", str(tmp_path / "missing"), "--json"])

        record = json.loads(capsys.readouterr().out)["records"][0]
        assert rc == 1
        assert record["error"] == "invalid_workspace"

    def test_missing_flow(self, workspace_mocks, tmp_path, capsys):
        workspace_mocks.has_init = False

        rc = cli_main.run(["run", "--workspace", str(tmp_path / "workspace"), "--json"])

        record = json.loads(capsys.readouterr().out)["records"][0]
        assert rc == 1
        assert record["error"] == "missing_flow"

    def test_unknown_step(self, workspace_mocks, tmp_path, capsys):
        rc = cli_main.run(
            ["run", "--workspace", str(tmp_path / "workspace"), "--only", "bogus", "--json"]
        )

        record = json.loads(capsys.readouterr().out)["records"][0]
        assert rc == 1
        assert record["error"] == "unknown_step"
        assert "bogus" in record["reason"]

    @pytest.mark.parametrize(
        "argv,error",
        [
            (["--project", "p", "--workspace", "w"], "project_workspace_conflict"),
            (["--run-id", "r", "--workspace", "w"], "project_workspace_conflict"),
            (["--workspace", "w", "--overwrite"], "overwrite_requires_project"),
            (["--workspace", "w", "--set", "place.target_density=0.6"], "set_requires_project"),
            (["--workspace", "w", "--resume", "--only", "place"], "selector_conflict"),
            (["--workspace", "w", "--from", "place", "--only", "CTS"], "selector_conflict"),
            (["--workspace", "w", "--force"], "force_requires_only"),
            (["--resume"], "selector_requires_workspace"),
            (["--from", "place"], "selector_requires_workspace"),
            (["--only", "place"], "selector_requires_workspace"),
            (["--force"], "selector_requires_workspace"),
        ],
    )
    def test_option_conflicts(self, argv, error, capsys, monkeypatch):
        monkeypatch.setattr(
            "chipcompiler.data.load_workspace",
            lambda _path: pytest.fail("conflicts must be rejected before workspace load"),
        )

        rc = cli_main.run(["run", *argv, "--json"])

        record = json.loads(capsys.readouterr().out)["records"][0]
        assert rc == 1
        assert record["error"] == error


class TestRunFlowViaWorkerFailure:
    def test_missing_binary_returns_structured_failure(self, tmp_path, monkeypatch):
        """A missing worker binary is a typed failure, not a crash."""
        monkeypatch.setattr(
            "chipcompiler.runtime.worker_operation._default_worker_argv",
            lambda: [str(tmp_path / "nonexistent_ecc"), "rpc", "serve", "--stdio"],
        )

        result = _REAL_RUN_FLOW_VIA_WORKER(str(tmp_path))

        assert result.success is False
        assert "not found" in result.error
