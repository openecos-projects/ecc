"""PDK root persistence requirement on the CLI run paths.

A fresh run persists the resolved absolute PDK root in the workspace's
home/params.toml, so the workspace is reproducible across machines. An
existing workspace without a persisted root would otherwise resolve the
root from ECC_PDK_ROOT or the repository default; the run paths block that
case with a pdk_root_not_persisted error instead of resolving it silently.
"""

import json
import os

from chipcompiler.cli import main as cli_main
from chipcompiler.cli.project.pdk_root_persistence import missing_pdk_root_reason
from chipcompiler.data.workspace.config import save_workspace_config
from test.flow_fixture import step_fields


def _write_workspace(run_dir, parameters, flow=None):
    os.makedirs(os.path.join(run_dir, "home"), exist_ok=True)
    assert save_workspace_config(run_dir, parameters, flow)


def _base_parameters(**extra):
    parameters = {"pdk": "ics55", "design": "gcd", "top_module": "gcd", "clock": "clk"}
    parameters.update(extra)
    return parameters


class TestMissingPdkRootReason:
    def test_reason_when_root_missing(self, tmp_path):
        run_dir = str(tmp_path / "ws")
        _write_workspace(run_dir, _base_parameters())

        assert missing_pdk_root_reason(run_dir) is not None

    def test_no_reason_when_root_is_persisted(self, tmp_path):
        run_dir = str(tmp_path / "ws")
        _write_workspace(run_dir, _base_parameters(pdk_root=str(tmp_path / "pinned")))

        assert missing_pdk_root_reason(run_dir) is None

    def test_no_reason_for_a_non_ics55_pdk(self, tmp_path):
        run_dir = str(tmp_path / "ws")
        _write_workspace(run_dir, _base_parameters(pdk="sg13g2"))

        assert missing_pdk_root_reason(run_dir) is None


class TestRunBlocksOnMissingPersistedRoot:
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
                **step_fields(name, tools[name]),
            }
            for name, state in zip(step_names, states, strict=True)
        ]
        os.makedirs(os.path.join(run_dir, "home"), exist_ok=True)
        with open(os.path.join(run_dir, "home", "flow.json"), "w") as f:
            json.dump({"schema_version": 3, "steps": steps}, f)
        assert save_workspace_config(
            run_dir, parameters or _base_parameters(), {"preset": "rtl2gds"}
        )

    def test_run_errors_when_existing_workspace_has_no_persisted_root(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        monkeypatch,
        plain_records,
    ):
        env_root = minimal_ics55_pdk_factory(tmp_path / "env-pdk")
        monkeypatch.setenv("ECC_PDK_ROOT", str(env_root))
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

        rc = cli_main.run(["run", "--project", project_dir, "--plain"])

        assert rc != 0
        records = plain_records(capsys.readouterr().out)
        errors = [r for r in records if r.get("error") == "pdk_root_not_persisted"]
        assert len(errors) == 1

    def test_run_proceeds_when_root_is_persisted(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        monkeypatch,
        plain_records,
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        monkeypatch.setenv("ECC_PDK_ROOT", str(pdk_root))
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
        assert [r for r in records if r.get("error") == "pdk_root_not_persisted"] == []


class TestFreshRunPersistsResolvedRoot:
    def test_env_fallback_root_is_passed_to_workspace_creation(
        self, tmp_path, create_cli_project, flow_mocks, monkeypatch
    ):
        env_root = tmp_path / "env-pdk"
        env_root.mkdir()
        monkeypatch.setenv("ECC_PDK_ROOT", str(env_root))
        project_dir = create_cli_project(pdk_root="")

        rc = cli_main.run(["run", "--project", project_dir])

        assert rc == 0
        assert flow_mocks.capture["create_kwargs"]["pdk_root"] == str(env_root)
