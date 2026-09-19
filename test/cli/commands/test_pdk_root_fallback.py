"""PDK root resolution-source disclosure on the CLI run paths.

A fresh run persists the resolved absolute PDK root in the workspace's
home/params.toml, so the workspace is reproducible across machines. An
existing workspace without a persisted root silently resolves the root from
the CHIPCOMPILER_ICS55_PDK_ROOT / ICS55_PDK_ROOT environment variables; the
run paths must surface that fallback as a pdk_root_env_fallback warning.
"""

import json
import os

from chipcompiler.cli import main as cli_main
from chipcompiler.cli.project.pdk_root_fallback import pdk_root_env_fallback_warning
from chipcompiler.data.workspace_config import save_workspace_config


def _write_workspace(run_dir, parameters, flow=None):
    os.makedirs(os.path.join(run_dir, "home"), exist_ok=True)
    assert save_workspace_config(run_dir, parameters, flow)


def _base_parameters(**extra):
    parameters = {"pdk": "ics55", "design": "gcd", "top_module": "gcd", "clock": "clk"}
    parameters.update(extra)
    return parameters


class TestEnvFallbackWarning:
    def test_warns_when_root_missing_and_env_resolves(self, tmp_path, monkeypatch):
        env_root = tmp_path / "env-pdk"
        env_root.mkdir()
        monkeypatch.setenv("CHIPCOMPILER_ICS55_PDK_ROOT", str(env_root))
        run_dir = str(tmp_path / "ws")
        _write_workspace(run_dir, _base_parameters())

        warning = pdk_root_env_fallback_warning(run_dir)

        assert warning is not None
        assert warning["warning"] == "pdk_root_env_fallback"
        assert warning["source"] == "CHIPCOMPILER_ICS55_PDK_ROOT"
        assert warning["resolved_root"] == str(env_root)

    def test_legacy_env_var_is_reported_as_source(self, tmp_path, monkeypatch):
        env_root = tmp_path / "env-pdk"
        env_root.mkdir()
        monkeypatch.delenv("CHIPCOMPILER_ICS55_PDK_ROOT", raising=False)
        monkeypatch.setenv("ICS55_PDK_ROOT", str(env_root))
        run_dir = str(tmp_path / "ws")
        _write_workspace(run_dir, _base_parameters())

        warning = pdk_root_env_fallback_warning(run_dir)

        assert warning is not None
        assert warning["source"] == "ICS55_PDK_ROOT"

    def test_no_warning_when_root_is_persisted(self, tmp_path, monkeypatch):
        env_root = tmp_path / "env-pdk"
        env_root.mkdir()
        monkeypatch.setenv("CHIPCOMPILER_ICS55_PDK_ROOT", str(env_root))
        run_dir = str(tmp_path / "ws")
        _write_workspace(run_dir, _base_parameters(pdk_root=str(tmp_path / "pinned")))

        assert pdk_root_env_fallback_warning(run_dir) is None

    def test_no_warning_without_a_resolving_env_var(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CHIPCOMPILER_ICS55_PDK_ROOT", raising=False)
        monkeypatch.delenv("ICS55_PDK_ROOT", raising=False)
        run_dir = str(tmp_path / "ws")
        _write_workspace(run_dir, _base_parameters())

        assert pdk_root_env_fallback_warning(run_dir) is None

    def test_no_warning_for_a_non_ics55_pdk(self, tmp_path, monkeypatch):
        env_root = tmp_path / "env-pdk"
        env_root.mkdir()
        monkeypatch.setenv("CHIPCOMPILER_ICS55_PDK_ROOT", str(env_root))
        run_dir = str(tmp_path / "ws")
        _write_workspace(run_dir, _base_parameters(pdk="sg13g2"))

        assert pdk_root_env_fallback_warning(run_dir) is None


class TestRunWarnsOnEnvFallbackRoot:
    def _write_existing_workspace(self, run_dir, step_names, states=None, parameters=None):
        from chipcompiler.rtl2gds.builder import build_rtl2gds_flow

        chain = [
            (step.value if hasattr(step, "value") else str(step), str(tool))
            for step, tool, _state in build_rtl2gds_flow()
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
        os.makedirs(os.path.join(run_dir, "home"), exist_ok=True)
        with open(os.path.join(run_dir, "home", "flow.json"), "w") as f:
            json.dump({"steps": steps}, f)
        assert save_workspace_config(
            run_dir, parameters or _base_parameters(), {"preset": "rtl2gds"}
        )

    def test_run_warns_when_existing_workspace_resolves_root_from_env(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        monkeypatch,
        plain_records,
    ):
        env_root = minimal_ics55_pdk_factory(tmp_path / "env-pdk")
        monkeypatch.setenv("CHIPCOMPILER_ICS55_PDK_ROOT", str(env_root))
        project_dir = create_cli_project(pdk_root=env_root)
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: None,
        )
        from chipcompiler.rtl2gds.builder import build_rtl2gds_flow

        step_names = [
            step.value if hasattr(step, "value") else str(step)
            for step, _tool, _state in build_rtl2gds_flow()
        ]
        run_dir = os.path.join(project_dir, "default")
        self._write_existing_workspace(run_dir, step_names)

        class Flow:
            def __init__(self, workspace):
                self.workspace = workspace

            def create_step_workspaces(self, *, executable_steps=None):
                raise AssertionError("no-op run must not rebuild step workspaces")

        monkeypatch.setattr("chipcompiler.engine.EngineFlow", Flow)

        rc = cli_main.run(["run", "--project", project_dir, "--plain"])

        assert rc == 0
        records = plain_records(capsys.readouterr().out)
        warning = [r for r in records if r.get("warning") == "pdk_root_env_fallback"]
        assert len(warning) == 1
        assert warning[0]["source"] == "CHIPCOMPILER_ICS55_PDK_ROOT"

    def test_run_stays_quiet_when_root_is_persisted(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        monkeypatch,
        plain_records,
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        monkeypatch.setenv("CHIPCOMPILER_ICS55_PDK_ROOT", str(pdk_root))
        project_dir = create_cli_project(pdk_root=pdk_root)
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: None,
        )
        from chipcompiler.rtl2gds.builder import build_rtl2gds_flow

        step_names = [
            step.value if hasattr(step, "value") else str(step)
            for step, _tool, _state in build_rtl2gds_flow()
        ]
        run_dir = os.path.join(project_dir, "default")
        self._write_existing_workspace(
            run_dir, step_names, parameters=_base_parameters(pdk_root=str(pdk_root))
        )

        class Flow:
            def __init__(self, workspace):
                self.workspace = workspace

            def create_step_workspaces(self, *, executable_steps=None):
                raise AssertionError("no-op run must not rebuild step workspaces")

        monkeypatch.setattr("chipcompiler.engine.EngineFlow", Flow)

        rc = cli_main.run(["run", "--project", project_dir, "--plain"])

        assert rc == 0
        records = plain_records(capsys.readouterr().out)
        assert [r for r in records if r.get("warning") == "pdk_root_env_fallback"] == []


class TestFreshRunPersistsResolvedRoot:
    def test_env_fallback_root_is_passed_to_workspace_creation(
        self, tmp_path, create_cli_project, flow_mocks, monkeypatch
    ):
        env_root = tmp_path / "env-pdk"
        env_root.mkdir()
        monkeypatch.setenv("CHIPCOMPILER_ICS55_PDK_ROOT", str(env_root))
        project_dir = create_cli_project(pdk_root="")

        rc = cli_main.run(["run", "--project", project_dir])

        assert rc == 0
        assert flow_mocks.capture["create_kwargs"]["pdk_root"] == str(env_root)
