import json
import os

import pytest

from chipcompiler.cli import main as cli_main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_valid_project(tmp_path, name="gcd", pdk_root=None):
    project_dir = tmp_path / name
    project_dir.mkdir(exist_ok=True)
    (project_dir / "rtl").mkdir(exist_ok=True)
    (project_dir / "constraints").mkdir(exist_ok=True)
    (project_dir / "runs").mkdir(exist_ok=True)

    rtl_file = project_dir / "rtl" / "gcd.v"
    rtl_file.write_text("module gcd(input clk); endmodule\n")

    if pdk_root is None:
        pdk_root = tmp_path / "ics55"
        pdk_root.mkdir(exist_ok=True)

    toml = f'''[design]
name = "{name}"
top = "{name}"
rtl = ["rtl/gcd.v"]
clock_port = "clk"
frequency_mhz = 100.0

[pdk]
name = "ics55"
root = "{pdk_root}"

[flow]
preset = "rtl2gds"
run = "default"
'''
    (project_dir / "ecc.toml").write_text(toml)
    return str(project_dir)


def _create_flow_json(run_dir, steps=None):
    home = os.path.join(run_dir, "home")
    os.makedirs(home, exist_ok=True)
    if steps is None:
        steps = [
            {"name": "Synthesis", "tool": "yosys", "state": "Success", "runtime": "0:00:05"},
            {"name": "Floorplan", "tool": "ecc", "state": "Success", "runtime": "0:00:03"},
            {"name": "CTS", "tool": "ecc", "state": "Success", "runtime": "0:00:04"},
        ]
    with open(os.path.join(home, "flow.json"), "w") as f:
        json.dump({"steps": steps}, f)


def _create_step_dir(run_dir, step_name, tool, subdirs=None, files=None):
    step_dir = os.path.join(run_dir, f"{step_name}_{tool}")
    os.makedirs(step_dir, exist_ok=True)
    if subdirs:
        for sd in subdirs:
            d = os.path.join(step_dir, sd)
            os.makedirs(d, exist_ok=True)
    if files:
        for relpath, content in files.items():
            fpath = os.path.join(step_dir, relpath)
            os.makedirs(os.path.dirname(fpath), exist_ok=True)
            with open(fpath, "w") as f:
                f.write(content)
    return step_dir


def _has_disclosure(line: str) -> bool:
    return '"ecc ' in line or "=ecc " in line


def _mock_pdk_validation(monkeypatch):
    monkeypatch.setattr(
        "chipcompiler.cli.config._validate_pdk_contents",
        lambda name, root: None,
    )


# ===========================================================================
# AC-1: Run-id resolution
# ===========================================================================


