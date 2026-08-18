import io
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

import chipcompiler.cli.rendering.progress as progress
from chipcompiler.cli.core.types import CommandContext, OutputMode
from chipcompiler.cli.inspection.log_view import LineKind, LogLine
from chipcompiler.cli.rendering.pretty import BOLD, CYAN, DIM, GREEN, RED, RESET
from chipcompiler.cli.rendering.progress import (
    RunProgressRenderer,
    format_error_context,
    run_flow_with_progress,
    sanitize_log_line,
    should_enable_run_progress,
    style,
    supports_color,
    truncate_to_width,
)
from chipcompiler.runtime.worker_operation import OperationResult

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def _strip_ansi(text):
    return _ANSI_RE.sub("", text)


class FakeTTYStderr:
    def __init__(self, *, isatty_value=True):
        self._isatty = isatty_value
        self.written = []

    def isatty(self):
        return self._isatty

    def write(self, s):
        self.written.append(s)

    def flush(self):
        pass


class RecordingRenderer:
    def __init__(self):
        self.lines = []
        self._lock = threading.Lock()

    def running(self, text):
        with self._lock:
            self.lines.append(text)

    def has_line_containing(self, needle):
        with self._lock:
            return any(needle in line for line in self.lines)


def _wait_until(predicate, timeout=1.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def _make_ctx(mode=OutputMode.TEXT, run_id=None):
    return CommandContext(
        project_dir="/tmp/project",
        project=None,
        run_dir="/tmp/project/runs/default",
        run_id=run_id,
        output_mode=mode,
    )


# -- supports_color --


class TestSupportsColor:
    def test_enabled_text_tty(self):
        env = {"TERM": "xterm-256color"}
        assert supports_color(FakeTTYStderr(isatty_value=True), OutputMode.TEXT, env) is True

    def test_disabled_non_tty(self):
        assert supports_color(FakeTTYStderr(isatty_value=False), OutputMode.TEXT) is False

    def test_disabled_no_isattr(self):
        assert supports_color(io.StringIO(), OutputMode.TEXT) is False

    def test_disabled_no_color(self):
        env = {"NO_COLOR": "1"}
        assert supports_color(FakeTTYStderr(isatty_value=True), OutputMode.TEXT, env) is False

    def test_disabled_term_dumb(self):
        env = {"TERM": "dumb"}
        assert supports_color(FakeTTYStderr(isatty_value=True), OutputMode.TEXT, env) is False

    def test_disabled_json(self):
        assert supports_color(FakeTTYStderr(isatty_value=True), OutputMode.JSON) is False

    def test_disabled_jsonl(self):
        assert supports_color(FakeTTYStderr(isatty_value=True), OutputMode.JSONL) is False

    def test_enabled_with_clean_env(self):
        env = {"TERM": "xterm-256color"}
        assert supports_color(FakeTTYStderr(isatty_value=True), OutputMode.TEXT, env) is True


# -- style --


class TestStyle:
    def test_applies_code_when_enabled(self):
        result = style("hello", GREEN, enabled=True)
        assert result == f"{GREEN}hello{RESET}"

    def test_passthrough_when_disabled(self):
        assert style("hello", GREEN, enabled=False) == "hello"


# -- should_enable_run_progress --


class TestShouldEnableRunProgress:
    def test_enabled_text_tty(self):
        ctx = _make_ctx(OutputMode.TEXT)
        assert should_enable_run_progress(ctx, FakeTTYStderr(isatty_value=True)) is True

    def test_disabled_json(self):
        ctx = _make_ctx(OutputMode.JSON)
        assert should_enable_run_progress(ctx, FakeTTYStderr(isatty_value=True)) is False

    def test_disabled_jsonl(self):
        ctx = _make_ctx(OutputMode.JSONL)
        assert should_enable_run_progress(ctx, FakeTTYStderr(isatty_value=True)) is False

    def test_disabled_plain(self):
        ctx = _make_ctx(OutputMode.PLAIN)
        assert should_enable_run_progress(ctx, FakeTTYStderr(isatty_value=True)) is False

    def test_disabled_no_tty(self):
        ctx = _make_ctx(OutputMode.TEXT)
        assert should_enable_run_progress(ctx, FakeTTYStderr(isatty_value=False)) is False

    def test_disabled_no_isattr(self):
        ctx = _make_ctx(OutputMode.TEXT)
        assert should_enable_run_progress(ctx, io.StringIO()) is False


# -- sanitize_log_line --


class TestSanitizeLogLine:
    def test_strips_ansi(self):
        assert sanitize_log_line("\x1b[32mOK\x1b[0m") == "OK"

    def test_replaces_control_chars(self):
        assert sanitize_log_line("a\r\nb\tc") == "a b c"

    def test_collapses_spaces(self):
        assert sanitize_log_line("a    b") == "a b"

    def test_strips_whitespace(self):
        assert sanitize_log_line("  hello  ") == "hello"

    def test_empty_string(self):
        assert sanitize_log_line("") == ""

    def test_preserves_normal_text(self):
        assert sanitize_log_line("Synthesis completed") == "Synthesis completed"


# -- truncate_to_width --


class TestTruncateToWidth:
    def test_short_text_passes(self):
        assert truncate_to_width("hi", 80) == "hi"

    def test_long_text_truncated(self):
        text = "x" * 100
        result = truncate_to_width(text, 20)
        assert len(result) == 20
        assert result.endswith("...")

    def test_exact_width(self):
        text = "x" * 10
        assert truncate_to_width(text, 10) == text

    def test_zero_width(self):
        assert truncate_to_width("hello", 0) == ""

    def test_small_width(self):
        assert truncate_to_width("hello", 2) == "he"


# -- RunProgressRenderer --


class TestRunProgressRenderer:
    def test_running_writes_log_prefix(self):
        buf = FakeTTYStderr(isatty_value=True)
        r = RunProgressRenderer(buf, width_fn=lambda: 80)
        r.running("working...")
        output = "".join(buf.written)
        assert output.startswith("\r\x1b[K")
        assert "  log: working..." in output

    def test_clear_noop_without_transient(self):
        buf = FakeTTYStderr(isatty_value=True)
        r = RunProgressRenderer(buf, width_fn=lambda: 80)
        r.clear()
        assert buf.written == []

    def test_truncates_long_running_text(self):
        buf = FakeTTYStderr(isatty_value=True)
        r = RunProgressRenderer(buf, width_fn=lambda: 20)
        r.running("x" * 100)
        output = "".join(buf.written)
        display = output.replace("\r\x1b[K", "")
        assert len(display) <= 20

    def test_start_step_emits_header(self):
        buf = FakeTTYStderr(isatty_value=True)
        r = RunProgressRenderer(buf, width_fn=lambda: 80)
        r.start_step("synthesis", "yosys")
        output = "".join(buf.written)
        assert "> synthesis (yosys)\n" in output

    def test_start_step_separator_after_first(self):
        buf = FakeTTYStderr(isatty_value=True)
        r = RunProgressRenderer(buf, width_fn=lambda: 80)
        r.start_step("synthesis", "yosys")
        r.start_step("floorplan", "ecc")
        output = "".join(buf.written)
        assert "\n> floorplan (ecc)\n" in output

    def test_start_step_no_separator_before_first(self):
        buf = FakeTTYStderr(isatty_value=True)
        r = RunProgressRenderer(buf, width_fn=lambda: 80)
        r.start_step("synthesis", "yosys")
        output = "".join(buf.written)
        assert not output.startswith("\n")

    def test_start_run_emits_header(self):
        buf = FakeTTYStderr(isatty_value=True)
        r = RunProgressRenderer(buf, width_fn=lambda: 80)
        r.start_run("default", "/tmp/runs/default")
        output = "".join(buf.written)
        assert "[run] default workspace=/tmp/runs/default\n" in output

    def test_finish_step_success(self):
        buf = FakeTTYStderr(isatty_value=True)
        r = RunProgressRenderer(buf, width_fn=lambda: 80)
        r.finish_step(
            "synthesis",
            "yosys",
            "success",
            "0:00:06",
            "output/synth.log",
            "ecc log synthesis --errors",
            success=True,
        )
        output = "".join(buf.written)
        assert "✓ synthesis (yosys) 0:00:06\n" in output
        assert "  log: output/synth.log\n" in output
        assert "  inspect: ecc log synthesis --errors\n" in output

    def test_finish_step_non_success(self):
        buf = FakeTTYStderr(isatty_value=True)
        r = RunProgressRenderer(buf, width_fn=lambda: 80)
        r.finish_step(
            "placement",
            "dreamplace",
            "incomplete",
            "0:00:00",
            "",
            "ecc log placement --errors",
            success=False,
        )
        output = "".join(buf.written)
        assert "✗ placement (dreamplace) incomplete 0:00:00\n" in output
        assert "  log: \n" in output
        assert "  inspect: ecc log placement --errors\n" in output

    def test_finish_step_clears_transient_to_clean_line(self):
        buf = FakeTTYStderr(isatty_value=True)
        r = RunProgressRenderer(buf, width_fn=lambda: 80)
        r.running("transient log")
        r.finish_step("synthesis", "yosys", "success", "0:00:06", "log", "cmd", success=True)
        output = "".join(buf.written)
        # The final clear before the summary must move to a clean line
        assert "\r\x1b[K\n✓ synthesis" in output

    def test_finish_step_non_success_clears_transient_to_clean_line(self):
        buf = FakeTTYStderr(isatty_value=True)
        r = RunProgressRenderer(buf, width_fn=lambda: 80)
        r.running("transient log")
        r.finish_step("placement", "dreamplace", "incomplete", "0:00:00", "", "cmd", success=False)
        output = "".join(buf.written)
        assert "\r\x1b[K\n✗ placement" in output

    def test_running_with_color(self):
        buf = FakeTTYStderr(isatty_value=True)
        r = RunProgressRenderer(buf, width_fn=lambda: 80, color=True)
        r.running("working...")
        output = "".join(buf.written)
        assert DIM in output
        assert "log:" in output

    def test_running_without_color(self):
        buf = FakeTTYStderr(isatty_value=True)
        r = RunProgressRenderer(buf, width_fn=lambda: 80, color=False)
        r.running("working...")
        output = "".join(buf.written)
        assert DIM not in output

    def test_no_color_codes_when_disabled(self):
        buf = FakeTTYStderr(isatty_value=True)
        r = RunProgressRenderer(buf, width_fn=lambda: 80, color=False)
        r.start_run("default", "/tmp")
        r.start_step("synthesis", "yosys")
        r.finish_step("synthesis", "yosys", "success", "0:00:06", "log", "cmd", success=True)
        output = "".join(buf.written)
        for code in (BOLD, DIM, CYAN, GREEN, RED):
            assert code not in output

    def test_start_step_with_color(self):
        buf = FakeTTYStderr(isatty_value=True)
        r = RunProgressRenderer(buf, width_fn=lambda: 80, color=True)
        r.start_step("synthesis", "yosys")
        output = "".join(buf.written)
        assert CYAN in output
        # Cyan sequence must appear before the `>` marker in raw output
        cyan_pos = output.find(CYAN)
        marker_pos = output.find(">")
        assert cyan_pos < marker_pos

    def test_start_run_with_color(self):
        buf = FakeTTYStderr(isatty_value=True)
        r = RunProgressRenderer(buf, width_fn=lambda: 80, color=True)
        r.start_run("default", "/tmp")
        output = "".join(buf.written)
        assert BOLD in output

    def test_finish_step_success_with_color(self):
        buf = FakeTTYStderr(isatty_value=True)
        r = RunProgressRenderer(buf, width_fn=lambda: 80, color=True)
        r.finish_step("synthesis", "yosys", "success", "0:00:06", "log", "cmd", success=True)
        output = "".join(buf.written)
        assert GREEN in output

    def test_finish_step_non_success_with_color(self):
        buf = FakeTTYStderr(isatty_value=True)
        r = RunProgressRenderer(buf, width_fn=lambda: 80, color=True)
        r.finish_step("placement", "dreamplace", "incomplete", "0:00:00", "", "cmd", success=False)
        output = "".join(buf.written)
        assert RED in output


# -- progress stream / stdio guard helpers --


class TestStableProgressStream:
    def test_fallback_returns_stream_without_fileno(self):
        buf = FakeTTYStderr(isatty_value=True)

        stream = progress._stable_stream_from(buf)

        assert stream is buf

    def test_uses_dup_for_fd_backed_stream(self, capfd):
        stream = progress._stable_stream_from(sys.stderr)
        saved_stderr_fd = os.dup(2)
        devnull_fd = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(devnull_fd, 2)
            stream.write("stable stderr\n")
            stream.flush()
        finally:
            stream.close()
            os.dup2(saved_stderr_fd, 2)
            os.close(saved_stderr_fd)
            os.close(devnull_fd)

        captured = capfd.readouterr()
        assert "stable stderr" in captured.err

    def test_preserves_fd_stream_error_handler(self, tmp_path):
        path = tmp_path / "stderr.txt"
        with open(path, "w", encoding="ascii", errors="backslashreplace") as original:
            stream = progress._stable_stream_from(original)
            try:
                stream.write("✓\n")
                stream.flush()
            finally:
                stream.close()

        assert "\\u2713" in path.read_text()


# ---------------------------------------------------------------------------
# Failure context block formatting (AC-5)
# ---------------------------------------------------------------------------


class TestFormatErrorContext:
    def test_first_line_is_error_log_path(self):
        ctx_lines = [LogLine(10, LineKind.ERROR, "Error: something")]
        out = format_error_context("log/synthesis.log", ctx_lines, "ecc log synthesis", color=False)
        assert out.startswith("error: log/synthesis.log")

    def test_includes_numbered_context_lines(self):
        ctx_lines = [
            LogLine(8, LineKind.INFO, "INFO: before"),
            LogLine(9, LineKind.WARNING, "Warning: careful"),
            LogLine(10, LineKind.ERROR, "Error: failed"),
        ]
        out = format_error_context("log/synthesis.log", ctx_lines, "ecc log synthesis", color=False)
        for ll in ctx_lines:
            assert str(ll.line_no) in out
            assert ll.text in out

    def test_compact_kind_labels(self):
        ctx_lines = [
            LogLine(5, LineKind.ERROR, "bad"),
            LogLine(6, LineKind.WARNING, "meh"),
            LogLine(7, LineKind.TRACEBACK, "  File ..."),
            LogLine(8, LineKind.INFO, "ok"),
        ]
        out = format_error_context("log/p.log", ctx_lines, "ecc log step", color=False)
        assert "ERROR" in out
        assert "WARN" in out
        assert "TRACE" in out
        assert "INFO" in out

    def test_footer_includes_for_more_log_info(self):
        ctx_lines = [LogLine(1, LineKind.ERROR, "failed")]
        out = format_error_context(
            "log/p.log", ctx_lines, "ecc log synthesis --project myproj", color=False
        )
        assert "For more log info:" in out
        assert "ecc log synthesis --project myproj" in out

    def test_footer_includes_command_grep_field(self):
        ctx_lines = [LogLine(1, LineKind.ERROR, "failed")]
        log_cmd = "ecc log synthesis --project myproj --run-id abc123"
        out = format_error_context("log/p.log", ctx_lines, log_cmd, color=False)
        assert 'command="ecc log synthesis --project myproj --run-id abc123"' in out

    def test_project_and_run_id_preserved_in_footer(self):
        ctx_lines = [LogLine(1, LineKind.ERROR, "failed")]
        log_cmd = "ecc log synthesis --project /path/to/proj --run-id run42"
        out = format_error_context("log/p.log", ctx_lines, log_cmd, color=False)
        assert "--project /path/to/proj" in out
        assert "--run-id run42" in out

    def test_color_gating_no_ansi_when_disabled(self):
        ctx_lines = [LogLine(10, LineKind.ERROR, "Error: bad")]
        out = format_error_context("log/p.log", ctx_lines, "ecc log step", color=False)
        assert "\x1b[" not in out

    def test_color_gating_ansi_when_enabled(self):
        ctx_lines = [LogLine(10, LineKind.ERROR, "Error: bad")]
        out = format_error_context("log/p.log", ctx_lines, "ecc log step", color=True)
        assert "\x1b[" in out

    def test_line_number_padding_consistent(self):
        ctx_lines = [
            LogLine(1, LineKind.PLAIN, "first"),
            LogLine(10, LineKind.ERROR, "error"),
            LogLine(100, LineKind.PLAIN, "hundred"),
        ]
        out = format_error_context("log/p.log", ctx_lines, "ecc log step", color=False)
        lines = out.strip().split("\n")
        context_lines = [
            line
            for line in lines
            if line.strip()
            and not line.startswith("error:")
            and not line.startswith("For")
            and not line.startswith("command=")
        ]
        for line in context_lines:
            assert line.startswith(" ")

    def test_empty_context(self):
        out = format_error_context("log/p.log", [], "ecc log step", color=False)
        assert "error: log/p.log" in out
        assert "For more log info:" in out


# ---------------------------------------------------------------------------
# run_flow_with_progress (worker-driven)
# ---------------------------------------------------------------------------


def _write_flow_json(workspace_dir, steps):
    home = Path(workspace_dir) / "home"
    home.mkdir(parents=True, exist_ok=True)
    (home / "flow.json").write_text(json.dumps({"steps": steps}))


def _step_record(name, tool, state, runtime="0:00:01"):
    return {"name": name, "tool": tool, "state": state, "runtime": runtime}


def _write_archived_log(workspace_dir, step, tool, content):
    log_path = Path(workspace_dir) / f"{step}_{tool}" / "log" / f"{step}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(content)
    return log_path


def _make_operation(workspace_dir, events, result):
    """Replay reader-callback events against a flow.json progression."""

    def run_operation(on_output, on_step_event):
        for event in events:
            kind = event[0]
            if kind == "begin":
                on_step_event("begin", event[1], event[2])
            elif kind == "output":
                on_output(event[1])
            elif kind == "states":
                _write_flow_json(workspace_dir, event[1])
        return result

    return run_operation


class TestRunFlowWithProgress:
    def test_success_summary_format(self, tmp_path):
        workspace = tmp_path / "workspace"
        _write_flow_json(workspace, [_step_record("Synthesis", "yosys", "Unstart")])
        operation = _make_operation(
            workspace,
            [
                ("begin", "Synthesis", "yosys"),
                ("states", [_step_record("Synthesis", "yosys", "Success")]),
            ],
            OperationResult(success=True, exit_code=0),
        )

        buf = FakeTTYStderr(isatty_value=True)
        result = run_flow_with_progress(str(workspace), _make_ctx(), None, buf, operation)

        assert result.success is True
        output = "".join(buf.written)
        assert "✓ synthesis (yosys)" in output

    def test_result_passed_through(self, tmp_path):
        workspace = tmp_path / "workspace"
        _write_flow_json(workspace, [])
        failure = OperationResult(success=False, error="worker exploded")
        operation = _make_operation(workspace, [], failure)

        buf = FakeTTYStderr(isatty_value=True)
        result = run_flow_with_progress(str(workspace), _make_ctx(), None, buf, operation)

        assert result is failure

    def test_step_headers_emitted(self, tmp_path):
        workspace = tmp_path / "workspace"
        _write_flow_json(workspace, [])
        operation = _make_operation(
            workspace,
            [
                ("begin", "Synthesis", "yosys"),
                ("begin", "Floorplan", "ecc"),
            ],
            OperationResult(success=True, exit_code=0),
        )

        buf = FakeTTYStderr(isatty_value=True)
        run_flow_with_progress(str(workspace), _make_ctx(), None, buf, operation)
        plain = _strip_ansi("".join(buf.written))
        assert "> synthesis (yosys)\n" in plain
        assert "> floorplan (ecc)\n" in plain

    def test_run_header_emitted(self, tmp_path):
        workspace = tmp_path / "workspace"
        _write_flow_json(workspace, [])
        operation = _make_operation(workspace, [], OperationResult(success=True, exit_code=0))

        buf = FakeTTYStderr(isatty_value=True)
        run_flow_with_progress(str(workspace), _make_ctx(), None, buf, operation)
        output = "".join(buf.written)
        assert "[run]" in output
        assert "workspace=" in output

    def test_run_label_uses_ctx_run_id(self, tmp_path):
        workspace = tmp_path / "workspace"
        _write_flow_json(workspace, [])
        operation = _make_operation(workspace, [], OperationResult(success=True, exit_code=0))

        buf = FakeTTYStderr(isatty_value=True)
        run_flow_with_progress(
            str(workspace), _make_ctx(run_id="sweeps/s1/r4"), None, buf, operation
        )
        plain = _strip_ansi("".join(buf.written))
        assert f"[run] sweeps/s1/r4 workspace={workspace}\n" in plain

    def test_summary_includes_inspect_detail_line(self, tmp_path):
        workspace = tmp_path / "workspace"
        _write_flow_json(workspace, [_step_record("Synthesis", "yosys", "Unstart")])
        operation = _make_operation(
            workspace,
            [
                ("begin", "Synthesis", "yosys"),
                ("states", [_step_record("Synthesis", "yosys", "Success")]),
            ],
            OperationResult(success=True, exit_code=0),
        )

        buf = FakeTTYStderr(isatty_value=True)
        run_flow_with_progress(str(workspace), _make_ctx(), "myproject", buf, operation)
        plain = _strip_ansi("".join(buf.written))
        assert "  inspect: ecc log synthesis --project myproject\n" in plain

    def test_inspect_detail_carries_run_id(self, tmp_path):
        workspace = tmp_path / "workspace"
        _write_flow_json(workspace, [_step_record("Synthesis", "yosys", "Unstart")])
        operation = _make_operation(
            workspace,
            [("states", [_step_record("Synthesis", "yosys", "Success")])],
            OperationResult(success=True, exit_code=0),
        )

        buf = FakeTTYStderr(isatty_value=True)
        run_flow_with_progress(
            str(workspace), _make_ctx(run_id="exp1"), "myproject", buf, operation
        )
        plain = _strip_ansi("".join(buf.written))
        assert "  inspect: ecc log synthesis --project myproject --run-id exp1\n" in plain

    def test_summary_includes_log_detail_line(self, tmp_path):
        workspace = tmp_path / "workspace"
        _write_flow_json(workspace, [_step_record("Synthesis", "yosys", "Unstart")])
        operation = _make_operation(
            workspace,
            [
                ("begin", "Synthesis", "yosys"),
                ("states", [_step_record("Synthesis", "yosys", "Success")]),
            ],
            OperationResult(success=True, exit_code=0),
        )

        buf = FakeTTYStderr(isatty_value=True)
        run_flow_with_progress(str(workspace), _make_ctx(), None, buf, operation)
        plain = _strip_ansi("".join(buf.written))
        assert "  log: Synthesis_yosys/log/Synthesis.log" in plain

    def test_block_separator_between_steps(self, tmp_path):
        workspace = tmp_path / "workspace"
        _write_flow_json(workspace, [])
        operation = _make_operation(
            workspace,
            [
                ("begin", "Synthesis", "yosys"),
                ("states", [_step_record("Synthesis", "yosys", "Success")]),
                ("begin", "Floorplan", "ecc"),
            ],
            OperationResult(success=True, exit_code=0),
        )

        buf = FakeTTYStderr(isatty_value=True)
        run_flow_with_progress(str(workspace), _make_ctx(), None, buf, operation)
        output = "".join(buf.written)
        synth_summary = output.find("✓ synthesis")
        fp_header = output.find("> floorplan")
        assert synth_summary >= 0
        assert fp_header >= 0
        assert "\n\n" in output[synth_summary:fp_header]

    def test_previous_step_rendered_before_next_header(self, tmp_path):
        workspace = tmp_path / "workspace"
        _write_flow_json(workspace, [])
        operation = _make_operation(
            workspace,
            [
                ("begin", "Synthesis", "yosys"),
                ("states", [_step_record("Synthesis", "yosys", "Success")]),
                ("begin", "Floorplan", "ecc"),
            ],
            OperationResult(success=True, exit_code=0),
        )

        buf = FakeTTYStderr(isatty_value=True)
        run_flow_with_progress(str(workspace), _make_ctx(), None, buf, operation)
        output = "".join(buf.written)
        synth_summary = output.find("✓ synthesis")
        fp_header = output.find("> floorplan")
        assert synth_summary >= 0
        assert fp_header > synth_summary

    def test_failure_summary_includes_status(self, tmp_path):
        workspace = tmp_path / "workspace"
        _write_flow_json(workspace, [])
        operation = _make_operation(
            workspace,
            [
                ("begin", "Synthesis", "yosys"),
                ("states", [_step_record("Synthesis", "yosys", "Success")]),
                ("begin", "Floorplan", "ecc"),
                ("states", [_step_record("Floorplan", "ecc", "Imcomplete", "0:00:02")]),
            ],
            OperationResult(success=False, error="run flow failed"),
        )

        buf = FakeTTYStderr(isatty_value=True)
        result = run_flow_with_progress(str(workspace), _make_ctx(), None, buf, operation)
        assert result.success is False
        plain = _strip_ansi("".join(buf.written))
        assert "✗ floorplan (ecc)" in plain
        assert "imcomplete" in plain

    def test_transient_line_shows_log_content(self, tmp_path):
        workspace = tmp_path / "workspace"
        _write_flow_json(workspace, [_step_record("Synthesis", "yosys", "Unstart")])
        operation = _make_operation(
            workspace,
            [
                ("begin", "Synthesis", "yosys"),
                ("output", b"Synthesizing module top\n"),
                ("states", [_step_record("Synthesis", "yosys", "Success")]),
            ],
            OperationResult(success=True, exit_code=0),
        )

        buf = FakeTTYStderr(isatty_value=True)
        run_flow_with_progress(str(workspace), _make_ctx(), None, buf, operation)
        plain = _strip_ansi("".join(buf.written))
        assert "Synthesizing module top" in plain

        log_pos = plain.find("Synthesizing module top")
        summary_pos = plain.find("✓ synthesis")
        assert log_pos >= 0
        assert summary_pos >= 0
        assert log_pos < summary_pos

    def test_output_burst_is_throttled(self, tmp_path):
        workspace = tmp_path / "workspace"
        _write_flow_json(workspace, [_step_record("Synthesis", "yosys", "Unstart")])
        operation = _make_operation(
            workspace,
            [
                ("begin", "Synthesis", "yosys"),
                ("output", b"line one\n"),
                ("output", b"line two\n"),
            ],
            OperationResult(success=True, exit_code=0),
        )

        buf = FakeTTYStderr(isatty_value=True)
        run_flow_with_progress(str(workspace), _make_ctx(), None, buf, operation)
        plain = _strip_ansi("".join(buf.written))
        assert "line one" in plain
        assert "line two" not in plain

    def test_marker_text_never_rendered(self, tmp_path):
        workspace = tmp_path / "workspace"
        _write_flow_json(workspace, [_step_record("Synthesis", "yosys", "Unstart")])
        operation = _make_operation(
            workspace,
            [
                ("begin", "Synthesis", "yosys"),
                ("states", [_step_record("Synthesis", "yosys", "Success")]),
            ],
            OperationResult(success=True, exit_code=0),
        )

        buf = FakeTTYStderr(isatty_value=True)
        run_flow_with_progress(str(workspace), _make_ctx(), None, buf, operation)
        plain = _strip_ansi("".join(buf.written))
        assert "ECC-STEP" not in plain

    def test_color_enabled_for_tty_text(self, tmp_path, monkeypatch):
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.setenv("TERM", "xterm-256color")
        workspace = tmp_path / "workspace"
        _write_flow_json(workspace, [])
        operation = _make_operation(
            workspace,
            [("begin", "Synthesis", "yosys")],
            OperationResult(success=True, exit_code=0),
        )

        buf = FakeTTYStderr(isatty_value=True)
        run_flow_with_progress(str(workspace), _make_ctx(), None, buf, operation)
        output = "".join(buf.written)
        assert "\x1b[36m" in output  # cyan for step header

    def test_color_disabled_for_non_tty(self, tmp_path):
        workspace = tmp_path / "workspace"
        _write_flow_json(workspace, [])
        operation = _make_operation(
            workspace,
            [("begin", "Synthesis", "yosys")],
            OperationResult(success=True, exit_code=0),
        )

        buf = FakeTTYStderr(isatty_value=False)
        run_flow_with_progress(str(workspace), _make_ctx(), None, buf, operation)
        output = "".join(buf.written)
        for code in (BOLD, CYAN, GREEN, RED, DIM):
            assert code not in output


# ---------------------------------------------------------------------------
# Failure context progress integration
# ---------------------------------------------------------------------------


class TestFailureContextIntegration:
    def test_failed_step_prints_context_block(self, tmp_path):
        workspace = tmp_path / "workspace"
        _write_flow_json(workspace, [_step_record("Synthesis", "yosys", "Unstart")])
        _write_archived_log(
            workspace, "Synthesis", "yosys", "line 1\nline 2\nError: something failed\nline 4\n"
        )
        operation = _make_operation(
            workspace,
            [
                ("begin", "Synthesis", "yosys"),
                ("states", [_step_record("Synthesis", "yosys", "Imcomplete")]),
            ],
            OperationResult(success=False, error="run flow failed"),
        )

        buf = FakeTTYStderr(isatty_value=True)
        result = run_flow_with_progress(str(workspace), _make_ctx(), "myproj", buf, operation)
        assert result.success is False
        plain = _strip_ansi("".join(buf.written))
        assert "error:" in plain
        assert "For more log info:" in plain
        assert 'command="' in plain

    def test_successful_step_no_context_block(self, tmp_path):
        workspace = tmp_path / "workspace"
        _write_flow_json(workspace, [_step_record("Synthesis", "yosys", "Unstart")])
        _write_archived_log(workspace, "Synthesis", "yosys", "line 1\nline 2\nall good\n")
        operation = _make_operation(
            workspace,
            [
                ("begin", "Synthesis", "yosys"),
                ("states", [_step_record("Synthesis", "yosys", "Success")]),
            ],
            OperationResult(success=True, exit_code=0),
        )

        buf = FakeTTYStderr(isatty_value=True)
        result = run_flow_with_progress(str(workspace), _make_ctx(), "myproj", buf, operation)
        assert result.success is True
        plain = _strip_ansi("".join(buf.written))
        assert "error:" not in plain
        assert "For more log info:" not in plain

    def test_missing_log_no_context_block(self, tmp_path):
        workspace = tmp_path / "workspace"
        _write_flow_json(workspace, [_step_record("Synthesis", "yosys", "Unstart")])
        operation = _make_operation(
            workspace,
            [("states", [_step_record("Synthesis", "yosys", "Imcomplete")])],
            OperationResult(success=False, error="run flow failed"),
        )

        buf = FakeTTYStderr(isatty_value=True)
        result = run_flow_with_progress(str(workspace), _make_ctx(), "myproj", buf, operation)
        assert result.success is False
        plain = _strip_ansi("".join(buf.written))
        assert "error:" not in plain
        assert "For more log info:" not in plain
        assert "log:" in plain
        assert "inspect:" in plain

    def test_empty_log_no_context_block(self, tmp_path):
        workspace = tmp_path / "workspace"
        _write_flow_json(workspace, [_step_record("Synthesis", "yosys", "Unstart")])
        _write_archived_log(workspace, "Synthesis", "yosys", "")
        operation = _make_operation(
            workspace,
            [("states", [_step_record("Synthesis", "yosys", "Imcomplete")])],
            OperationResult(success=False, error="run flow failed"),
        )

        buf = FakeTTYStderr(isatty_value=True)
        result = run_flow_with_progress(str(workspace), _make_ctx(), "myproj", buf, operation)
        assert result.success is False
        plain = _strip_ansi("".join(buf.written))
        assert "For more log info:" not in plain

    def test_existing_log_and_inspect_lines_remain(self, tmp_path):
        workspace = tmp_path / "workspace"
        _write_flow_json(workspace, [_step_record("Synthesis", "yosys", "Unstart")])
        _write_archived_log(workspace, "Synthesis", "yosys", "line 1\nError: fail\nline 3\n")
        operation = _make_operation(
            workspace,
            [("states", [_step_record("Synthesis", "yosys", "Imcomplete")])],
            OperationResult(success=False, error="run flow failed"),
        )

        buf = FakeTTYStderr(isatty_value=True)
        result = run_flow_with_progress(str(workspace), _make_ctx(), "myproj", buf, operation)
        assert result.success is False
        plain = _strip_ansi("".join(buf.written))
        assert "log:" in plain
        assert "inspect:" in plain

    def test_context_block_no_blank_lines_between_rows(self, tmp_path):
        workspace = tmp_path / "workspace"
        _write_flow_json(workspace, [_step_record("Synthesis", "yosys", "Unstart")])
        _write_archived_log(
            workspace, "Synthesis", "yosys", "line one\nline two\nError: boom\nline four\n"
        )
        operation = _make_operation(
            workspace,
            [("states", [_step_record("Synthesis", "yosys", "Imcomplete")])],
            OperationResult(success=False, error="run flow failed"),
        )

        buf = FakeTTYStderr(isatty_value=True)
        result = run_flow_with_progress(str(workspace), _make_ctx(), "myproj", buf, operation)
        assert result.success is False
        raw = "".join(buf.written)

        header_pos = raw.find("error:")
        footer_pos = raw.find("For more log info:", header_pos)
        assert header_pos >= 0
        assert footer_pos > header_pos

        block = raw[header_pos:footer_pos]
        plain_block = _strip_ansi(block)
        all_lines = plain_block.rstrip("\n").split("\n")

        body_lines = [line for line in all_lines if not line.startswith("error:")]
        assert len(body_lines) > 0

        for i, line in enumerate(body_lines):
            assert line.strip() != "", f"blank line at index {i} in context block: {body_lines!r}"
            assert line.startswith(" "), f"context row not indented at index {i}: {line!r}"
