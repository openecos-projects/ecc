import json

import pytest

from chipcompiler.cli import main as cli_main
from chipcompiler.cli.inspection import env_probe
from chipcompiler.cli.inspection.env_probe import FAIL, PASS, ProbeResult


def _patch_probes(monkeypatch, results_by_component, *, slang_called=None):
    """Replace probe_environment with canned results keyed by component."""

    def fake(components, *, cfg=None, include_slang=True):
        selected = [results_by_component[c] for c in components]
        if slang_called is not None:
            slang_called.append(include_slang)
        return selected

    monkeypatch.setattr("chipcompiler.cli.inspection.env_probe.probe_environment", fake)


class TestDoctorCommand:
    def test_doctor_all_pass(self, tmp_path, capsys, monkeypatch, create_cli_project):
        project_dir = create_cli_project()
        monkeypatch.setattr(
            "chipcompiler.cli.inspection.env_probe.ALL_COMPONENTS",
            ("yosys", "ecc-tools"),
        )
        _patch_probes(
            monkeypatch,
            {
                "yosys": ProbeResult("yosys", PASS, detail="yosys"),
                "ecc-tools": ProbeResult("ecc-tools", PASS, detail="ecc-tools-bin 1.0"),
            },
        )

        rc = cli_main.run(["doctor", "--project", project_dir, "--json"])

        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        summary = data["records"][0]
        assert summary["doctor"] == "environment"
        assert summary["status"] == "ok"
        assert summary["checked"] == 2
        assert summary["failed"] == 0
        assert summary["attention"] == 0
        assert {r["component"] for r in data["records"][1:]} == {"yosys", "ecc-tools"}

    def test_doctor_required_failure_exits_nonzero(
        self, tmp_path, capsys, monkeypatch, create_cli_project
    ):
        project_dir = create_cli_project()
        monkeypatch.setattr(
            "chipcompiler.cli.inspection.env_probe.ALL_COMPONENTS",
            ("yosys",),
        )
        _patch_probes(
            monkeypatch,
            {
                "yosys": ProbeResult("yosys", FAIL, remediation="install yosys"),
            },
        )

        rc = cli_main.run(["doctor", "--project", project_dir, "--json"])

        data = json.loads(capsys.readouterr().out)
        assert rc == 1
        assert data["records"][0]["status"] == "failed"
        assert data["records"][0]["failed"] == 1
        assert data["records"][0]["attention"] == 0
        assert data["records"][1]["remediation"] == "install yosys"

    def test_doctor_optional_failure_stays_zero(
        self, tmp_path, capsys, monkeypatch, create_cli_project
    ):
        project_dir = create_cli_project()
        monkeypatch.setattr(
            "chipcompiler.cli.inspection.env_probe.ALL_COMPONENTS",
            ("klayout",),
        )
        _patch_probes(
            monkeypatch,
            {
                "klayout": ProbeResult(
                    "klayout", FAIL, required=False, remediation="pip install klayout"
                ),
            },
        )

        rc = cli_main.run(["doctor", "--project", project_dir, "--json"])

        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        summary = data["records"][0]
        assert summary["status"] == "attention"
        assert summary["failed"] == 0  # optional failure never inflates `failed`
        assert summary["attention"] == 1

    def test_doctor_without_project_skips_pdk(self, tmp_path, capsys, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            "chipcompiler.cli.inspection.env_probe.ALL_COMPONENTS",
            ("pdk",),
        )
        _patch_probes(
            monkeypatch,
            {"pdk": ProbeResult("pdk", "skip", detail="no ecc.toml")},
        )

        rc = cli_main.run(["doctor", "--json"])

        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data["records"][1]["status"] == "skip"

    def test_doctor_real_pdk_failure_names_problem(
        self, tmp_path, capsys, monkeypatch, create_cli_project
    ):
        project_dir = create_cli_project()
        monkeypatch.setattr(
            "chipcompiler.cli.inspection.env_probe.ALL_COMPONENTS",
            ("pdk",),
        )
        real_probe_pdk = env_probe.probe_pdk

        def only_pdk(components, *, cfg=None, include_slang=True):
            return [real_probe_pdk(cfg)]

        monkeypatch.setattr("chipcompiler.cli.inspection.env_probe.probe_environment", only_pdk)
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: "PDK has no liberty files",
        )

        rc = cli_main.run(["doctor", "--project", project_dir, "--json"])

        data = json.loads(capsys.readouterr().out)
        assert rc == 1
        pdk_record = data["records"][1]
        assert pdk_record["component"] == "pdk"
        assert pdk_record["status"] == "fail"
        assert pdk_record["remediation"] == "PDK has no liberty files"

    def test_doctor_skips_slang_when_yosys_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr("chipcompiler.tools.yosys.utility.get_yosys_command", lambda: [])
        monkeypatch.setattr(
            "chipcompiler.tools.yosys.utility.check_slang_support",
            lambda *args, **kwargs: pytest.fail("must not run without yosys"),
        )

        result = env_probe.probe_yosys_slang()

        assert result.status == "skip"


