import json
import os
import re
from types import SimpleNamespace

import pytest

from chipcompiler.cli import main as cli_main

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class DummyFlow:
    has_init_value = False
    run_steps_value = True
    instances = []

    def __init__(self, workspace):
        self.workspace = workspace
        self.added_steps = []
        self.create_called = False
        self.run_called = False
        self.workspace_steps = []
        DummyFlow.instances.append(self)

    def has_init(self):
        return self.has_init_value

    def add_step(self, step, tool, state):
        self.added_steps.append((step, tool, state))

    def create_step_workspaces(self):
        self.create_called = True

    def run_steps(self):
        self.run_called = True
        return self.run_steps_value

    def run_step(self, workspace_step):
        from chipcompiler.data import StateEnum
        self.run_called = True
        return StateEnum.Success if self.run_steps_value else StateEnum.Imcomplete


def _install_flow_mocks(monkeypatch):
    capture = {"create_kwargs": None}
    workspace_obj = SimpleNamespace(name="workspace")

    DummyFlow.instances = []
    DummyFlow.has_init_value = False
    DummyFlow.run_steps_value = True

    def fake_create_workspace(**kwargs):
        capture["create_kwargs"] = kwargs
        return workspace_obj

    monkeypatch.setattr("chipcompiler.data.create_workspace", fake_create_workspace)
    monkeypatch.setattr("chipcompiler.engine.EngineFlow", DummyFlow)
    monkeypatch.setattr(
        "chipcompiler.rtl2gds.build_rtl2gds_flow",
        lambda: [("Synthesis", "yosys", "Unstart")],
    )
    monkeypatch.setattr(
        "chipcompiler.cli.config._validate_pdk_contents",
        lambda name, root: None,
    )

    return capture


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
            {"name": "Synthesis", "tool": "yosys", "state": "Success", "runtime": "0:00:18"},
            {"name": "Floorplan", "tool": "ecc", "state": "Success", "runtime": "0:00:04"},
        ]
    with open(os.path.join(home, "flow.json"), "w") as f:
        json.dump({"steps": steps}, f)


def _has_disclosure(line):
    return bool(re.search(r'\w+="ecc ', line))


# ===========================================================================
# AC-1: ecc init
# ===========================================================================


class TestInit:
    def test_init_creates_skeleton(self, tmp_path):
        project_path = str(tmp_path / "gcd")
        rc = cli_main.run(["init", project_path])
        assert rc == 0

        assert (tmp_path / "gcd" / "ecc.toml").exists()
        assert (tmp_path / "gcd" / "rtl").is_dir()
        assert (tmp_path / "gcd" / "constraints").is_dir()
        assert (tmp_path / "gcd" / "runs").is_dir()

    def test_init_output_has_disclosure_commands(self, tmp_path, capsys):
        project_path = str(tmp_path / "myproj")
        rc = cli_main.run(["init", project_path])
        assert rc == 0
        out = capsys.readouterr().out
        assert 'check="ecc check' in out
        assert 'run="ecc run' in out

    def test_init_fails_if_ecc_toml_exists(self, tmp_path):
        project_dir = tmp_path / "gcd"
        project_dir.mkdir()
        (project_dir / "ecc.toml").write_text("[design]\n")
        rc = cli_main.run(["init", str(project_dir)])
        assert rc == 1

    def test_init_rejects_empty_name(self):
        rc = cli_main.run(["init", ""])
        assert rc == 1

    def test_init_uses_basename_for_design_name(self, tmp_path):
        project_path = str(tmp_path / "subdir" / "mydesign")
        rc = cli_main.run(["init", project_path])
        assert rc == 0
        toml = (tmp_path / "subdir" / "mydesign" / "ecc.toml").read_text()
        assert 'name = "mydesign"' in toml
        assert "rtl/mydesign.v" in toml


# ===========================================================================
# AC-2: ecc check
# ===========================================================================


