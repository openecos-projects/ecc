import json
import os

from chipcompiler.cli import main as cli_main


class TestLog:
    def test_log_step_errors(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
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

    def test_log_step_errors_jsonl(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")

        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        with open(os.path.join(step_dir, "synthesis.log"), "w") as f:
            f.write("Info: running\nError: bad thing\n")

        rc = cli_main.run(["log", "synthesis", "--errors", "--jsonl", "--project", project_dir])
        assert rc == 0
        objects = [json.loads(ln) for ln in capsys.readouterr().out.strip().split("\n")]
        assert any("Error" in obj["line"] for obj in objects)

    def test_log_no_step_shows_locations(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        log_dir = os.path.join(run_dir, "log")
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, "flow.log"), "w") as f:
            f.write("log content\n")

        rc = cli_main.run(["log", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "ecc log" in out

    def test_log_no_step_discovers_step_logs(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
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

    def test_log_no_step_global_logs_have_disclosure(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        log_dir = os.path.join(run_dir, "log")
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, "flow.log"), "w") as f:
            f.write("content\n")

        rc = cli_main.run(["log", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "ecc log" in out

    def test_log_unknown_step(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        os.makedirs(os.path.join(project_dir, "runs", "default"), exist_ok=True)

        rc = cli_main.run(["log", "nonexistent", "--project", project_dir])
        assert rc == 1

    def test_log_missing_step_logs(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        os.makedirs(os.path.join(run_dir, "Synthesis_yosys"), exist_ok=True)

        rc = cli_main.run(["log", "synthesis", "--project", project_dir])
        assert rc == 1


class TestLogDefaultShowsAllContent:
    """AC-1: Default ecc log <step> renders complete log content."""

    def test_default_shows_all_lines(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
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

    def test_default_includes_header(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
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

    def test_blank_lines_preserved(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
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

    def test_traceback_complete_in_default_output(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
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

    def test_traceback_complete_in_jsonl(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        with open(os.path.join(step_dir, "synthesis.log"), "w") as f:
            f.write('Traceback (most recent call last):\n  File "a.py", line 1\nValueError: fail\n')

        rc = cli_main.run(["log", "synthesis", "--jsonl", "--project", project_dir])
        assert rc == 0
        objects = [json.loads(ln) for ln in capsys.readouterr().out.strip().split("\n")]
        assert objects[0]["kind"] == "traceback"
        assert objects[1]["kind"] == "traceback"
        assert objects[2]["kind"] == "error"

    def test_keyboard_interrupt_jsonl_classified_as_error(
        self, tmp_path, capsys, create_cli_project
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        with open(os.path.join(step_dir, "synthesis.log"), "w") as f:
            f.write(
                'Traceback (most recent call last):\n  File "a.py", line 1\nKeyboardInterrupt\n'
            )

        rc = cli_main.run(["log", "synthesis", "--jsonl", "--project", project_dir])
        assert rc == 0
        objects = [json.loads(ln) for ln in capsys.readouterr().out.strip().split("\n")]
        assert objects[0]["kind"] == "traceback"
        assert objects[1]["kind"] == "traceback"
        assert objects[2]["kind"] == "error"
        assert objects[2]["line"] == "KeyboardInterrupt"


class TestLogPlainMode:
    """AC-5: --plain emits full-content stable line records."""

    def test_plain_has_all_fields(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        with open(os.path.join(step_dir, "synthesis.log"), "w") as f:
            f.write("Error: bad\nINFO: ok\n")

        rc = cli_main.run(["log", "synthesis", "--plain", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        lines = [line for line in out.strip().split("\n") if line.strip()]
        assert len(lines) == 2
        assert "step=synthesis" in lines[0]
        assert "line_no=1" in lines[0]
        assert "kind=error" in lines[0]
        assert "line_no=2" in lines[1]
        assert "kind=info" in lines[1]

    def test_plain_no_ansi(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        with open(os.path.join(step_dir, "synthesis.log"), "w") as f:
            f.write("Error: bad\n")

        rc = cli_main.run(["log", "synthesis", "--plain", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "\x1b[" not in out

    def test_plain_stable_quoting_for_special_chars(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        with open(os.path.join(step_dir, "synthesis.log"), "w") as f:
            f.write('key=value path\\to\\file "quoted text"\n')

        rc = cli_main.run(["log", "synthesis", "--plain", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "\x1b[" not in out
        lines = [line for line in out.strip().split("\n") if line.strip()]
        assert len(lines) == 1
        assert 'line="key=value' in lines[0]
        assert "inspect_cmd=" in lines[0]


class TestLogJsonlMode:
    """AC-6: --jsonl emits full-content structured log objects."""

    def test_jsonl_per_line_objects(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
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

    def test_jsonl_no_ansi(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        with open(os.path.join(step_dir, "synthesis.log"), "w") as f:
            f.write("Error: bad\n")

        rc = cli_main.run(["log", "synthesis", "--jsonl", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "\x1b[" not in out


class TestLogJsonMode:
    """ecc log --json must produce JSON envelope output."""

    def test_json_step_output(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        with open(os.path.join(step_dir, "synthesis.log"), "w") as f:
            f.write("Error: bad\nINFO: ok\n")

        rc = cli_main.run(["log", "synthesis", "--json", "--project", project_dir])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert "records" in data
        assert len(data["records"]) == 2

    def test_json_listing_output(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        with open(os.path.join(step_dir, "synthesis.log"), "w") as f:
            f.write("content\n")

        rc = cli_main.run(["log", "--json", "--project", project_dir])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert "records" in data


class TestLogListingMode:
    """AC-7: ecc log without step lists available logs."""

    def test_listing_shows_logs(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
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

    def test_listing_no_logs_returns_no_log_status(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        os.makedirs(run_dir, exist_ok=True)

        rc = cli_main.run(["log", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "no_logs" in out

    def test_listing_jsonl_records(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        with open(os.path.join(step_dir, "synthesis.log"), "w") as f:
            f.write("content\n")

        rc = cli_main.run(["log", "--jsonl", "--project", project_dir])
        assert rc == 0
        objects = [
            json.loads(ln) for ln in capsys.readouterr().out.strip().split("\n") if ln.strip()
        ]
        assert any("step" in o for o in objects)

    def test_listing_plain_step_logs(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        with open(os.path.join(step_dir, "synthesis.log"), "w") as f:
            f.write("content\n")

        rc = cli_main.run(["log", "--plain", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "step=synthesis" in out
        assert "source=" in out
        assert "inspect_cmd=" in out
        assert "line_no=" not in out

    def test_listing_plain_run_level_logs(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        log_dir = os.path.join(run_dir, "log")
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, "flow.log"), "w") as f:
            f.write("log content\n")

        rc = cli_main.run(["log", "--plain", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "log=" in out
        assert "inspect_cmd=" in out
        assert "line_no=" not in out
        assert "kind=" not in out


class TestLogErrorCases:
    """AC-9: Error cases are structured and readable."""

    def test_unknown_step_returns_nonzero(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        os.makedirs(run_dir, exist_ok=True)

        rc = cli_main.run(["log", "nonexistent", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert "unknown_step" in out

    def test_unknown_step_json(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        os.makedirs(run_dir, exist_ok=True)

        rc = cli_main.run(["log", "nonexistent", "--jsonl", "--project", project_dir])
        assert rc == 1
        record = json.loads(capsys.readouterr().out.strip())
        assert record["status"] == "unknown_step"

    def test_known_step_no_logs_returns_nonzero(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        os.makedirs(os.path.join(run_dir, "Synthesis_yosys"), exist_ok=True)

        rc = cli_main.run(["log", "synthesis", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert "missing" in out

    def test_known_step_no_logs_json(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        os.makedirs(os.path.join(run_dir, "Synthesis_yosys"), exist_ok=True)

        rc = cli_main.run(["log", "synthesis", "--jsonl", "--project", project_dir])
        assert rc == 1
        record = json.loads(capsys.readouterr().out.strip())
        assert record["log_status"] == "missing"

    def test_empty_log_returns_zero(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
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

    def test_listing_disclosure_no_errors(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        with open(os.path.join(step_dir, "synthesis.log"), "w") as f:
            f.write("ok\n")

        rc = cli_main.run(["log", "--jsonl", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "--errors" not in out

    def test_step_log_inspect_no_errors(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        with open(os.path.join(step_dir, "synthesis.log"), "w") as f:
            f.write("ok\n")

        rc = cli_main.run(["log", "synthesis", "--jsonl", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "--errors" not in out

    def test_status_disclosure_no_errors(
        self, tmp_path, capsys, create_cli_project, create_flow_json
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir, profile="main")

        rc = cli_main.run(["status", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "--errors" not in out

    def test_metrics_disclosure_no_errors(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
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

    def test_artifacts_log_disclosure_no_errors(
        self, tmp_path, capsys, create_cli_project, create_flow_json
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir, profile="main")
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

    def test_unreadable_log_returns_nonzero(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
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

    def test_unreadable_log_jsonl(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
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

    def test_multi_source_pretty(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
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
        rc = cli_main.run(["log", "--help"])
        assert rc == 0
        assert "--errors" not in capsys.readouterr().out

    def test_errors_emits_deprecation_warning(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        with open(os.path.join(step_dir, "synthesis.log"), "w") as f:
            f.write("ok\n")

        rc = cli_main.run(["log", "synthesis", "--errors", "--project", project_dir])
        assert rc == 0
        err = capsys.readouterr().err
        assert "deprecated" in err

    def test_errors_jsonl_still_full_records(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        with open(os.path.join(step_dir, "synthesis.log"), "w") as f:
            f.write("INFO: running\nError: bad\n")

        rc = cli_main.run(["log", "synthesis", "--errors", "--jsonl", "--project", project_dir])
        assert rc == 0
        objects = [json.loads(ln) for ln in capsys.readouterr().out.strip().split("\n")]
        assert len(objects) == 2
        assert objects[0]["kind"] == "info"
        assert objects[1]["kind"] == "error"
        assert "\x1b[" not in capsys.readouterr().out


class TestLogListingFlowOrder:
    """Listing step logs follow flow.json order, not alphabetical."""

    def _setup_steps_with_flow(
        self, tmp_path, create_cli_project, create_flow_json, step_names, extra_dirs=None
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(
            run_dir, steps=[{"name": n, "tool": "ecc", "state": "Success"} for n in step_names]
        )
        all_dirs = list(step_names) + (extra_dirs or [])
        tool_map = {
            "Synthesis": "yosys",
            "Floorplan": "ecc",
            "fixFanout": "ecc",
            "place": "ecc",
            "CTS": "ecc",
            "legalization": "ecc",
            "route": "ecc",
            "drc": "ecc",
            "filler": "ecc",
        }
        for name in all_dirs:
            tool = tool_map.get(name, "ecc")
            step_dir = os.path.join(run_dir, f"{name}_{tool}", "log")
            os.makedirs(step_dir, exist_ok=True)
            with open(os.path.join(step_dir, f"{name.lower()}.log"), "w") as f:
                f.write(f"log from {name}\n")
        return project_dir

    def test_steps_follow_flow_json_order(
        self, tmp_path, capsys, create_cli_project, create_flow_json
    ):
        project_dir = self._setup_steps_with_flow(
            tmp_path,
            create_cli_project,
            create_flow_json,
            ["Synthesis", "Floorplan", "CTS"],
        )
        rc = cli_main.run(["log", "--jsonl", "--project", project_dir])
        assert rc == 0
        records = [
            json.loads(ln) for ln in capsys.readouterr().out.strip().split("\n") if ln.strip()
        ]
        steps = [r.get("step") for r in records if "step" in r]
        assert steps == ["synthesis", "floorplan", "cts"]

    def test_run_level_logs_before_step_logs(
        self, tmp_path, capsys, create_cli_project, create_flow_json
    ):
        project_dir = self._setup_steps_with_flow(
            tmp_path,
            create_cli_project,
            create_flow_json,
            ["Synthesis", "CTS"],
        )
        run_dir = os.path.join(project_dir, "runs", "default")
        log_dir = os.path.join(run_dir, "log")
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, "flow.log"), "w") as f:
            f.write("run-level log\n")
        rc = cli_main.run(["log", "--jsonl", "--project", project_dir])
        assert rc == 0
        records = [
            json.loads(ln) for ln in capsys.readouterr().out.strip().split("\n") if ln.strip()
        ]
        run_indices = [i for i, r in enumerate(records) if "log" in r and "step" not in r]
        step_indices = [i for i, r in enumerate(records) if "step" in r]
        assert run_indices, "expected at least one run-level record"
        assert step_indices, "expected at least one step record"
        assert max(run_indices) < min(step_indices)

    def test_extra_steps_after_flow_steps(
        self, tmp_path, capsys, create_cli_project, create_flow_json
    ):
        project_dir = self._setup_steps_with_flow(
            tmp_path,
            create_cli_project,
            create_flow_json,
            ["Synthesis", "CTS"],
            extra_dirs=["Floorplan"],
        )
        rc = cli_main.run(["log", "--jsonl", "--project", project_dir])
        assert rc == 0
        records = [
            json.loads(ln) for ln in capsys.readouterr().out.strip().split("\n") if ln.strip()
        ]
        steps = [r.get("step") for r in records if "step" in r]
        synth_idx = steps.index("synthesis")
        cts_idx = steps.index("cts")
        fp_idx = steps.index("floorplan")
        assert synth_idx < cts_idx
        assert cts_idx < fp_idx

    def test_extra_steps_sorted_alphabetically(
        self, tmp_path, capsys, create_cli_project, create_flow_json
    ):
        project_dir = self._setup_steps_with_flow(
            tmp_path,
            create_cli_project,
            create_flow_json,
            ["Synthesis"],
            extra_dirs=["Floorplan", "CTS"],
        )
        rc = cli_main.run(["log", "--jsonl", "--project", project_dir])
        assert rc == 0
        records = [
            json.loads(ln) for ln in capsys.readouterr().out.strip().split("\n") if ln.strip()
        ]
        steps = [r.get("step") for r in records if "step" in r]
        extras = [s for s in steps if s != "synthesis"]
        assert extras == sorted(extras)

    def test_missing_flow_json_falls_back_to_alphabetical(
        self, tmp_path, capsys, create_cli_project
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        os.makedirs(run_dir, exist_ok=True)
        for name in ["CTS_ecc", "Floorplan_ecc", "Synthesis_yosys"]:
            step_dir = os.path.join(run_dir, name, "log")
            os.makedirs(step_dir, exist_ok=True)
            with open(os.path.join(step_dir, "test.log"), "w") as f:
                f.write("content\n")
        rc = cli_main.run(["log", "--jsonl", "--project", project_dir])
        assert rc == 0
        records = [
            json.loads(ln) for ln in capsys.readouterr().out.strip().split("\n") if ln.strip()
        ]
        steps = [r.get("step") for r in records if "step" in r]
        assert steps == sorted(steps)

    def test_corrupt_flow_json_falls_back_to_alphabetical(
        self, tmp_path, capsys, create_cli_project
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        home = os.path.join(run_dir, "home")
        os.makedirs(home, exist_ok=True)
        with open(os.path.join(home, "flow.json"), "w") as f:
            f.write("not valid json{{{")
        for name in ["CTS_ecc", "Floorplan_ecc", "Synthesis_yosys"]:
            step_dir = os.path.join(run_dir, name, "log")
            os.makedirs(step_dir, exist_ok=True)
            with open(os.path.join(step_dir, "test.log"), "w") as f:
                f.write("content\n")
        rc = cli_main.run(["log", "--jsonl", "--project", project_dir])
        assert rc == 0
        records = [
            json.loads(ln) for ln in capsys.readouterr().out.strip().split("\n") if ln.strip()
        ]
        steps = [r.get("step") for r in records if "step" in r]
        assert steps == sorted(steps)


class TestLogListingTailPreview:
    """Tail preview shows up to 10 lines in default pretty text mode."""

    def test_listing_shows_tail_lines(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        log_path = os.path.join(step_dir, "synthesis.log")
        lines = [f"log line {i}" for i in range(15)]
        with open(log_path, "w") as f:
            f.write("\n".join(lines) + "\n")
        rc = cli_main.run(["log", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "log line 14" in out
        assert "tail:" in out

    def test_listing_tail_max_10_lines(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        log_path = os.path.join(step_dir, "synthesis.log")
        lines = [f"line {i}" for i in range(20)]
        with open(log_path, "w") as f:
            f.write("\n".join(lines) + "\n")
        rc = cli_main.run(["log", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        output_lines = out.split("\n")
        tail_header_idx = next(
            index for index, line in enumerate(output_lines) if line.strip() == "tail:"
        )
        tail_content = [
            line
            for line in output_lines[tail_header_idx + 1 :]
            if line.startswith("      ") and "inspect:" not in line
        ]
        assert len(tail_content) == 10

    def test_empty_log_no_tail_block(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        log_path = os.path.join(step_dir, "synthesis.log")
        with open(log_path, "w") as f:
            f.write("")
        rc = cli_main.run(["log", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "tail:" not in out
        assert "inspect:" in out

    def test_inspect_visible_below_tail(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        log_path = os.path.join(step_dir, "synthesis.log")
        with open(log_path, "w") as f:
            f.write("content line\n")
        rc = cli_main.run(["log", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        tail_pos = out.find("tail:")
        inspect_pos = out.find("inspect:")
        assert tail_pos < inspect_pos


class TestLogListingMachineModeNoTail:
    """Machine modes must not include tail data."""

    def test_plain_no_tail(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        with open(os.path.join(step_dir, "synthesis.log"), "w") as f:
            f.write("line 1\nline 2\nline 3\n")
        rc = cli_main.run(["log", "--plain", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "tail=" not in out

    def test_json_no_tail(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        with open(os.path.join(step_dir, "synthesis.log"), "w") as f:
            f.write("line 1\nline 2\n")
        rc = cli_main.run(["log", "--json", "--project", project_dir])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        for rec in data["records"]:
            assert "tail" not in rec

    def test_jsonl_no_tail(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        with open(os.path.join(step_dir, "synthesis.log"), "w") as f:
            f.write("line 1\nline 2\n")
        rc = cli_main.run(["log", "--jsonl", "--project", project_dir])
        assert rc == 0
        records = [
            json.loads(ln) for ln in capsys.readouterr().out.strip().split("\n") if ln.strip()
        ]
        for rec in records:
            assert "tail" not in rec


class TestLogStepUnchanged:
    """ecc log <step> full output must remain unchanged."""

    def test_step_shows_all_lines_not_tail(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        lines = [f"line {i}" for i in range(20)]
        with open(os.path.join(step_dir, "synthesis.log"), "w") as f:
            f.write("\n".join(lines) + "\n")
        rc = cli_main.run(["log", "synthesis", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "line 0" in out
        assert "line 19" in out

    def test_step_plain_unchanged(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        with open(os.path.join(step_dir, "synthesis.log"), "w") as f:
            f.write("a\nb\nc\n")
        rc = cli_main.run(["log", "synthesis", "--plain", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "line_no=1" in out
        assert "line_no=2" in out
        assert "line_no=3" in out
        assert "tail" not in out

    def test_step_jsonl_unchanged(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        with open(os.path.join(step_dir, "synthesis.log"), "w") as f:
            f.write("a\nb\n")
        rc = cli_main.run(["log", "synthesis", "--jsonl", "--project", project_dir])
        assert rc == 0
        records = [
            json.loads(ln) for ln in capsys.readouterr().out.strip().split("\n") if ln.strip()
        ]
        assert len(records) == 2
        for rec in records:
            assert "tail" not in rec


class TestLogListingUnreadable:
    """Unreadable logs in listing mode must omit tail, keep path+inspect, no traceback."""

    def test_unreadable_step_log_in_listing(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        log_path = os.path.join(step_dir, "synthesis.log")
        with open(log_path, "w") as f:
            f.write("content\n")
        os.chmod(log_path, 0o000)

        try:
            rc = cli_main.run(["log", "--project", project_dir])
            assert rc == 0
            out = capsys.readouterr().out
            assert "tail:" not in out
            assert "Synthesis_yosys" in out
            assert "inspect:" in out
            assert "Traceback" not in out
        finally:
            os.chmod(log_path, 0o644)
