"""Spec-mode drift disclosure on the CLI run paths.

A GUI-created (spec-mode) workspace pins its parameter intent in
``home/engineering-snapshot.json``. When ``home/params.toml`` becomes newer
than the snapshot, the CLI run paths must surface a ``workspace_spec_drift``
warning: the GUI snapshot (and its workspaceRevision) no longer reflects the
parameters the CLI run will execute.
"""

import json
import os

from chipcompiler.cli import main as cli_main
from chipcompiler.cli.project.spec_drift import workspace_spec_drift_warning
from chipcompiler.data.workspace_config import save_workspace_config

SNAPSHOT = {
    "schemaVersion": 2,
    "workspaceId": "workspace-test",
    "workspaceRevision": 3,
}


def _write_workspace(run_dir, parameters):
    os.makedirs(os.path.join(run_dir, "home"), exist_ok=True)
    assert save_workspace_config(run_dir, parameters, {"preset": "rtl2gds"})


def _base_parameters(**extra):
    parameters = {"pdk": "ics55", "design": "gcd", "top_module": "gcd", "clock": "clk"}
    parameters.update(extra)
    return parameters


def _write_snapshot(run_dir, *, mtime=None):
    snapshot_path = os.path.join(run_dir, "home", "engineering-snapshot.json")
    with open(snapshot_path, "w") as f:
        json.dump(SNAPSHOT, f)
    if mtime is not None:
        os.utime(snapshot_path, (mtime, mtime))
    return snapshot_path


class TestSpecDriftWarning:
    def test_warns_when_params_are_newer_than_the_snapshot(self, tmp_path):
        run_dir = str(tmp_path / "ws")
        _write_workspace(run_dir, _base_parameters())
        params_mtime = os.path.getmtime(os.path.join(run_dir, "home", "params.toml"))
        _write_snapshot(run_dir, mtime=params_mtime - 100)

        warning = workspace_spec_drift_warning(run_dir)

        assert warning is not None
        assert warning["warning"] == "workspace_spec_drift"
        assert warning["workspace"] == os.path.abspath(run_dir)
        assert "ecc param set --workspace" in warning["reason"]

    def test_no_warning_when_snapshot_is_newer(self, tmp_path):
        run_dir = str(tmp_path / "ws")
        _write_workspace(run_dir, _base_parameters())
        params_mtime = os.path.getmtime(os.path.join(run_dir, "home", "params.toml"))
        _write_snapshot(run_dir, mtime=params_mtime + 100)

        assert workspace_spec_drift_warning(run_dir) is None

    def test_no_warning_without_a_snapshot(self, tmp_path):
        run_dir = str(tmp_path / "ws")
        _write_workspace(run_dir, _base_parameters())

        assert workspace_spec_drift_warning(run_dir) is None


class TestRunWarnsOnSpecDrift:
    def _write_existing_workspace(self, run_dir, step_names, parameters=None):
        from chipcompiler.rtl2gds.builder import build_rtl2gds_flow

        chain = [
            (step.value if hasattr(step, "value") else str(step), str(tool))
            for step, tool, _state in build_rtl2gds_flow()
        ]
        tools = dict(chain)
        steps = [
            {
                "name": name,
                "tool": tools[name],
                "state": "Success",
                "runtime": "",
                "peak memory (mb)": 0,
                "info": {},
            }
            for name in step_names
        ]
        os.makedirs(os.path.join(run_dir, "home"), exist_ok=True)
        with open(os.path.join(run_dir, "home", "flow.json"), "w") as f:
            json.dump({"steps": steps}, f)
        assert save_workspace_config(
            run_dir, parameters or _base_parameters(), {"preset": "rtl2gds"}
        )

    def _noop_run(self, project_dir, monkeypatch):
        class Flow:
            def __init__(self, workspace):
                self.workspace = workspace

            def create_step_workspaces(self, *, executable_steps=None):
                raise AssertionError("no-op run must not rebuild step workspaces")

        monkeypatch.setattr("chipcompiler.engine.EngineFlow", Flow)
        return cli_main.run(["run", "--project", project_dir, "--plain"])

    def test_run_warns_when_params_drifted_from_the_snapshot(
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
        params_mtime = os.path.getmtime(os.path.join(run_dir, "home", "params.toml"))
        _write_snapshot(run_dir, mtime=params_mtime - 100)

        rc = self._noop_run(project_dir, monkeypatch)

        assert rc == 0
        records = plain_records(capsys.readouterr().out)
        warning = [r for r in records if r.get("warning") == "workspace_spec_drift"]
        assert len(warning) == 1

    def test_run_stays_quiet_when_snapshot_is_current(
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
        params_mtime = os.path.getmtime(os.path.join(run_dir, "home", "params.toml"))
        _write_snapshot(run_dir, mtime=params_mtime + 100)

        rc = self._noop_run(project_dir, monkeypatch)

        assert rc == 0
        records = plain_records(capsys.readouterr().out)
        assert [r for r in records if r.get("warning") == "workspace_spec_drift"] == []