class TestCheck:
    def test_check_passes_valid_config(self, tmp_path, monkeypatch, capsys):
        project_dir = _create_valid_project(tmp_path)
        monkeypatch.setattr(
            "chipcompiler.cli.config._validate_pdk_contents",
            lambda name, root: None,
        )
        rc = cli_main.run(["check", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "status=checked" in out

    def test_check_from_inside_project_dir(self, tmp_path, monkeypatch, capsys):
        project_dir = _create_valid_project(tmp_path)
        monkeypatch.setattr(
            "chipcompiler.cli.config._validate_pdk_contents",
            lambda name, root: None,
        )
        monkeypatch.chdir(project_dir)
        rc = cli_main.run(["check"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "status=checked" in out

    def test_check_fails_missing_ecc_toml(self, tmp_path):
        rc = cli_main.run(["check", "--project", str(tmp_path)])
        assert rc == 1

    def test_check_fails_malformed_toml(self, tmp_path, capsys):
        project_dir = tmp_path / "bad"
        project_dir.mkdir()
        (project_dir / "ecc.toml").write_text("[design\ninvalid {{{")
        rc = cli_main.run(["check", "--project", str(project_dir)])
        assert rc == 1

    def test_check_fails_missing_rtl(self, tmp_path):
        project_dir = _create_valid_project(tmp_path)
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path, "w") as f:
            f.write(
                '[design]\nname="gcd"\ntop="gcd"\nrtl=["rtl/missing.v"]\n'
                'clock_port="clk"\nfrequency_mhz=100\n'
                '[pdk]\nname="ics55"\nroot=""\n'
                '[flow]\npreset="rtl2gds"\nrun="default"\n',
            )
        rc = cli_main.run(["check", "--project", project_dir])
        assert rc == 1

    def test_check_fails_empty_pdk_root(self, tmp_path):
        project_dir = _create_valid_project(tmp_path, pdk_root="")
        rc = cli_main.run(["check", "--project", project_dir])
        assert rc == 1

    def test_check_fails_non_directory_pdk_root(self, tmp_path):
        pdk_root = tmp_path / "ics55.txt"
        pdk_root.write_text("not a dir")
        project_dir = _create_valid_project(tmp_path, pdk_root=str(pdk_root))
        rc = cli_main.run(["check", "--project", project_dir])
        assert rc == 1

    def test_check_fails_unsupported_pdk(self, tmp_path):
        project_dir = _create_valid_project(tmp_path)
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content = content.replace('name = "ics55"', 'name = "unsupported"')
        with open(toml_path, "w") as f:
            f.write(content)
        rc = cli_main.run(["check", "--project", project_dir])
        assert rc == 1

    def test_check_fails_unsupported_preset(self, tmp_path):
        project_dir = _create_valid_project(tmp_path)
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content = content.replace('preset = "rtl2gds"', 'preset = "unknown"')
        with open(toml_path, "w") as f:
            f.write(content)
        rc = cli_main.run(["check", "--project", project_dir])
        assert rc == 1

    def test_check_fails_non_positive_frequency(self, tmp_path):
        project_dir = _create_valid_project(tmp_path)
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content = content.replace("frequency_mhz = 100.0", "frequency_mhz = -10")
        with open(toml_path, "w") as f:
            f.write(content)
        rc = cli_main.run(["check", "--project", project_dir])
        assert rc == 1

    def test_check_fails_multiple_rtl(self, tmp_path):
        project_dir = _create_valid_project(tmp_path)
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content = content.replace(
            'rtl = ["rtl/gcd.v"]',
            'rtl = ["rtl/a.v", "rtl/b.v"]',
        )
        with open(toml_path, "w") as f:
            f.write(content)
        rc = cli_main.run(["check", "--project", project_dir])
        assert rc == 1

    def test_check_fails_non_numeric_frequency(self, tmp_path):
        project_dir = _create_valid_project(tmp_path)
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content = content.replace("frequency_mhz = 100.0", 'frequency_mhz = "fast"')
        with open(toml_path, "w") as f:
            f.write(content)
        rc = cli_main.run(["check", "--project", project_dir])
        assert rc == 1

    def test_check_json_output(self, tmp_path, monkeypatch, capsys):
        project_dir = _create_valid_project(tmp_path)
        monkeypatch.setattr(
            "chipcompiler.cli.config._validate_pdk_contents",
            lambda name, root: None,
        )
        rc = cli_main.run(["check", "--project", project_dir, "--json"])
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "records" in data
        assert data["records"][0]["status"] == "checked"
        assert data["records"][0]["project"] == "gcd"


# ===========================================================================
# AC-3: ecc run
# ===========================================================================


class TestRun:
    def test_run_calls_create_workspace(self, tmp_path, monkeypatch):
        project_dir = _create_valid_project(tmp_path)
        capture = _install_flow_mocks(monkeypatch)

        rc = cli_main.run(["run", "--project", project_dir])
        assert rc == 0
        assert capture["create_kwargs"]["directory"] == os.path.join(
            project_dir, "runs", "default"
        )

    def test_run_adds_flow_steps_when_no_init(self, tmp_path, monkeypatch):
        project_dir = _create_valid_project(tmp_path)
        _install_flow_mocks(monkeypatch)

        rc = cli_main.run(["run", "--project", project_dir])
        assert rc == 0
        assert len(DummyFlow.instances[0].added_steps) > 0

    def test_run_calls_create_and_run(self, tmp_path, monkeypatch):
        project_dir = _create_valid_project(tmp_path)
        _install_flow_mocks(monkeypatch)

        rc = cli_main.run(["run", "--project", project_dir])
        assert rc == 0
        assert DummyFlow.instances[0].create_called
        assert DummyFlow.instances[0].run_called

    def test_run_overwrite_removes_existing(self, tmp_path, monkeypatch):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir)
        _install_flow_mocks(monkeypatch)

        rc = cli_main.run(["run", "--project", project_dir, "--overwrite"])
        assert rc == 0

    def test_run_fails_if_flow_json_exists(self, tmp_path):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir)

        rc = cli_main.run(["run", "--project", project_dir])
        assert rc == 1

    def test_run_fails_on_config_error(self, tmp_path):
        project_dir = tmp_path / "bad"
        project_dir.mkdir()
        (project_dir / "ecc.toml").write_text("[design]\n")
        rc = cli_main.run(["run", "--project", str(project_dir)])
        assert rc == 1

    def test_run_fails_when_create_workspace_returns_none(self, tmp_path, monkeypatch):
        project_dir = _create_valid_project(tmp_path)
        _install_flow_mocks(monkeypatch)

        def fake_create(**kwargs):
            return None

        monkeypatch.setattr("chipcompiler.data.create_workspace", fake_create)
        rc = cli_main.run(["run", "--project", project_dir])
        assert rc == 1

    def test_run_fails_when_run_steps_false(self, tmp_path, monkeypatch):
        project_dir = _create_valid_project(tmp_path)
        _install_flow_mocks(monkeypatch)
        DummyFlow.run_steps_value = False

        rc = cli_main.run(["run", "--project", project_dir])
        assert rc == 1

    def test_run_json_uses_non_progress_path(self, tmp_path, monkeypatch, capsys):
        project_dir = _create_valid_project(tmp_path)
        _install_flow_mocks(monkeypatch)

        rc = cli_main.run(["run", "--project", project_dir, "--json"])
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "records" in data
        assert data["records"][0]["status"] == "success"
        assert DummyFlow.instances[0].run_called

    def test_run_jsonl_uses_non_progress_path(self, tmp_path, monkeypatch, capsys):
        project_dir = _create_valid_project(tmp_path)
        _install_flow_mocks(monkeypatch)

        rc = cli_main.run(["run", "--project", project_dir, "--jsonl"])
        assert rc == 0
        out = capsys.readouterr().out
        objects = [json.loads(ln) for ln in out.strip().split("\n")]
        assert any("status" in obj for obj in objects)
        assert DummyFlow.instances[0].run_called

    def test_run_json_no_progress_on_stderr(self, tmp_path, monkeypatch, capsys):
        project_dir = _create_valid_project(tmp_path)
        _install_flow_mocks(monkeypatch)

        rc = cli_main.run(["run", "--project", project_dir, "--json"])
        assert rc == 0
        err = capsys.readouterr().err
        assert "step=" not in err

    def test_run_preserves_final_records(self, tmp_path, monkeypatch, capsys):
        project_dir = _create_valid_project(tmp_path)
        _install_flow_mocks(monkeypatch)

        rc = cli_main.run(["run", "--project", project_dir, "--json"])
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        record = data["records"][0]
        assert record["run"] == "default"
        assert record["status"] == "success"
        assert "inspect_cmd" in record
        assert "metrics_cmd" in record
        assert "log_cmd" in record


# ===========================================================================
# AC-4: ecc status
# ===========================================================================


class TestStatus:
    def test_status_reads_flow_json(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir)

        rc = cli_main.run(["status", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "run=default" in out
        assert "step=synthesis" in out
        assert "step=floorplan" in out

    def test_status_json(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir)

        rc = cli_main.run(["status", "--project", project_dir, "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert "records" in data
        records = data["records"]
        assert records[0]["run"] == "default"
        assert records[0]["status"] == "success"
        step_records = [r for r in records if "step" in r]
        assert len(step_records) == 2

    def test_status_jsonl(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir)

        rc = cli_main.run(["status", "--project", project_dir, "--jsonl"])
        assert rc == 0
        lines = capsys.readouterr().out.strip().split("\n")
        objects = [json.loads(ln) for ln in lines]
        assert "run" in objects[0]
        assert "step" in objects[1]

    def test_status_normalizes_step_names(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir, [
            {"name": "Synthesis", "tool": "yosys", "state": "Success", "runtime": "0:00:18"},
            {"name": "place", "tool": "dreamplace", "state": "Success", "runtime": "0:01:12"},
        ])

        rc = cli_main.run(["status", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "step=synthesis" in out
        assert "step=placement" in out

    def test_status_missing_run(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)

        rc = cli_main.run(["status", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert "status=missing" in out
        assert 'start="ecc run' in out

    def test_status_invalid_flow_json(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        home = os.path.join(run_dir, "home")
        os.makedirs(home, exist_ok=True)
        with open(os.path.join(home, "flow.json"), "w") as f:
            f.write("not valid json{{{")

        rc = cli_main.run(["status", "--project", project_dir])
        assert rc == 1


# ===========================================================================
# AC-5: ecc log
# ===========================================================================


class TestLog:
    def test_log_step_errors(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")

        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        with open(os.path.join(step_dir, "synthesis.log"), "w") as f:
            f.write("Info: running\nError: bad thing\nWarning: meh\nTraceback: crash\n")

        rc = cli_main.run(["log", "synthesis", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Error: bad thing" in out
        assert "Traceback: crash" in out
        assert "Warning: meh" in out
        assert "Info: running" in out

    def test_log_step_errors_jsonl(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")

        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        with open(os.path.join(step_dir, "synthesis.log"), "w") as f:
            f.write("Info: running\nError: bad thing\n")

        rc = cli_main.run(
            ["log", "synthesis", "--errors", "--jsonl", "--project", project_dir]
        )
        assert rc == 0
        objects = [json.loads(ln) for ln in capsys.readouterr().out.strip().split("\n")]
        assert any("Error" in obj["line"] for obj in objects)

    def test_log_no_step_shows_locations(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        log_dir = os.path.join(run_dir, "log")
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, "flow.log"), "w") as f:
            f.write("log content\n")

        rc = cli_main.run(["log", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert 'ecc log' in out

    def test_log_no_step_discovers_step_logs(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")

        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        with open(os.path.join(step_dir, "synthesis.log"), "w") as f:
            f.write("Error: bad\n")

        rc = cli_main.run(["log", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "synthesis" in out
        assert "Synthesis_yosys/log/synthesis.log" in out
        assert "ecc log synthesis" in out

    def test_log_no_step_global_logs_have_disclosure(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        log_dir = os.path.join(run_dir, "log")
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, "flow.log"), "w") as f:
            f.write("content\n")

        rc = cli_main.run(["log", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "ecc log" in out

    def test_log_unknown_step(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        os.makedirs(os.path.join(project_dir, "runs", "default"), exist_ok=True)

        rc = cli_main.run(["log", "nonexistent", "--project", project_dir])
        assert rc == 1

    def test_log_missing_step_logs(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        os.makedirs(os.path.join(run_dir, "Synthesis_yosys"), exist_ok=True)

        rc = cli_main.run(["log", "synthesis", "--project", project_dir])
        assert rc == 1


# ===========================================================================
# AC-6: ecc metrics
# ===========================================================================


class TestMetrics:
    def test_metrics_reads_step_metrics(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")

        analysis_dir = os.path.join(run_dir, "Synthesis_yosys", "analysis")
        os.makedirs(analysis_dir, exist_ok=True)
        with open(os.path.join(analysis_dir, "Synthesis_metrics.json"), "w") as f:
            json.dump({"Cell number": 312, "Cell area": 1840.2}, f)

        rc = cli_main.run(["metrics", "synthesis", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "metric=cell_number" in out
        assert "value=312" in out

    def test_metrics_all_steps(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")

        for step_dir_name in ["Synthesis_yosys", "Floorplan_ecc"]:
            analysis = os.path.join(run_dir, step_dir_name, "analysis")
            os.makedirs(analysis, exist_ok=True)
            metrics_name = step_dir_name.split("_")[0] + "_metrics.json"
            with open(os.path.join(analysis, metrics_name), "w") as f:
                json.dump({"Cell number": 100}, f)

        rc = cli_main.run(["metrics", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "step=synthesis" in out
        assert "step=floorplan" in out

    def test_metrics_json(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")

        analysis_dir = os.path.join(run_dir, "Synthesis_yosys", "analysis")
        os.makedirs(analysis_dir, exist_ok=True)
        with open(os.path.join(analysis_dir, "Synthesis_metrics.json"), "w") as f:
            json.dump({"Cell number": 312}, f)

        rc = cli_main.run(
            ["metrics", "synthesis", "--json", "--project", project_dir]
        )
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert "records" in data
        assert len(data["records"]) == 1
        assert data["records"][0]["metric"] == "cell_number"

    def test_metrics_jsonl(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")

        analysis_dir = os.path.join(run_dir, "Synthesis_yosys", "analysis")
        os.makedirs(analysis_dir, exist_ok=True)
        with open(os.path.join(analysis_dir, "Synthesis_metrics.json"), "w") as f:
            json.dump({"Cell number": 312, "Cell area": 1840.2}, f)

        rc = cli_main.run(
            ["metrics", "synthesis", "--jsonl", "--project", project_dir]
        )
        assert rc == 0
        objects = [json.loads(ln) for ln in capsys.readouterr().out.strip().split("\n")]
        assert len(objects) == 2

    def test_metrics_normalizes_known_keys(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")

        analysis_dir = os.path.join(run_dir, "CTS_ecc", "analysis")
        os.makedirs(analysis_dir, exist_ok=True)
        with open(os.path.join(analysis_dir, "CTS_metrics.json"), "w") as f:
            json.dump({"Frequency [MHz]": 450.0, "Die area [μm^2]": "10000.000"}, f)

        rc = cli_main.run(["metrics", "cts", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "metric=frequency_mhz" in out
        assert "metric=die_area_um2" in out

    def test_metrics_unknown_step(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        os.makedirs(os.path.join(project_dir, "runs", "default"), exist_ok=True)

        rc = cli_main.run(["metrics", "nonexistent", "--project", project_dir])
        assert rc == 1

    def test_metrics_missing_file(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        os.makedirs(os.path.join(run_dir, "CTS_ecc", "analysis"), exist_ok=True)

        rc = cli_main.run(["metrics", "cts", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert "status=missing" in out
        assert 'log="ecc log cts' in out

    def test_metrics_json_unknown_step(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        os.makedirs(os.path.join(project_dir, "runs", "default"), exist_ok=True)

        rc = cli_main.run(["metrics", "nonexistent", "--json", "--project", project_dir])
        assert rc == 1
        data = json.loads(capsys.readouterr().out)
        assert data["records"][0]["status"] == "unknown_step"
        assert data["records"][0]["step"] == "nonexistent"

    def test_metrics_json_missing_file(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        os.makedirs(os.path.join(run_dir, "CTS_ecc", "analysis"), exist_ok=True)

        rc = cli_main.run(["metrics", "cts", "--json", "--project", project_dir])
        assert rc == 1
        data = json.loads(capsys.readouterr().out)
        assert data["records"][0]["status"] == "missing"

    def test_metrics_jsonl_unknown_step(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        os.makedirs(os.path.join(project_dir, "runs", "default"), exist_ok=True)

        rc = cli_main.run(["metrics", "nonexistent", "--jsonl", "--project", project_dir])
        assert rc == 1
        objects = [json.loads(ln) for ln in capsys.readouterr().out.strip().split("\n")]
        assert objects[0]["status"] == "unknown_step"


# ===========================================================================
# AC-7: Disclosure commands on all output
# ===========================================================================


class TestDisclosureCommands:
    def test_init_lines_have_disclosure(self, tmp_path, capsys):
        project_path = str(tmp_path / "disctest")
        rc = cli_main.run(["init", project_path])
        assert rc == 0
        out = capsys.readouterr().out
        for line in out.strip().split("\n"):
            if line.strip():
                assert _has_disclosure(line), f"Missing disclosure in: {line}"

    def test_check_lines_have_disclosure(self, tmp_path, monkeypatch, capsys):
        project_dir = _create_valid_project(tmp_path)
        monkeypatch.setattr(
            "chipcompiler.cli.config._validate_pdk_contents",
            lambda name, root: None,
        )
        rc = cli_main.run(["check", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        for line in out.strip().split("\n"):
            if line.strip():
                assert _has_disclosure(line), f"Missing disclosure in: {line}"

    def test_status_lines_have_disclosure(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir)

        rc = cli_main.run(["status", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        for line in out.strip().split("\n"):
            if line.strip():
                assert _has_disclosure(line), f"Missing disclosure in: {line}"

    def test_metrics_lines_have_disclosure(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")

        analysis_dir = os.path.join(run_dir, "Synthesis_yosys", "analysis")
        os.makedirs(analysis_dir, exist_ok=True)
        with open(os.path.join(analysis_dir, "Synthesis_metrics.json"), "w") as f:
            json.dump({"Cell number": 312}, f)

        rc = cli_main.run(["metrics", "synthesis", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        for line in out.strip().split("\n"):
            if line.strip():
                assert _has_disclosure(line), f"Missing disclosure in: {line}"

    def test_log_error_lines_have_disclosure(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")

        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        with open(os.path.join(step_dir, "synthesis.log"), "w") as f:
            f.write("Error: something failed\n")

        rc = cli_main.run(
            ["log", "synthesis", "--project", project_dir]
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "ecc log synthesis" in out

    def test_project_arg_propagated_to_disclosure(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir)

        rc = cli_main.run(["status", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert f"--project {project_dir}" in out

    def test_output_lowercase_tokens(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir, [
            {"name": "Synthesis", "tool": "yosys", "state": "Success", "runtime": "0:00:01"},
        ])

        rc = cli_main.run(["status", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "step=synthesis" in out
        assert "status=success" in out


# ===========================================================================
# AC-8: Packaging
# ===========================================================================


class TestPackaging:
    def test_ecc_console_script_in_pyproject(self):
        import tomllib

        project_root = os.path.dirname(
            os.path.dirname(os.path.dirname(__file__))
        )
        pyproject = os.path.join(project_root, "pyproject.toml")
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
        assert data["project"]["scripts"]["ecc"] == "chipcompiler.cli.main:main"


# ===========================================================================
# Edge cases
# ===========================================================================


class TestEdgeCases:
    def test_no_command_returns_nonzero(self, capsys):
        rc = cli_main.run([])
        assert rc == 1


class TestCheckFilelistValidation:
    def test_check_fails_filelist_with_missing_sources(self, tmp_path, monkeypatch):
        from chipcompiler.cli.config import _validate_pdk_contents
        monkeypatch.setattr(_validate_pdk_contents, "__wrapped__",
                            lambda *a, **k: None, raising=False)
        monkeypatch.setattr("chipcompiler.cli.config._validate_pdk_contents",
                            lambda *a, **k: None)

        project_dir = tmp_path / "flproj"
        project_dir.mkdir()
        (project_dir / "rtl").mkdir()
        (project_dir / "rtl" / "gcd.v").write_text("module gcd; endmodule")

        filelist = project_dir / "rtl" / "files.f"
        filelist.write_text("gcd.v\nmissing.v\nother_missing.v\n")

        pdk_root = tmp_path / "ics55"
        pdk_root.mkdir()

        toml = f'''[design]
name = "gcd"
top = "gcd"
rtl = ["rtl/files.f"]
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
        rc = cli_main.run(["check", "--project", str(project_dir)])
        assert rc == 1

    def test_check_fails_invalid_filelist_directive(self, tmp_path, monkeypatch):
        from chipcompiler.cli.config import _validate_pdk_contents
        monkeypatch.setattr("chipcompiler.cli.config._validate_pdk_contents",
                            lambda *a, **k: None)

        project_dir = tmp_path / "flproj2"
        project_dir.mkdir()
        (project_dir / "rtl").mkdir()

        filelist = project_dir / "rtl" / "files.f"
        filelist.write_text("gcd.v\n-f other.f\n")

        pdk_root = tmp_path / "ics55"
        pdk_root.mkdir()

        toml = f'''[design]
name = "gcd"
top = "gcd"
rtl = ["rtl/files.f"]
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
        rc = cli_main.run(["check", "--project", str(project_dir)])
        assert rc == 1


class TestRendererCmdStripping:
    def test_text_strips_cmd_suffix(self):
        from chipcompiler.cli.render import render_text
        from io import StringIO
        buf = StringIO()
        render_text(({"inspect_cmd": "ecc status", "log_cmd": "ecc log"},), file=buf)
        line = buf.getvalue().strip()
        assert "inspect=" in line
        assert "log=" in line
        assert "inspect_cmd=" not in line
        assert "log_cmd=" not in line

    def test_json_preserves_cmd_keys(self):
        from chipcompiler.cli.render import render_json
        from chipcompiler.cli.types import CommandResult
        from io import StringIO
        buf = StringIO()
        result = CommandResult(records=({"inspect_cmd": "ecc status", "log_cmd": "ecc log"},))
        render_json(result, file=buf)
        data = json.loads(buf.getvalue())
        assert "inspect_cmd" in data["records"][0]
        assert "log_cmd" in data["records"][0]

    def test_jsonl_preserves_cmd_keys(self):
        from chipcompiler.cli.render import render_jsonl
        from chipcompiler.cli.types import CommandResult
        from io import StringIO
        buf = StringIO()
        result = CommandResult(records=({"inspect_cmd": "ecc status", "log_cmd": "ecc log"},))
        render_jsonl(result, file=buf)
        record = json.loads(buf.getvalue().strip())
        assert "inspect_cmd" in record
        assert "log_cmd" in record


class TestMissingConfigErrorRecord:
    def test_check_missing_config_has_kind_error_json(self, tmp_path, capsys):
        rc = cli_main.run(["check", "--project", str(tmp_path), "--json"])
        assert rc == 1
        data = json.loads(capsys.readouterr().out)
        record = data["records"][0]
        assert record["kind"] == "error"
        assert record["error"] == "missing_config"

    def test_check_missing_config_has_kind_error_text(self, tmp_path, capsys):
        rc = cli_main.run(["check", "--project", str(tmp_path)])
        assert rc == 1
        out = capsys.readouterr().out
        assert "kind=error" in out
        assert "error=missing_config" in out

    def test_check_missing_config_has_disclosure_command(self, tmp_path, capsys):
        rc = cli_main.run(["check", "--project", str(tmp_path), "--json"])
        assert rc == 1
        data = json.loads(capsys.readouterr().out)
        record = data["records"][0]
        assert "inspect" in record or "inspect_cmd" in record


# ===========================================================================
# Log output refactoring integration tests
# ===========================================================================


class TestLogDefaultShowsAllContent:
    """AC-1: Default ecc log <step> renders complete log content."""

    def test_default_shows_all_lines(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        with open(os.path.join(step_dir, "synthesis.log"), "w") as f:
            f.write("INFO: starting\nsome output\nError: bad\nWarning: meh\n")

        rc = cli_main.run(["log", "synthesis", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "INFO: starting" in out
        assert "some output" in out
        assert "Error: bad" in out
        assert "Warning: meh" in out

    def test_default_includes_header(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        with open(os.path.join(step_dir, "synthesis.log"), "w") as f:
            f.write("ok\n")

        rc = cli_main.run(["log", "synthesis", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "[log]" in out
        assert "step=synthesis" in out
        assert "source:" in out

    def test_blank_lines_preserved(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        with open(os.path.join(step_dir, "synthesis.log"), "w") as f:
            f.write("line1\n\nline3\n")

        rc = cli_main.run(["log", "synthesis", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "line1" in out
        assert "line3" in out


class TestLogTracebackComplete:
    """AC-2: Python traceback blocks remain complete and contiguous."""

    def test_traceback_complete_in_default_output(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        with open(os.path.join(step_dir, "synthesis.log"), "w") as f:
            f.write(
                "INFO: before\n"
                "Traceback (most recent call last):\n"
                '  File "app.py", line 42, in run\n'
                "    result = compute()\n"
                "        ^^^^^^^^^\n"
                "ValueError: invalid value\n"
                "INFO: after\n"
            )

        rc = cli_main.run(["log", "synthesis", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Traceback (most recent call last):" in out
        assert 'File "app.py", line 42' in out
        assert "result = compute()" in out
        assert "^^^^^^^^^" in out
        assert "ValueError: invalid value" in out

    def test_traceback_complete_in_jsonl(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        with open(os.path.join(step_dir, "synthesis.log"), "w") as f:
            f.write(
                "Traceback (most recent call last):\n"
                '  File "a.py", line 1\n'
                "ValueError: fail\n"
            )

        rc = cli_main.run(["log", "synthesis", "--jsonl", "--project", project_dir])
        assert rc == 0
        objects = [json.loads(ln) for ln in capsys.readouterr().out.strip().split("\n")]
        assert objects[0]["kind"] == "traceback"
        assert objects[1]["kind"] == "traceback"
        assert objects[2]["kind"] == "error"


class TestLogPlainMode:
    """AC-5: --plain emits full-content stable line records."""

    def test_plain_has_all_fields(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        with open(os.path.join(step_dir, "synthesis.log"), "w") as f:
            f.write("Error: bad\nINFO: ok\n")

        rc = cli_main.run(["log", "synthesis", "--plain", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        lines = [l for l in out.strip().split("\n") if l.strip()]
        assert len(lines) == 2
        assert "step=synthesis" in lines[0]
        assert "line_no=1" in lines[0]
        assert "kind=error" in lines[0]
        assert "line_no=2" in lines[1]
        assert "kind=info" in lines[1]

    def test_plain_no_ansi(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        with open(os.path.join(step_dir, "synthesis.log"), "w") as f:
            f.write("Error: bad\n")

        rc = cli_main.run(["log", "synthesis", "--plain", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "\x1b[" not in out


class TestLogJsonlMode:
    """AC-6: --jsonl emits full-content structured log objects."""

    def test_jsonl_per_line_objects(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        with open(os.path.join(step_dir, "synthesis.log"), "w") as f:
            f.write("Error: bad\nINFO: ok\nplain\n")

        rc = cli_main.run(["log", "synthesis", "--jsonl", "--project", project_dir])
        assert rc == 0
        objects = [json.loads(ln) for ln in capsys.readouterr().out.strip().split("\n")]
        assert len(objects) == 3
        for obj in objects:
            assert "step" in obj
            assert "source" in obj
            assert "line_no" in obj
            assert "kind" in obj
            assert "line" in obj
            assert "inspect_cmd" in obj

    def test_jsonl_no_ansi(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        with open(os.path.join(step_dir, "synthesis.log"), "w") as f:
            f.write("Error: bad\n")

        rc = cli_main.run(["log", "synthesis", "--jsonl", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "\x1b[" not in out


class TestLogListingMode:
    """AC-7: ecc log without step lists available logs."""

    def test_listing_shows_logs(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        with open(os.path.join(step_dir, "synthesis.log"), "w") as f:
            f.write("content\n")

        rc = cli_main.run(["log", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "synthesis" in out
        assert "ecc log synthesis" in out

    def test_listing_no_logs_returns_no_log_status(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        os.makedirs(run_dir, exist_ok=True)

        rc = cli_main.run(["log", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "no_logs" in out

    def test_listing_jsonl_records(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        with open(os.path.join(step_dir, "synthesis.log"), "w") as f:
            f.write("content\n")

        rc = cli_main.run(["log", "--jsonl", "--project", project_dir])
        assert rc == 0
        objects = [json.loads(ln) for ln in capsys.readouterr().out.strip().split("\n") if ln.strip()]
        assert any("step" in o for o in objects)


class TestLogErrorCases:
    """AC-9: Error cases are structured and readable."""

    def test_unknown_step_returns_nonzero(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        os.makedirs(run_dir, exist_ok=True)

        rc = cli_main.run(["log", "nonexistent", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert "unknown_step" in out

    def test_unknown_step_json(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        os.makedirs(run_dir, exist_ok=True)

        rc = cli_main.run(["log", "nonexistent", "--jsonl", "--project", project_dir])
        assert rc == 1
        record = json.loads(capsys.readouterr().out.strip())
        assert record["status"] == "unknown_step"

    def test_known_step_no_logs_returns_nonzero(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        os.makedirs(os.path.join(run_dir, "Synthesis_yosys"), exist_ok=True)

        rc = cli_main.run(["log", "synthesis", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert "missing" in out

    def test_known_step_no_logs_json(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        os.makedirs(os.path.join(run_dir, "Synthesis_yosys"), exist_ok=True)

        rc = cli_main.run(["log", "synthesis", "--jsonl", "--project", project_dir])
        assert rc == 1
        record = json.loads(capsys.readouterr().out.strip())
        assert record["log_status"] == "missing"

    def test_empty_log_returns_zero(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        with open(os.path.join(step_dir, "synthesis.log"), "w") as f:
            f.write("")

        rc = cli_main.run(["log", "synthesis", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "empty" in out


class TestLogNoErrorsInDisclosure:
    """AC-8: Disclosure commands do not include --errors."""

    def test_listing_disclosure_no_errors(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        with open(os.path.join(step_dir, "synthesis.log"), "w") as f:
            f.write("ok\n")

        rc = cli_main.run(["log", "--jsonl", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "--errors" not in out

    def test_step_log_inspect_no_errors(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        with open(os.path.join(step_dir, "synthesis.log"), "w") as f:
            f.write("ok\n")

        rc = cli_main.run(["log", "synthesis", "--jsonl", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "--errors" not in out

    def test_status_disclosure_no_errors(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir)

        rc = cli_main.run(["status", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "--errors" not in out

    def test_metrics_disclosure_no_errors(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        analysis_dir = os.path.join(run_dir, "Synthesis_yosys", "analysis")
        os.makedirs(analysis_dir, exist_ok=True)
        with open(os.path.join(analysis_dir, "Synthesis_metrics.json"), "w") as f:
            json.dump({"Cell number": 100}, f)

        rc = cli_main.run(["metrics", "synthesis", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "--errors" not in out

    def test_artifacts_log_disclosure_no_errors(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir)
        log_dir = os.path.join(run_dir, "CTS_ecc", "log")
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, "cts.log"), "w") as f:
            f.write("log content\n")

        rc = cli_main.run(["artifacts", "cts", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "--errors" not in out


class TestLogUnreadableFile:
    """AC-9: Unreadable log files return non-zero with OS error."""

    def test_unreadable_log_returns_nonzero(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        log_path = os.path.join(step_dir, "synthesis.log")
        with open(log_path, "w") as f:
            f.write("content\n")
        os.chmod(log_path, 0o000)

        try:
            rc = cli_main.run(["log", "synthesis", "--project", project_dir])
            assert rc == 1
            out = capsys.readouterr().out
            assert "unreadable" in out
        finally:
            os.chmod(log_path, 0o644)

    def test_unreadable_log_jsonl(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        log_path = os.path.join(step_dir, "synthesis.log")
        with open(log_path, "w") as f:
            f.write("content\n")
        os.chmod(log_path, 0o000)

        try:
            rc = cli_main.run(["log", "synthesis", "--jsonl", "--project", project_dir])
            assert rc == 1
            record = json.loads(capsys.readouterr().out.strip())
            assert record["log_status"] == "unreadable"
            assert "source" in record
            assert "error" in record
        finally:
            os.chmod(log_path, 0o644)


class TestLogMultiSource:
    """AC-1: Multiple log files per step shown with separate source headers."""

    def test_multi_source_pretty(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        with open(os.path.join(step_dir, "a.log"), "w") as f:
            f.write("from A\n")
        with open(os.path.join(step_dir, "b.log"), "w") as f:
            f.write("from B\n")

        rc = cli_main.run(["log", "synthesis", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "a.log" in out
        assert "b.log" in out
        assert "from A" in out
        assert "from B" in out


class TestLogErrorsDeprecation:
    """AC-8: --errors is deprecated with visible notice."""

    def test_errors_hidden_from_help(self, tmp_path, capsys):
        with pytest.raises(SystemExit):
            cli_main.run(["log", "--help"])

    def test_errors_emits_deprecation_warning(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        with open(os.path.join(step_dir, "synthesis.log"), "w") as f:
            f.write("ok\n")

        rc = cli_main.run(["log", "synthesis", "--errors", "--project", project_dir])
        assert rc == 0
        err = capsys.readouterr().err
        assert "deprecated" in err

    def test_errors_jsonl_still_full_records(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        with open(os.path.join(step_dir, "synthesis.log"), "w") as f:
            f.write("INFO: running\nError: bad\n")

        rc = cli_main.run(
            ["log", "synthesis", "--errors", "--jsonl", "--project", project_dir]
        )
        assert rc == 0
        objects = [json.loads(ln) for ln in capsys.readouterr().out.strip().split("\n")]
        assert len(objects) == 2
        assert objects[0]["kind"] == "info"
        assert objects[1]["kind"] == "error"
        assert "\x1b[" not in capsys.readouterr().out