class TestRunIdResolution:
    def test_status_default_run_id(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir)

        rc = cli_main.run(["status", "--run-id", "default", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "run=default" in out

    def test_status_simple_token_run_id(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "run_004")
        os.makedirs(os.path.join(run_dir, "home"), exist_ok=True)
        _create_flow_json(run_dir)

        rc = cli_main.run(["status", "--run-id", "run_004", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "run=run_004" in out

    def test_status_relative_path_run_id(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "sweeps", "sweep_001", "run_004")
        _create_flow_json(run_dir)

        rc = cli_main.run(
            ["status", "--run-id", "sweeps/sweep_001/run_004", "--project", project_dir]
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "run=sweeps/sweep_001/run_004" in out

    def test_status_absolute_path_run_id(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = tmp_path / "ecc-run-004"
        _create_flow_json(str(run_dir))

        rc = cli_main.run(
            ["status", "--run-id", str(run_dir), "--project", project_dir]
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "run=" in out

    def test_status_missing_run_id(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)

        rc = cli_main.run(["status", "--run-id", "nonexistent", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert "status=missing" in out

    def test_log_preserves_run_id(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "run_005")
        _create_flow_json(run_dir)
        _create_step_dir(run_dir, "Synthesis", "yosys", subdirs=["log"],
                         files={"log/synthesis.log": "Error: something failed\n"})

        rc = cli_main.run(
            ["log", "synthesis", "--errors", "--run-id", "run_005", "--project", project_dir]
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "--run-id run_005" in out

    def test_metrics_preserves_run_id(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "run_006")
        _create_flow_json(run_dir, [
            {"name": "CTS", "tool": "ecc", "state": "Success", "runtime": "0:00:04"},
        ])
        _create_step_dir(run_dir, "CTS", "ecc", subdirs=["analysis"],
                         files={"analysis/CTS_metrics.json": json.dumps({"Frequency [MHz]": 450.0})})

        rc = cli_main.run(
            ["metrics", "cts", "--run-id", "run_006", "--project", project_dir]
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "--run-id run_006" in out


# ===========================================================================
# AC-2: ecc artifacts
# ===========================================================================


class TestArtifacts:
    def test_artifacts_all_steps(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir)
        _create_step_dir(run_dir, "CTS", "ecc", subdirs=["output", "log"],
                         files={"output/design.def": "def content",
                                "log/cts.log": "log content"})

        rc = cli_main.run(["artifacts", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "step=cts" in out
        assert "role=output" in out
        assert "role=log" in out

    def test_artifacts_single_step(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir)
        _create_step_dir(run_dir, "CTS", "ecc", subdirs=["output"],
                         files={"output/design.def": "def content"})

        rc = cli_main.run(["artifacts", "cts", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "step=cts" in out
        assert "role=output" in out

    def test_artifacts_unknown_step(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        os.makedirs(run_dir, exist_ok=True)

        rc = cli_main.run(["artifacts", "nonexistent", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert "status=unknown_step" in out

    def test_artifacts_empty_known_step(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir)
        _create_step_dir(run_dir, "CTS", "ecc", subdirs=["output"])

        rc = cli_main.run(["artifacts", "cts", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "artifacts_status=none" in out

    def test_artifacts_json(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir)
        _create_step_dir(run_dir, "CTS", "ecc", subdirs=["output"],
                         files={"output/design.def": "def content"})

        rc = cli_main.run(["artifacts", "--json", "--project", project_dir])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert "records" in data
        assert len(data["records"]) > 0
        assert data["records"][0]["artifact"] == "design.def"

    def test_artifacts_jsonl(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir)
        _create_step_dir(run_dir, "CTS", "ecc", subdirs=["output", "log"],
                         files={"output/design.def": "def content",
                                "log/cts.log": "log content"})

        rc = cli_main.run(["artifacts", "--jsonl", "--project", project_dir])
        assert rc == 0
        objects = [json.loads(ln) for ln in capsys.readouterr().out.strip().split("\n")]
        assert len(objects) == 2
        assert all("artifact" in o for o in objects)

    def test_artifacts_with_run_id(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "sweeps", "sweep_001", "run_004")
        _create_flow_json(run_dir)
        _create_step_dir(run_dir, "CTS", "ecc", subdirs=["output"],
                         files={"output/design.def": "def content"})

        rc = cli_main.run(
            ["artifacts", "--run-id", "sweeps/sweep_001/run_004", "--project", project_dir]
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "step=cts" in out

    def test_artifacts_derives_roles_from_dirs(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir)
        _create_step_dir(run_dir, "CTS", "ecc",
                         subdirs=["config", "output", "report", "log", "analysis"],
                         files={"config/cts_config.json": "{}",
                                "output/design.def": "def",
                                "report/timing.rpt": "rpt",
                                "log/cts.log": "log",
                                "analysis/CTS_metrics.json": "{}"})

        rc = cli_main.run(["artifacts", "cts", "--json", "--project", project_dir])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        roles = {a["role"] for a in data["records"]}
        assert roles == {"config", "output", "report", "log", "analysis"}


# ===========================================================================
# AC-3: ecc config --resolved (project level)
# ===========================================================================


class TestConfigResolved:
    def test_config_resolved_project(self, tmp_path, capsys, monkeypatch):
        _mock_pdk_validation(monkeypatch)
        project_dir = _create_valid_project(tmp_path)

        rc = cli_main.run(["config", "--resolved", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "config=design.name" in out
        assert "scope=project" in out
        assert "config=pdk.name" in out
        assert "config=run_dir" in out

    def test_config_resolved_json(self, tmp_path, capsys, monkeypatch):
        _mock_pdk_validation(monkeypatch)
        project_dir = _create_valid_project(tmp_path)

        rc = cli_main.run(["config", "--resolved", "--json", "--project", project_dir])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert "records" in data
        keys = [item["config"] for item in data["records"]]
        assert "design.name" in keys
        assert "pdk.name" in keys
        assert "run_dir" in keys

    def test_config_resolved_default_run_dir_value(self, tmp_path, capsys, monkeypatch):
        _mock_pdk_validation(monkeypatch)
        project_dir = _create_valid_project(tmp_path)

        rc = cli_main.run(["config", "--resolved", "--json", "--project", project_dir])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        run_item = next(i for i in data["records"] if i["config"] == "run_dir")
        assert run_item["value"] == "runs/default"

    def test_config_resolved_jsonl(self, tmp_path, capsys, monkeypatch):
        _mock_pdk_validation(monkeypatch)
        project_dir = _create_valid_project(tmp_path)

        rc = cli_main.run(["config", "--resolved", "--jsonl", "--project", project_dir])
        assert rc == 0
        objects = [json.loads(ln) for ln in capsys.readouterr().out.strip().split("\n")]
        keys = [o["config"] for o in objects]
        assert "design.name" in keys

    def test_config_resolved_pdk_root_from_env(self, tmp_path, capsys, monkeypatch):
        _mock_pdk_validation(monkeypatch)
        pdk_root = tmp_path / "ics55_env"
        pdk_root.mkdir()
        monkeypatch.setenv("CHIPCOMPILER_ICS55_PDK_ROOT", str(pdk_root))

        project_dir = _create_valid_project(tmp_path, pdk_root="")

        rc = cli_main.run(["config", "--resolved", "--json", "--project", project_dir])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        pdk_item = next(i for i in data["records"] if i["config"] == "pdk.root")
        assert pdk_item["source"] == "env"

    def test_config_resolved_run_id(self, tmp_path, capsys, monkeypatch):
        _mock_pdk_validation(monkeypatch)
        project_dir = _create_valid_project(tmp_path)

        rc = cli_main.run(
            ["config", "--resolved", "--run-id", "sweeps/sweep_001/run_004",
             "--json", "--project", project_dir]
        )
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        run_item = next(i for i in data["records"] if i["config"] == "run_dir")
        assert run_item["value"] == "sweeps/sweep_001/run_004"

    def test_config_missing_config(self, tmp_path, capsys):
        project_dir = tmp_path / "empty_project"
        project_dir.mkdir()

        rc = cli_main.run(["config", "--resolved", "--project", str(project_dir)])
        assert rc == 1

    def test_config_requires_resolved(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)

        with pytest.raises(SystemExit):
            cli_main.run(["config", "--project", project_dir])


# ===========================================================================
# AC-4: ecc config <step> --resolved
# ===========================================================================


class TestConfigStepResolved:
    def test_config_step_lists_files(self, tmp_path, capsys, monkeypatch):
        _mock_pdk_validation(monkeypatch)
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir)
        _create_step_dir(run_dir, "CTS", "ecc", subdirs=["config"],
                         files={"config/cts_default_config.json": "{}",
                                "config/run.tcl": "echo hi"})

        rc = cli_main.run(["config", "cts", "--resolved", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "step=cts" in out
        assert "scope=step" in out
        assert "cts_default_config.json" in out

    def test_config_step_json(self, tmp_path, capsys, monkeypatch):
        _mock_pdk_validation(monkeypatch)
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir)
        _create_step_dir(run_dir, "CTS", "ecc", subdirs=["config"],
                         files={"config/cts_config.json": "{}"})

        rc = cli_main.run(["config", "cts", "--resolved", "--json", "--project", project_dir])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert "records" in data
        assert all(item["scope"] == "step" for item in data["records"])

    def test_config_step_unknown_step(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        os.makedirs(run_dir, exist_ok=True)

        rc = cli_main.run(["config", "nonexistent", "--resolved", "--project", project_dir])
        assert rc == 1

    def test_config_step_no_config_files(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir)
        _create_step_dir(run_dir, "CTS", "ecc", subdirs=["output"])

        rc = cli_main.run(["config", "cts", "--resolved", "--project", project_dir])
        assert rc == 0


# ===========================================================================
# AC-5: ecc diagnose
# ===========================================================================


class TestDiagnose:
    def test_diagnose_missing_run(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)

        rc = cli_main.run(["diagnose", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert "issue=missing_run" in out
        assert "severity=error" in out

    def test_diagnose_invalid_flow_json(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        home = os.path.join(run_dir, "home")
        os.makedirs(home, exist_ok=True)
        with open(os.path.join(home, "flow.json"), "w") as f:
            f.write("NOT VALID JSON{{{")

        rc = cli_main.run(["diagnose", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert "issue=invalid_flow_json" in out

    def test_diagnose_failed_step(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir, [
            {"name": "CTS", "tool": "ecc", "state": "Incomplete", "runtime": "0:00:04"},
        ])
        _create_step_dir(run_dir, "CTS", "ecc", subdirs=["log", "analysis"],
                         files={"log/cts.log": "Error: failed\n",
                                "analysis/CTS_metrics.json": "{}"})

        rc = cli_main.run(["diagnose", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert "issue=failed_step" in out
        assert "severity=error" in out

    def test_diagnose_ongoing_step_warning(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir, [
            {"name": "CTS", "tool": "ecc", "state": "Ongoing", "runtime": ""},
        ])
        _create_step_dir(run_dir, "CTS", "ecc", subdirs=["log", "output", "analysis", "config"],
                         files={"log/cts.log": "running\n",
                                "output/design.def": "def",
                                "analysis/CTS_metrics.json": "{}",
                                "config/cts_config.json": "{}"})

        rc = cli_main.run(["diagnose", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "issue=ongoing_step" in out
        assert "severity=warning" in out

    def test_diagnose_unstarted_step_info(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir, [
            {"name": "CTS", "tool": "ecc", "state": "Unstart", "runtime": ""},
        ])
        _create_step_dir(run_dir, "CTS", "ecc", subdirs=["log", "output", "analysis", "config"],
                         files={"log/cts.log": "",
                                "output/design.def": "def",
                                "analysis/CTS_metrics.json": "{}",
                                "config/cts_config.json": "{}"})

        rc = cli_main.run(["diagnose", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "issue=unstarted_step" in out
        assert "severity=info" in out

    def test_diagnose_log_errors_count(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir, [
            {"name": "CTS", "tool": "ecc", "state": "Success", "runtime": "0:00:04"},
        ])
        _create_step_dir(run_dir, "CTS", "ecc", subdirs=["log", "output", "analysis", "config"],
                         files={"log/cts.log": "Error: bad thing\nError: other bad\nok line\n",
                                "output/design.def": "def",
                                "analysis/CTS_metrics.json": "{}",
                                "config/cts_config.json": "{}"})

        rc = cli_main.run(["diagnose", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert "issue=log_errors" in out
        assert "count=2" in out

    def test_diagnose_missing_metrics_warning(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir, [
            {"name": "CTS", "tool": "ecc", "state": "Success", "runtime": "0:00:04"},
        ])
        _create_step_dir(run_dir, "CTS", "ecc", subdirs=["log", "output", "config"],
                         files={"log/cts.log": "ok\n",
                                "output/design.def": "def",
                                "config/cts_config.json": "{}"})

        rc = cli_main.run(["diagnose", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "issue=missing_metrics" in out
        assert "severity=warning" in out

    def test_diagnose_missing_artifacts_warning(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir, [
            {"name": "CTS", "tool": "ecc", "state": "Success", "runtime": "0:00:04"},
        ])
        _create_step_dir(run_dir, "CTS", "ecc", subdirs=["log", "analysis", "config"],
                         files={"log/cts.log": "ok\n",
                                "analysis/CTS_metrics.json": "{}",
                                "config/cts_config.json": "{}"})
        # Remove investigation role dirs to trigger missing_artifacts
        import shutil
        shutil.rmtree(os.path.join(run_dir, "CTS_ecc", "analysis"))

        rc = cli_main.run(["diagnose", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "issue=missing_artifacts" in out
        assert "severity=warning" in out

    def test_diagnose_config_unavailable_info(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir, [
            {"name": "CTS", "tool": "ecc", "state": "Success", "runtime": "0:00:04"},
        ])
        _create_step_dir(run_dir, "CTS", "ecc", subdirs=["log", "output", "analysis"],
                         files={"log/cts.log": "ok\n",
                                "output/design.def": "def",
                                "analysis/CTS_metrics.json": "{}"})

        rc = cli_main.run(["diagnose", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "issue=config_unavailable" in out
        assert "severity=info" in out

    def test_diagnose_clean_run(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir, [
            {"name": "CTS", "tool": "ecc", "state": "Success", "runtime": "0:00:04"},
        ])
        _create_step_dir(run_dir, "CTS", "ecc",
                         subdirs=["log", "output", "analysis", "config"],
                         files={"log/cts.log": "ok\n",
                                "output/design.def": "def",
                                "analysis/CTS_metrics.json": json.dumps({"Frequency [MHz]": 450.0}),
                                "config/cts_config.json": "{}"})

        rc = cli_main.run(["diagnose", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "status=clean" in out

    def test_diagnose_step_filter(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir, [
            {"name": "Synthesis", "tool": "yosys", "state": "Success", "runtime": "0:00:05"},
            {"name": "CTS", "tool": "ecc", "state": "Incomplete", "runtime": "0:00:04"},
        ])
        _create_step_dir(run_dir, "Synthesis", "yosys", subdirs=["output", "log", "analysis", "config"],
                         files={"output/synth.v": "verilog",
                                "log/synthesis.log": "ok\n",
                                "analysis/Synthesis_metrics.json": "{}",
                                "config/config.json": "{}"})
        _create_step_dir(run_dir, "CTS", "ecc", subdirs=["log"],
                         files={"log/cts.log": "Error: failed\n"})

        rc = cli_main.run(["diagnose", "cts", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert "issue=failed_step" in out
        assert "step=cts" in out
        assert "step=synthesis" not in out

    def test_diagnose_unknown_step(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir)

        rc = cli_main.run(["diagnose", "nonexistent", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert "issue=unknown_step" in out

    def test_diagnose_no_repair_suggestions(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir, [
            {"name": "CTS", "tool": "ecc", "state": "Incomplete", "runtime": "0:00:04"},
        ])
        _create_step_dir(run_dir, "CTS", "ecc", subdirs=["log"],
                         files={"log/cts.log": "Error: failed\n"})

        rc = cli_main.run(["diagnose", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert "suggest" not in out.lower()
        assert "fix" not in out.lower()
        assert "recommend" not in out.lower()

    def test_diagnose_json(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir, [
            {"name": "CTS", "tool": "ecc", "state": "Incomplete", "runtime": "0:00:04"},
        ])
        _create_step_dir(run_dir, "CTS", "ecc", subdirs=["log"],
                         files={"log/cts.log": "Error: failed\n"})

        rc = cli_main.run(["diagnose", "--json", "--project", project_dir])
        assert rc == 1
        data = json.loads(capsys.readouterr().out)
        assert "records" in data
        assert any(i["issue"] == "failed_step" for i in data["records"])

    def test_diagnose_jsonl(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir, [
            {"name": "CTS", "tool": "ecc", "state": "Incomplete", "runtime": "0:00:04"},
        ])
        _create_step_dir(run_dir, "CTS", "ecc", subdirs=["log"],
                         files={"log/cts.log": "Error: failed\n"})

        rc = cli_main.run(["diagnose", "--jsonl", "--project", project_dir])
        assert rc == 1
        objects = [json.loads(ln) for ln in capsys.readouterr().out.strip().split("\n")]
        assert any(o["issue"] == "failed_step" for o in objects)

    def test_diagnose_with_run_id(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "run_007")
        _create_flow_json(run_dir, [
            {"name": "CTS", "tool": "ecc", "state": "Success", "runtime": "0:00:04"},
        ])
        _create_step_dir(run_dir, "CTS", "ecc",
                         subdirs=["log", "output", "analysis", "config"],
                         files={"log/cts.log": "ok\n",
                                "output/design.def": "def",
                                "analysis/CTS_metrics.json": "{}",
                                "config/cts_config.json": "{}"})

        rc = cli_main.run(
            ["diagnose", "--run-id", "run_007", "--project", project_dir]
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "status=clean" in out


# ===========================================================================
# AC-6: Diagnose exit codes
# ===========================================================================


class TestDiagnoseExitCodes:
    def test_error_issue_returns_nonzero(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir, [
            {"name": "CTS", "tool": "ecc", "state": "Incomplete", "runtime": "0:00:04"},
        ])
        _create_step_dir(run_dir, "CTS", "ecc", subdirs=["log"],
                         files={"log/cts.log": "Error: failed\n"})

        rc = cli_main.run(["diagnose", "--project", project_dir])
        assert rc == 1

    def test_warning_only_returns_zero(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir, [
            {"name": "CTS", "tool": "ecc", "state": "Ongoing", "runtime": ""},
        ])
        _create_step_dir(run_dir, "CTS", "ecc",
                         subdirs=["log", "output", "analysis", "config"],
                         files={"log/cts.log": "running\n",
                                "output/design.def": "def",
                                "analysis/CTS_metrics.json": "{}",
                                "config/cts_config.json": "{}"})

        rc = cli_main.run(["diagnose", "--project", project_dir])
        assert rc == 0

    def test_clean_run_returns_zero(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir, [
            {"name": "CTS", "tool": "ecc", "state": "Success", "runtime": "0:00:04"},
        ])
        _create_step_dir(run_dir, "CTS", "ecc",
                         subdirs=["log", "output", "analysis", "config"],
                         files={"log/cts.log": "ok\n",
                                "output/design.def": "def",
                                "analysis/CTS_metrics.json": "{}",
                                "config/cts_config.json": "{}"})

        rc = cli_main.run(["diagnose", "--project", project_dir])
        assert rc == 0

    def test_failed_step_not_zero(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir, [
            {"name": "CTS", "tool": "ecc", "state": "Incomplete", "runtime": "0:00:04"},
        ])
        _create_step_dir(run_dir, "CTS", "ecc")

        rc = cli_main.run(["diagnose", "--project", project_dir])
        assert rc != 0


# ===========================================================================
# AC-7: Disclosure commands in Phase 2 output
# ===========================================================================


class TestDisclosure:
    def test_artifacts_lines_have_disclosure(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir)
        _create_step_dir(run_dir, "CTS", "ecc", subdirs=["output"],
                         files={"output/design.def": "def content"})

        rc = cli_main.run(["artifacts", "cts", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        for line in out.strip().split("\n"):
            if line.strip():
                assert _has_disclosure(line), f"Missing disclosure in: {line}"

    def test_config_resolved_lines_have_disclosure(self, tmp_path, capsys, monkeypatch):
        _mock_pdk_validation(monkeypatch)
        project_dir = _create_valid_project(tmp_path)

        rc = cli_main.run(["config", "--resolved", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        for line in out.strip().split("\n"):
            if line.strip():
                assert _has_disclosure(line), f"Missing disclosure in: {line}"

    def test_diagnose_lines_have_disclosure(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)

        rc = cli_main.run(["diagnose", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        for line in out.strip().split("\n"):
            if line.strip():
                assert _has_disclosure(line), f"Missing disclosure in: {line}"

    def test_phase2_disclosure_preserves_run_id(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "run_008")
        _create_flow_json(run_dir, [
            {"name": "CTS", "tool": "ecc", "state": "Incomplete", "runtime": "0:00:04"},
        ])
        _create_step_dir(run_dir, "CTS", "ecc", subdirs=["log"],
                         files={"log/cts.log": "Error: fail\n"})

        rc = cli_main.run(
            ["diagnose", "--run-id", "run_008", "--project", project_dir]
        )
        assert rc == 1
        out = capsys.readouterr().out
        assert "--run-id run_008" in out

    def test_artifacts_disclosure_preserves_project(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir)
        _create_step_dir(run_dir, "CTS", "ecc", subdirs=["output"],
                         files={"output/design.def": "def content"})

        rc = cli_main.run(["artifacts", "cts", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert f"--project {project_dir}" in out


# ===========================================================================
# AC-8: Read-only and CLI-local
# ===========================================================================


class TestReadOnly:
    def test_artifacts_does_not_modify_files(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir)
        _create_step_dir(run_dir, "CTS", "ecc", subdirs=["output"],
                         files={"output/design.def": "original"})

        before_mtime = os.path.getmtime(
            os.path.join(run_dir, "CTS_ecc", "output", "design.def")
        )

        rc = cli_main.run(["artifacts", "--project", project_dir])
        assert rc == 0

        after_mtime = os.path.getmtime(
            os.path.join(run_dir, "CTS_ecc", "output", "design.def")
        )
        assert before_mtime == after_mtime

    def test_no_persistent_metadata_files(self, tmp_path, capsys, monkeypatch):
        _mock_pdk_validation(monkeypatch)
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir)
        _create_step_dir(run_dir, "CTS", "ecc", subdirs=["output"],
                         files={"output/design.def": "def content"})

        cli_main.run(["artifacts", "--project", project_dir])
        cli_main.run(["config", "--resolved", "--project", project_dir])
        cli_main.run(["diagnose", "--project", project_dir])

        assert not os.path.exists(os.path.join(project_dir, "issues.json"))
        assert not os.path.exists(os.path.join(project_dir, "artifacts.json"))
        assert not os.path.exists(os.path.join(project_dir, "resolved_config.json"))
        assert not os.path.exists(os.path.join(run_dir, "issues.json"))
        assert not os.path.exists(os.path.join(run_dir, "artifacts.json"))


# ===========================================================================
# Regression tests for Codex review findings (Round 1)
# ===========================================================================


class TestRunIdDisclosure:
    def test_explicit_default_preserved_in_disclosure(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir)

        rc = cli_main.run(["status", "--run-id", "default", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "--run-id default" in out

    def test_project_relative_run_id_resolves(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "sweeps", "sweep_001", "run_004")
        _create_flow_json(run_dir)

        rc = cli_main.run(
            ["status", "--run-id", "sweeps/sweep_001/run_004", "--project", project_dir]
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "run=sweeps/sweep_001/run_004" in out


class TestArtifactPaths:
    def test_nested_run_artifact_paths(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "sweeps", "sweep_001", "run_004")
        _create_flow_json(run_dir)
        _create_step_dir(run_dir, "CTS", "ecc", subdirs=["output"],
                         files={"output/design.def": "def content"})

        rc = cli_main.run(
            ["artifacts", "--run-id", "sweeps/sweep_001/run_004",
             "--json", "--project", project_dir]
        )
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert len(data["records"]) == 1
        path = data["records"][0]["path"]
        assert path.startswith("sweeps/")

    def test_nested_run_step_config_paths(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "sweeps", "sweep_001", "run_004")
        _create_flow_json(run_dir)
        _create_step_dir(run_dir, "CTS", "ecc", subdirs=["config"],
                         files={"config/cts_config.json": "{}"})

        rc = cli_main.run(
            ["config", "cts", "--resolved", "--run-id", "sweeps/sweep_001/run_004",
             "--json", "--project", project_dir]
        )
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert "records" in data
        path = data["records"][0]["path"]


class TestEmptyStepConfigSentinel:
    def test_step_no_config_emits_sentinel_text(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir)
        _create_step_dir(run_dir, "CTS", "ecc", subdirs=["output"])

        rc = cli_main.run(["config", "cts", "--resolved", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "step=cts" in out
        assert "config_status=none" in out
        assert "artifacts=" in out

    def test_step_no_config_emits_sentinel_json(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir)
        _create_step_dir(run_dir, "CTS", "ecc", subdirs=["output"])

        rc = cli_main.run(["config", "cts", "--resolved", "--json", "--project", project_dir])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["records"][0]["step"] == "cts"
        assert data["records"][0]["config_status"] == "none"


class TestDiagnoseFlowOnlySteps:
    def test_flow_step_without_directory_emits_issues(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir, [
            {"name": "CTS", "tool": "ecc", "state": "Incomplete", "runtime": "0:00:04"},
        ])

        rc = cli_main.run(["diagnose", "cts", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert "issue=failed_step" in out
        assert "step=cts" in out
        assert "issue=unknown_step" not in out

    def test_flow_step_without_dir_reports_missing_artifacts(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir, [
            {"name": "CTS", "tool": "ecc", "state": "Success", "runtime": "0:00:04"},
        ])

        rc = cli_main.run(["diagnose", "cts", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "issue=missing_artifacts" in out
        assert "issue=missing_metrics" in out
        assert "issue=config_unavailable" in out


class TestConfigRoleDisclosure:
    def test_config_artifact_has_disclosure(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir)
        _create_step_dir(run_dir, "CTS", "ecc", subdirs=["config"],
                         files={"config/cts_config.json": "{}"})

        rc = cli_main.run(["artifacts", "cts", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        for line in out.strip().split("\n"):
            if line.strip():
                assert _has_disclosure(line), f"Missing disclosure in: {line}"


# ===========================================================================
# Regression tests for Codex Round 2 findings (Round 3)
# ===========================================================================


class TestAbsoluteRunIdConfig:
    def test_absolute_run_id_preserves_run_dir_value(self, tmp_path, capsys, monkeypatch):
        _mock_pdk_validation(monkeypatch)
        project_dir = _create_valid_project(tmp_path)
        external_run = tmp_path / "external_run"
        _create_flow_json(str(external_run))

        rc = cli_main.run(
            ["config", "--resolved", "--run-id", str(external_run),
             "--json", "--project", project_dir]
        )
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        run_item = next(i for i in data["records"] if i["config"] == "run_dir")
        assert run_item["value"] == str(external_run)


class TestConfigTextUsesItemInspectCmd:
    def test_run_dir_text_uses_status_command(self, tmp_path, capsys, monkeypatch):
        _mock_pdk_validation(monkeypatch)
        project_dir = _create_valid_project(tmp_path)

        rc = cli_main.run(["config", "--resolved", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        run_dir_line = [l for l in out.strip().split("\n") if "config=run_dir" in l][0]
        assert "ecc status" in run_dir_line
        assert "ecc config --resolved --json" not in run_dir_line


class TestDiagnoseIssueSpecificEvidence:
    def test_log_errors_uses_log_command(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir, [
            {"name": "CTS", "tool": "ecc", "state": "Success", "runtime": "0:00:04"},
        ])
        _create_step_dir(run_dir, "CTS", "ecc",
                         subdirs=["log", "output", "analysis", "config"],
                         files={"log/cts.log": "Error: bad thing\nError: other\nok\n",
                                "output/design.def": "def",
                                "analysis/CTS_metrics.json": "{}",
                                "config/cts_config.json": "{}"})

        rc = cli_main.run(["diagnose", "cts", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        log_errors_line = [l for l in out.strip().split("\n") if "issue=log_errors" in l][0]
        assert "ecc log cts --errors" in log_errors_line

    def test_missing_metrics_uses_metrics_command(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir, [
            {"name": "CTS", "tool": "ecc", "state": "Success", "runtime": "0:00:04"},
        ])
        _create_step_dir(run_dir, "CTS", "ecc",
                         subdirs=["log", "output", "config"],
                         files={"log/cts.log": "ok\n",
                                "output/design.def": "def",
                                "config/cts_config.json": "{}"})

        rc = cli_main.run(["diagnose", "cts", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        metrics_line = [l for l in out.strip().split("\n") if "issue=missing_metrics" in l][0]
        assert "ecc metrics cts --json" in metrics_line

    def test_missing_artifacts_uses_artifacts_command(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir, [
            {"name": "CTS", "tool": "ecc", "state": "Success", "runtime": "0:00:04"},
        ])
        _create_step_dir(run_dir, "CTS", "ecc",
                         subdirs=["log", "config"],
                         files={"log/cts.log": "ok\n",
                                "config/cts_config.json": "{}"})

        rc = cli_main.run(["diagnose", "cts", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "issue=missing_artifacts" in out
        artifacts_lines = [l for l in out.strip().split("\n") if "issue=missing_artifacts" in l]
        assert len(artifacts_lines) > 0
        assert "ecc artifacts cts" in artifacts_lines[0]

    def test_config_unavailable_uses_config_command(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir, [
            {"name": "CTS", "tool": "ecc", "state": "Success", "runtime": "0:00:04"},
        ])
        _create_step_dir(run_dir, "CTS", "ecc",
                         subdirs=["log", "output", "analysis"],
                         files={"log/cts.log": "ok\n",
                                "output/design.def": "def",
                                "analysis/CTS_metrics.json": "{}"})

        rc = cli_main.run(["diagnose", "cts", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        config_line = [l for l in out.strip().split("\n") if "issue=config_unavailable" in l][0]
        assert "ecc config cts --resolved" in config_line

    def test_invalid_flow_json_has_evidence(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        os.makedirs(os.path.join(run_dir, "home"), exist_ok=True)
        with open(os.path.join(run_dir, "home", "flow.json"), "w") as f:
            f.write("NOT VALID JSON{{{")

        rc = cli_main.run(["diagnose", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert "issue=invalid_flow_json" in out
        assert "evidence=" in out
        assert "ecc status" in out

    def test_invalid_flow_json_json_has_evidence(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        os.makedirs(os.path.join(run_dir, "home"), exist_ok=True)
        with open(os.path.join(run_dir, "home", "flow.json"), "w") as f:
            f.write("NOT VALID JSON{{{")

        rc = cli_main.run(["diagnose", "--json", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        data = json.loads(out)
        issue = data["records"][0]
        assert issue["issue"] == "invalid_flow_json"
        assert "evidence" in issue
        assert "run_cmd" in issue


class TestCleanDiagnoseOutput:
    def test_clean_has_status_and_disclosure_commands(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir, [
            {"name": "CTS", "tool": "ecc", "state": "Success", "runtime": "0:00:04"},
        ])
        _create_step_dir(run_dir, "CTS", "ecc",
                         subdirs=["log", "output", "analysis", "config"],
                         files={"log/cts.log": "ok\n",
                                "output/design.def": "def",
                                "analysis/CTS_metrics.json": "{}",
                                "config/cts_config.json": "{}"})

        rc = cli_main.run(["diagnose", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "status=clean" in out
        assert "status_cmd=" in out
        assert "artifacts=" in out
        assert "config=" in out

    def test_clean_json_has_disclosure_metadata(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir, [
            {"name": "CTS", "tool": "ecc", "state": "Success", "runtime": "0:00:04"},
        ])
        _create_step_dir(run_dir, "CTS", "ecc",
                         subdirs=["log", "output", "analysis", "config"],
                         files={"log/cts.log": "ok\n",
                                "output/design.def": "def",
                                "analysis/CTS_metrics.json": "{}",
                                "config/cts_config.json": "{}"})

        rc = cli_main.run(["diagnose", "--json", "--project", project_dir])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["records"][0]["status"] == "clean"
        assert "status_cmd" in data["records"][0]
        assert "artifacts" in data["records"][0]
        assert "config" in data["records"][0]


class TestConfigJsonDisclosure:
    def test_project_config_json_has_inspect_cmd(self, tmp_path, capsys, monkeypatch):
        _mock_pdk_validation(monkeypatch)
        project_dir = _create_valid_project(tmp_path)

        rc = cli_main.run(["config", "--resolved", "--json", "--project", project_dir])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        for item in data["records"]:
            assert "inspect" in item, f"Missing inspect in item: {item['config']}"


class TestIsolatedConfigValidation:
    @staticmethod
    def _valid_toml(tmp_path, **overrides):
        pdk_dir = tmp_path / "pdk"
        pdk_dir.mkdir(exist_ok=True)
        rtl_dir = tmp_path / "rtl"
        rtl_dir.mkdir(exist_ok=True)
        (rtl_dir / "gcd.v").write_text("module gcd; endmodule")
        defaults = {
            "name": "gcd", "top": "gcd", "rtl": '["rtl/gcd.v"]',
            "clock_port": "clk", "frequency_mhz": "100.0",
            "pdk_name": "ics55", "pdk_root": str(pdk_dir),
            "flow_preset": "rtl2gds", "flow_run": "default",
        }
        defaults.update(overrides)
        return f'''[design]
name = "{defaults['name']}"
top = "{defaults['top']}"
rtl = {defaults['rtl']}
clock_port = "{defaults['clock_port']}"
frequency_mhz = {defaults['frequency_mhz']}

[pdk]
name = "{defaults['pdk_name']}"
root = "{defaults['pdk_root']}"

[flow]
preset = "{defaults['flow_preset']}"
run = "{defaults['flow_run']}"
'''

    def test_unsupported_flow_run_rejected(self, tmp_path, capsys, monkeypatch):
        _mock_pdk_validation(monkeypatch)
        project_dir = tmp_path / "bad_run"
        project_dir.mkdir()
        toml = self._valid_toml(tmp_path, flow_run="custom")
        (project_dir / "ecc.toml").write_text(toml)
        rc = cli_main.run(["config", "--resolved", "--project", str(project_dir)])
        assert rc == 1

    def test_empty_clock_port_rejected(self, tmp_path, capsys, monkeypatch):
        _mock_pdk_validation(monkeypatch)
        project_dir = tmp_path / "bad_clock"
        project_dir.mkdir()
        toml = self._valid_toml(tmp_path, clock_port="")
        (project_dir / "ecc.toml").write_text(toml)
        rc = cli_main.run(["config", "--resolved", "--project", str(project_dir)])
        assert rc == 1

    def test_zero_frequency_rejected(self, tmp_path, capsys, monkeypatch):
        _mock_pdk_validation(monkeypatch)
        project_dir = tmp_path / "bad_freq"
        project_dir.mkdir()
        toml = self._valid_toml(tmp_path, frequency_mhz="0")
        (project_dir / "ecc.toml").write_text(toml)
        rc = cli_main.run(["config", "--resolved", "--project", str(project_dir)])
        assert rc == 1

    def test_empty_rtl_rejected(self, tmp_path, capsys, monkeypatch):
        _mock_pdk_validation(monkeypatch)
        project_dir = tmp_path / "bad_rtl"
        project_dir.mkdir()
        toml = self._valid_toml(tmp_path, rtl="[]")
        (project_dir / "ecc.toml").write_text(toml)
        rc = cli_main.run(["config", "--resolved", "--project", str(project_dir)])
        assert rc == 1


# ===========================================================================
# Regression tests for Codex Round 4 code review (Round 5)
# ===========================================================================


class TestCorruptFlowJson:
    def test_corrupt_flow_json_status_reports_corrupt(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        os.makedirs(os.path.join(run_dir, "home"), exist_ok=True)
        with open(os.path.join(run_dir, "home", "flow.json"), "w") as f:
            f.write("BROKEN{{{")
        rc = cli_main.run(["status", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert "corrupt" in out

    def test_missing_flow_json_status_reports_missing(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        os.makedirs(run_dir, exist_ok=True)
        rc = cli_main.run(["status", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert "missing" in out

    def test_corrupt_flow_json_json_reports_corrupt(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        os.makedirs(os.path.join(run_dir, "home"), exist_ok=True)
        with open(os.path.join(run_dir, "home", "flow.json"), "w") as f:
            f.write("BROKEN{{{")
        rc = cli_main.run(["status", "--json", "--project", project_dir])
        assert rc == 1
        data = json.loads(capsys.readouterr().out)
        assert data["records"][0]["status"] == "corrupt"


class TestCorruptMetricsJson:
    def test_malformed_metrics_reports_corrupt_text(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir, [
            {"name": "CTS", "tool": "ecc", "state": "Success", "runtime": "0:00:04"},
        ])
        _create_step_dir(run_dir, "CTS", "ecc",
                         subdirs=["analysis"],
                         files={"analysis/CTS_metrics.json": "NOT JSON{{{"})
        rc = cli_main.run(["metrics", "cts", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert "corrupt" in out

    def test_malformed_metrics_reports_corrupt_json(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir, [
            {"name": "CTS", "tool": "ecc", "state": "Success", "runtime": "0:00:04"},
        ])
        _create_step_dir(run_dir, "CTS", "ecc",
                         subdirs=["analysis"],
                         files={"analysis/CTS_metrics.json": "NOT JSON{{{"})
        rc = cli_main.run(["metrics", "cts", "--json", "--project", project_dir])
        assert rc == 1
        data = json.loads(capsys.readouterr().out)
        assert data["records"][0]["status"] == "corrupt"


class TestRtlPathResolution:
    def test_absolute_rtl_resolved_correctly(self, tmp_path, capsys, monkeypatch):
        _mock_pdk_validation(monkeypatch)
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        rtl_dir = tmp_path / "external_rtl"
        rtl_dir.mkdir()
        (rtl_dir / "gcd.v").write_text("module gcd; endmodule")
        (project_dir / "ecc.toml").write_text(f'''[design]
name = "gcd"
top = "gcd"
rtl = ["{rtl_dir / "gcd.v"}"]
clock_port = "clk"
frequency_mhz = 100.0

[pdk]
name = "ics55"
root = "{tmp_path / "pdk"}"

[flow]
preset = "rtl2gds"
run = "default"
''')
        (tmp_path / "pdk").mkdir(exist_ok=True)
        rc = cli_main.run(["config", "--resolved", "--json", "--project", str(project_dir)])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        rtl_item = next(i for i in data["records"] if i["config"] == "design.rtl.0")
        assert rtl_item["resolved"] == str(rtl_dir / "gcd.v")


# ===========================================================================
# Regression tests for Codex Round 5 code review (Round 6)
# ===========================================================================


class TestPendingStepDiagnose:
    def test_pending_step_creates_issue(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir, [
            {"name": "CTS", "tool": "ecc", "state": "Pending", "runtime": ""},
        ])
        _create_step_dir(run_dir, "CTS", "ecc",
                         subdirs=["log", "output", "analysis", "config"],
                         files={"log/cts.log": "ok\n",
                                "output/design.def": "def",
                                "analysis/CTS_metrics.json": '{"freq": 100}',
                                "config/cts_config.json": "{}"})

        rc = cli_main.run(["diagnose", "cts", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "issue=pending_step" in out
        assert "status=pending" in out


class TestMissingRunJsonlKind:
    def test_missing_run_jsonl_has_kind(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        os.makedirs(run_dir, exist_ok=True)

        rc = cli_main.run(["status", "--jsonl", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        data = [json.loads(line) for line in out.strip().split("\n") if line.strip()]
        assert data[0]["run"] == "default"
        assert data[0]["status"] == "missing"


class TestLogErrorMatching:
    def test_clean_summary_not_counted_as_error(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir, [
            {"name": "CTS", "tool": "ecc", "state": "Success", "runtime": "0:00:04"},
        ])
        _create_step_dir(run_dir, "CTS", "ecc",
                         subdirs=["log", "output", "analysis", "config"],
                         files={"log/cts.log": "CTS completed successfully\n0 errors\nNo errors found\n0 failed checks\n",
                                "output/design.def": "def",
                                "analysis/CTS_metrics.json": '{"freq": 100}',
                                "config/cts_config.json": "{}"})

        rc = cli_main.run(["diagnose", "cts", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "log_errors" not in out

    def test_real_errors_still_detected(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir, [
            {"name": "CTS", "tool": "ecc", "state": "Success", "runtime": "0:00:04"},
        ])
        _create_step_dir(run_dir, "CTS", "ecc",
                         subdirs=["log", "output", "analysis", "config"],
                         files={"log/cts.log": "CTS completed\nError: bad thing\nTraceback (most recent call):\n0 errors\n",
                                "output/design.def": "def",
                                "analysis/CTS_metrics.json": '{"freq": 100}',
                                "config/cts_config.json": "{}"})

        rc = cli_main.run(["diagnose", "cts", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert "issue=log_errors" in out
        assert "count=2" in out

