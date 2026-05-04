import json
import os

from chipcompiler.cli import main as cli_main
from chipcompiler.cli.pretty import (
    BOLD,
    CYAN,
    DIM,
    GREEN,
    RED,
    RESET,
    YELLOW,
    display_key,
    format_plain_value,
    render_header,
    status_style,
    style,
    supports_color,
)
from chipcompiler.cli.render import _plain_value, render_plain
from chipcompiler.cli.types import CommandResult
from io import StringIO


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
    import json as j
    home = os.path.join(run_dir, "home")
    os.makedirs(home, exist_ok=True)
    if steps is None:
        steps = [
            {"name": "Synthesis", "tool": "yosys", "state": "Success", "runtime": "0:00:05"},
        ]
    with open(os.path.join(home, "flow.json"), "w") as f:
        j.dump({"steps": steps}, f)


# ---------------------------------------------------------------------------
# Plain key-value stability tests
# ---------------------------------------------------------------------------


class TestPlainQuoting:
    def test_plain_value_no_quoting_for_simple(self):
        assert _plain_value("hello") == "hello"

    def test_plain_value_quotes_spaces(self):
        assert _plain_value("hello world") == '"hello world"'

    def test_plain_value_quotes_equals(self):
        assert _plain_value("a=b") == '"a=b"'

    def test_plain_value_escapes_backslashes(self):
        assert _plain_value("path\\to\\file") == '"path\\\\to\\\\file"'

    def test_plain_value_escapes_quotes(self):
        assert _plain_value('say "hi"') == '"say \\"hi\\""'

    def test_plain_value_numeric(self):
        assert _plain_value(42) == "42"

    def test_render_plain_one_record_per_line(self):
        records = (
            {"a": "1", "b": "two words"},
            {"c": "3"},
        )
        buf = StringIO()
        render_plain(records, file=buf)
        lines = [l for l in buf.getvalue().strip().split("\n") if l.strip()]
        assert len(lines) == 2
        assert "a=1" in lines[0]
        assert 'b="two words"' in lines[0]

    def test_render_plain_no_ansi(self):
        records = ({"status": "success", "path": "/tmp/x"},)
        buf = StringIO()
        render_plain(records, file=buf)
        assert "\x1b[" not in buf.getvalue()


# ---------------------------------------------------------------------------
# Display key normalization
# ---------------------------------------------------------------------------


class TestDisplayKey:
    def test_strips_cmd_suffix(self):
        assert display_key("inspect_cmd") == "inspect"

    def test_preserves_non_cmd(self):
        assert display_key("status") == "status"

    def test_replaces_underscores(self):
        assert display_key("run_dir") == "run dir"


# ---------------------------------------------------------------------------
# Color gating
# ---------------------------------------------------------------------------


class TestColorGating:
    def test_supports_color_non_tty(self):
        assert not supports_color(file=StringIO())

    def test_style_disabled(self):
        assert style("text", RED, enabled=False) == "text"

    def test_style_enabled(self):
        styled = style("text", RED, enabled=True)
        assert RED in styled
        assert RESET in styled

    def test_status_style_known_states(self):
        assert GREEN in status_style("success", color=True)
        assert RED in status_style("failed", color=True)
        assert YELLOW in status_style("pending", color=True)

    def test_status_style_unknown_passthrough(self):
        assert status_style("unknown_state", color=True) == "unknown_state"

    def test_status_style_no_color(self):
        assert status_style("success", color=False) == "success"


# ---------------------------------------------------------------------------
# Pretty header rendering
# ---------------------------------------------------------------------------


class TestPrettyHeader:
    def test_header_with_color(self):
        h = render_header("status", color=True)
        assert BOLD in h
        assert RESET in h
        assert "[status]" in h

    def test_header_without_color(self):
        h = render_header("status", color=False)
        assert "\x1b[" not in h
        assert "[status]" in h


# ---------------------------------------------------------------------------
# CLI --plain acceptance tests
# ---------------------------------------------------------------------------