class TestRunPreflight:
    def test_run_blocks_when_required_tool_missing(
        self, tmp_path, capsys, monkeypatch, create_cli_project, flow_mocks
    ):
        project_dir = create_cli_project()
        monkeypatch.setattr(
            "chipcompiler.cli.inspection.env_probe.probe_environment",
            lambda components, *, cfg=None, include_slang=True: [
                ProbeResult("yosys", FAIL, remediation="install yosys")
            ],
        )

        rc = cli_main.run(["run", "--project", project_dir, "--json"])

        record = json.loads(capsys.readouterr().out)["records"][0]
        assert rc == 1
        assert record["error"] == "env_not_ready"
        assert record["preset"] == "rtl2gds"
        assert record["doctor"].startswith("ecc doctor")
        assert flow_mocks.capture["create_kwargs"] is None

    def test_run_probes_components_for_effective_preset(
        self, tmp_path, monkeypatch, create_cli_project, flow_mocks
    ):
        project_dir = create_cli_project()
        seen = {}
        monkeypatch.setattr(
            "chipcompiler.cli.inspection.env_probe.probe_components_for_preset",
            _capture_preset(seen),
        )

        rc = cli_main.run(["run", "--project", project_dir, "--preset", "syn_sta"])

        assert rc == 0
        assert seen["preset"] == "syn_sta"

    def test_preflight_components_mapping(self, monkeypatch):
        monkeypatch.setattr(
            "chipcompiler.rtl2gds.builder.build_syn_sta_flow",
            lambda: [("Synthesis", "yosys", "Unstart")],
        )
        monkeypatch.setattr(
            "chipcompiler.rtl2gds.builder.build_rtl2gds_flow",
            lambda: [
                ("Synthesis", "yosys", "Unstart"),
                ("place", "dreamplace", "Unstart"),
            ],
        )

        assert env_probe.probe_components_for_preset("syn_sta") == ("ecc-tools", "yosys")
        assert env_probe.probe_components_for_preset("rtl2gds") == (
            "ecc-tools",
            "yosys",
            "dreamplace",
        )

    def test_workspace_run_mode_never_probes(self, tmp_path, monkeypatch):
        from types import SimpleNamespace

        from chipcompiler.engine import StepRunResult

        monkeypatch.setattr(
            "chipcompiler.cli.inspection.env_probe.probe_environment",
            lambda *args, **kwargs: pytest.fail("workspace mode must not preflight"),
        )
        monkeypatch.setattr(
            "chipcompiler.data.load_workspace",
            lambda _path: SimpleNamespace(name="workspace"),
        )

        class Flow:
            def __init__(self, workspace):
                self.workspace = workspace

            def has_init(self):
                return True

            def create_step_workspaces(self, *, executable_steps=None):
                return None

        monkeypatch.setattr("chipcompiler.engine.EngineFlow", Flow)
        monkeypatch.setattr(
            "chipcompiler.engine.rerun.selected_step_names",
            lambda flow, **kwargs: ["place"],
        )
        monkeypatch.setattr(
            "chipcompiler.engine.rerun.run_resume",
            lambda flow: StepRunResult(ok=True, executed=("place",)),
        )
        monkeypatch.setattr(
            "chipcompiler.data.create_workspace",
            lambda **_kwargs: pytest.fail("workspace mode must not create a workspace"),
        )

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        rc = cli_main.run(["run", "--workspace", str(workspace), "--resume", "--json"])

        assert rc == 0


def _capture_preset(seen):
    def fake(preset):
        seen["preset"] = preset
        return ("ecc-tools",)

    return fake