class TestPlainFlagAcceptance:
    def test_init_plain(self, tmp_path, capsys):
        rc = cli_main.run(["init", str(tmp_path / "p"), "--plain"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "\x1b[" not in out
        assert "=" in out

    def test_check_plain(self, tmp_path, monkeypatch, capsys):
        project_dir = _create_valid_project(tmp_path)
        monkeypatch.setattr(
            "chipcompiler.cli.config._validate_pdk_contents",
            lambda name, root: None,
        )
        rc = cli_main.run(["check", "--project", project_dir, "--plain"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "\x1b[" not in out
        assert "=" in out

    def test_status_plain(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        _create_flow_json(os.path.join(project_dir, "runs", "default"))
        rc = cli_main.run(["status", "--project", project_dir, "--plain"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "\x1b[" not in out
        assert "status=" in out

    def test_metrics_plain(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir)
        analysis_dir = os.path.join(run_dir, "Synthesis_yosys", "analysis")
        os.makedirs(analysis_dir, exist_ok=True)
        with open(os.path.join(analysis_dir, "Synthesis_metrics.json"), "w") as f:
            json.dump({"Cell number": 312}, f)
        rc = cli_main.run(["metrics", "synthesis", "--plain", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "\x1b[" not in out
        assert "metric=" in out

    def test_artifacts_plain(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir)
        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        with open(os.path.join(step_dir, "synthesis.log"), "w") as f:
            f.write("ok\n")
        rc = cli_main.run(["artifacts", "--plain", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "\x1b[" not in out

    def test_diagnose_plain(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        rc = cli_main.run(["diagnose", "--plain", "--project", project_dir])
        out = capsys.readouterr().out
        assert "\x1b[" not in out

    def test_config_plain(self, tmp_path, monkeypatch, capsys):
        project_dir = _create_valid_project(tmp_path)
        monkeypatch.setattr(
            "chipcompiler.cli.config._validate_pdk_contents",
            lambda name, root: None,
        )
        rc = cli_main.run(["config", "--resolved", "--plain", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "\x1b[" not in out


# ---------------------------------------------------------------------------
# Pretty default output structure tests
# ---------------------------------------------------------------------------


class TestPrettyDefaultOutput:
    def test_init_has_header(self, tmp_path, capsys):
        rc = cli_main.run(["init", str(tmp_path / "p")])
        assert rc == 0
        out = capsys.readouterr().out
        assert "[init]" in out

    def test_check_has_header(self, tmp_path, monkeypatch, capsys):
        project_dir = _create_valid_project(tmp_path)
        monkeypatch.setattr(
            "chipcompiler.cli.config._validate_pdk_contents",
            lambda name, root: None,
        )
        rc = cli_main.run(["check", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "[check]" in out

    def test_status_has_header(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        _create_flow_json(os.path.join(project_dir, "runs", "default"))
        rc = cli_main.run(["status", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "[status]" in out

    def test_status_groups_steps(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        _create_flow_json(os.path.join(project_dir, "runs", "default"), [
            {"name": "Synthesis", "tool": "yosys", "state": "Success", "runtime": "0:00:05"},
            {"name": "CTS", "tool": "ecc", "state": "Success", "runtime": "0:00:04"},
        ])
        rc = cli_main.run(["status", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "synthesis (yosys)" in out
        assert "cts (ecc)" in out

    def test_metrics_groups_by_step(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        for step_dir_name in ["Synthesis_yosys", "CTS_ecc"]:
            analysis = os.path.join(run_dir, step_dir_name, "analysis")
            os.makedirs(analysis, exist_ok=True)
            metrics_name = step_dir_name.split("_")[0] + "_metrics.json"
            with open(os.path.join(analysis, metrics_name), "w") as f:
                json.dump({"Cell number": 100}, f)
        rc = cli_main.run(["metrics", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "[metrics]" in out
        assert "synthesis:" in out
        assert "cts:" in out

    def test_diagnose_clean_has_header(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir, [
            {"name": "CTS", "tool": "ecc", "state": "Success", "runtime": "0:00:04"},
        ])
        step_dir = os.path.join(run_dir, "CTS_ecc", "log")
        os.makedirs(step_dir, exist_ok=True)
        with open(os.path.join(step_dir, "cts.log"), "w") as f:
            f.write("ok\n")
        rc = cli_main.run(["diagnose", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "[diagnose]" in out
        assert "clean" in out

    def test_error_output_has_error_header(self, tmp_path, capsys):
        rc = cli_main.run(["check", "--project", str(tmp_path)])
        assert rc == 1
        out = capsys.readouterr().out
        assert "[error]" in out

    def test_run_summary_has_header(self, tmp_path, monkeypatch, capsys):
        project_dir = _create_valid_project(tmp_path)
        from types import SimpleNamespace

        DummyFlow_instances = []
        class DummyFlow:
            instances = DummyFlow_instances
            has_init_value = False
            run_steps_value = True
            def __init__(self, workspace):
                self.workspace = workspace
                self.added_steps = []
                self.create_called = False
                self.run_called = False
                self.workspace_steps = []
                DummyFlow.instances.append(self)
            def has_init(self):
                return False
            def add_step(self, step, tool, state):
                self.added_steps.append((step, tool, state))
            def create_step_workspaces(self):
                self.create_called = True
            def run_steps(self):
                self.run_called = True
                return True

        monkeypatch.setattr("chipcompiler.data.create_workspace",
                            lambda **kw: SimpleNamespace(name="ws"))
        monkeypatch.setattr("chipcompiler.engine.EngineFlow", DummyFlow)
        monkeypatch.setattr(
            "chipcompiler.rtl2gds.build_rtl2gds_flow",
            lambda: [("Synthesis", "yosys", "Unstart")],
        )
        monkeypatch.setattr(
            "chipcompiler.cli.config._validate_pdk_contents",
            lambda name, root: None,
        )

        rc = cli_main.run(["run", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "[run]" in out
        assert "success" in out


# ---------------------------------------------------------------------------
# JSON/JSONL unaffected by pretty changes
# ---------------------------------------------------------------------------


class TestJsonUnchanged:
    def test_status_json_unchanged(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        _create_flow_json(os.path.join(project_dir, "runs", "default"))
        rc = cli_main.run(["status", "--project", project_dir, "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert "records" in data
        assert data["records"][0]["run"] == "default"

    def test_metrics_jsonl_unchanged(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        run_dir = os.path.join(project_dir, "runs", "default")
        _create_flow_json(run_dir)
        analysis_dir = os.path.join(run_dir, "Synthesis_yosys", "analysis")
        os.makedirs(analysis_dir, exist_ok=True)
        with open(os.path.join(analysis_dir, "Synthesis_metrics.json"), "w") as f:
            json.dump({"Cell number": 312}, f)
        rc = cli_main.run(["metrics", "synthesis", "--jsonl", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "\x1b[" not in out
        objects = [json.loads(l) for l in out.strip().split("\n")]
        assert any("metric" in o for o in objects)
