import io
import re
import time

import pytest

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def _strip_ansi(text):
    return _ANSI_RE.sub("", text)

from chipcompiler.cli.progress import (
    _BOLD,
    _CYAN,
    _DIM,
    _GREEN,
    _RED,
    _RESET,
    RunProgressRenderer,
    latest_log_line,
    sanitize_log_line,
    should_enable_run_progress,
    style,
    supports_color,
    truncate_to_width,
)
from chipcompiler.cli.types import CommandContext, OutputMode


class FakeTTYStderr:
    def __init__(self, isatty_value=True):
        self._isatty = isatty_value
        self.written = []

    def isatty(self):
        return self._isatty

    def write(self, s):
        self.written.append(s)

    def flush(self):
        pass


def _make_ctx(mode=OutputMode.TEXT):
    return CommandContext(
        project_dir="/tmp/project",
        project=None,
        run_dir="/tmp/project/runs/default",
        run_id=None,
        output_mode=mode,
    )


# -- supports_color --


class TestSupportsColor:
    def test_enabled_text_tty(self):
        assert supports_color(FakeTTYStderr(True), OutputMode.TEXT, {"TERM": "xterm-256color"}) is True

    def test_disabled_non_tty(self):
        assert supports_color(FakeTTYStderr(False), OutputMode.TEXT) is False

    def test_disabled_no_isattr(self):
        assert supports_color(io.StringIO(), OutputMode.TEXT) is False

    def test_disabled_no_color(self):
        assert supports_color(FakeTTYStderr(True), OutputMode.TEXT, {"NO_COLOR": "1"}) is False

    def test_disabled_term_dumb(self):
        assert supports_color(FakeTTYStderr(True), OutputMode.TEXT, {"TERM": "dumb"}) is False

    def test_disabled_json(self):
        assert supports_color(FakeTTYStderr(True), OutputMode.JSON) is False

    def test_disabled_jsonl(self):
        assert supports_color(FakeTTYStderr(True), OutputMode.JSONL) is False

    def test_enabled_with_clean_env(self):
        assert supports_color(FakeTTYStderr(True), OutputMode.TEXT, {"TERM": "xterm-256color"}) is True


# -- style --


class TestStyle:
    def test_applies_code_when_enabled(self):
        result = style("hello", _GREEN, True)
        assert result == f"{_GREEN}hello{_RESET}"

    def test_passthrough_when_disabled(self):
        assert style("hello", _GREEN, False) == "hello"


# -- should_enable_run_progress --


class TestShouldEnableRunProgress:
    def test_enabled_text_tty(self):
        ctx = _make_ctx(OutputMode.TEXT)
        assert should_enable_run_progress(ctx, FakeTTYStderr(True)) is True

    def test_disabled_json(self):
        ctx = _make_ctx(OutputMode.JSON)
        assert should_enable_run_progress(ctx, FakeTTYStderr(True)) is False

    def test_disabled_jsonl(self):
        ctx = _make_ctx(OutputMode.JSONL)
        assert should_enable_run_progress(ctx, FakeTTYStderr(True)) is False

    def test_disabled_no_tty(self):
        ctx = _make_ctx(OutputMode.TEXT)
        assert should_enable_run_progress(ctx, FakeTTYStderr(False)) is False

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


# -- latest_log_line --


class TestLatestLogLine:
    def test_returns_last_nonempty_line(self, tmp_path):
        log = tmp_path / "test.log"
        log.write_text("line one\nline two\n\n")
        assert latest_log_line(str(log)) == "line two"

    def test_returns_none_for_missing_file(self):
        assert latest_log_line("/nonexistent/file.log") is None

    def test_returns_none_for_empty_file(self, tmp_path):
        log = tmp_path / "empty.log"
        log.write_text("")
        assert latest_log_line(str(log)) is None

    def test_returns_none_for_none_path(self):
        assert latest_log_line(None) is None

    def test_sanitizes_ansi_in_line(self, tmp_path):
        log = tmp_path / "ansi.log"
        log.write_text("\x1b[32mprogress\x1b[0m\n")
        assert latest_log_line(str(log)) == "progress"

    def test_trailing_newlines_only(self, tmp_path):
        log = tmp_path / "nl.log"
        log.write_text("\n\n\n")
        assert latest_log_line(str(log)) is None


# -- RunProgressRenderer --


class TestRunProgressRenderer:
    def test_running_writes_log_prefix(self):
        buf = FakeTTYStderr(True)
        r = RunProgressRenderer(buf, width_fn=lambda: 80)
        r.running("working...")
        output = "".join(buf.written)
        assert output.startswith("\r\x1b[K")
        assert "  log: working..." in output

    def test_clear_noop_without_transient(self):
        buf = FakeTTYStderr(True)
        r = RunProgressRenderer(buf, width_fn=lambda: 80)
        r.clear()
        assert buf.written == []

    def test_truncates_long_running_text(self):
        buf = FakeTTYStderr(True)
        r = RunProgressRenderer(buf, width_fn=lambda: 20)
        r.running("x" * 100)
        output = "".join(buf.written)
        display = output.replace("\r\x1b[K", "")
        assert len(display) <= 20

    def test_start_step_emits_header(self):
        buf = FakeTTYStderr(True)
        r = RunProgressRenderer(buf, width_fn=lambda: 80)
        r.start_step("synthesis", "yosys")
        output = "".join(buf.written)
        assert "> synthesis (yosys)\n" in output

    def test_start_step_separator_after_first(self):
        buf = FakeTTYStderr(True)
        r = RunProgressRenderer(buf, width_fn=lambda: 80)
        r.start_step("synthesis", "yosys")
        r.start_step("floorplan", "ecc")
        output = "".join(buf.written)
        assert "\n> floorplan (ecc)\n" in output

    def test_start_step_no_separator_before_first(self):
        buf = FakeTTYStderr(True)
        r = RunProgressRenderer(buf, width_fn=lambda: 80)
        r.start_step("synthesis", "yosys")
        output = "".join(buf.written)
        assert not output.startswith("\n")

    def test_start_run_emits_header(self):
        buf = FakeTTYStderr(True)
        r = RunProgressRenderer(buf, width_fn=lambda: 80)
        r.start_run("default", "/tmp/runs/default")
        output = "".join(buf.written)
        assert "[run] default workspace=/tmp/runs/default\n" in output

    def test_finish_step_success(self):
        buf = FakeTTYStderr(True)
        r = RunProgressRenderer(buf, width_fn=lambda: 80)
        r.finish_step("synthesis", "yosys", "success", "0:00:06", "output/synth.log", "ecc log synthesis --errors", True)
        output = "".join(buf.written)
        assert "✓ synthesis (yosys) 0:00:06\n" in output
        assert "  log: output/synth.log\n" in output
        assert "  inspect: ecc log synthesis --errors\n" in output

    def test_finish_step_non_success(self):
        buf = FakeTTYStderr(True)
        r = RunProgressRenderer(buf, width_fn=lambda: 80)
        r.finish_step("placement", "dreamplace", "incomplete", "0:00:00", "", "ecc log placement --errors", False)
        output = "".join(buf.written)
        assert "✗ placement (dreamplace) incomplete 0:00:00\n" in output
        assert "  log: \n" in output
        assert "  inspect: ecc log placement --errors\n" in output

    def test_finish_step_clears_transient_to_clean_line(self):
        buf = FakeTTYStderr(True)
        r = RunProgressRenderer(buf, width_fn=lambda: 80)
        r.running("transient log")
        r.finish_step("synthesis", "yosys", "success", "0:00:06", "log", "cmd", True)
        output = "".join(buf.written)
        # The final clear before the summary must move to a clean line
        assert "\r\x1b[K\n✓ synthesis" in output

    def test_finish_step_non_success_clears_transient_to_clean_line(self):
        buf = FakeTTYStderr(True)
        r = RunProgressRenderer(buf, width_fn=lambda: 80)
        r.running("transient log")
        r.finish_step("placement", "dreamplace", "incomplete", "0:00:00", "", "cmd", False)
        output = "".join(buf.written)
        assert "\r\x1b[K\n✗ placement" in output

    def test_running_with_color(self):
        buf = FakeTTYStderr(True)
        r = RunProgressRenderer(buf, width_fn=lambda: 80, color=True)
        r.running("working...")
        output = "".join(buf.written)
        assert _DIM in output
        assert "log:" in output

    def test_running_without_color(self):
        buf = FakeTTYStderr(True)
        r = RunProgressRenderer(buf, width_fn=lambda: 80, color=False)
        r.running("working...")
        output = "".join(buf.written)
        assert _DIM not in output

    def test_no_color_codes_when_disabled(self):
        buf = FakeTTYStderr(True)
        r = RunProgressRenderer(buf, width_fn=lambda: 80, color=False)
        r.start_run("default", "/tmp")
        r.start_step("synthesis", "yosys")
        r.finish_step("synthesis", "yosys", "success", "0:00:06", "log", "cmd", True)
        output = "".join(buf.written)
        for code in (_BOLD, _DIM, _CYAN, _GREEN, _RED):
            assert code not in output

    def test_start_step_with_color(self):
        buf = FakeTTYStderr(True)
        r = RunProgressRenderer(buf, width_fn=lambda: 80, color=True)
        r.start_step("synthesis", "yosys")
        output = "".join(buf.written)
        assert _CYAN in output
        # Cyan sequence must appear before the `>` marker in raw output
        cyan_pos = output.find(_CYAN)
        marker_pos = output.find(">")
        assert cyan_pos < marker_pos

    def test_start_run_with_color(self):
        buf = FakeTTYStderr(True)
        r = RunProgressRenderer(buf, width_fn=lambda: 80, color=True)
        r.start_run("default", "/tmp")
        output = "".join(buf.written)
        assert _BOLD in output

    def test_finish_step_success_with_color(self):
        buf = FakeTTYStderr(True)
        r = RunProgressRenderer(buf, width_fn=lambda: 80, color=True)
        r.finish_step("synthesis", "yosys", "success", "0:00:06", "log", "cmd", True)
        output = "".join(buf.written)
        assert _GREEN in output

    def test_finish_step_non_success_with_color(self):
        buf = FakeTTYStderr(True)
        r = RunProgressRenderer(buf, width_fn=lambda: 80, color=True)
        r.finish_step("placement", "dreamplace", "incomplete", "0:00:00", "", "cmd", False)
        output = "".join(buf.written)
        assert _RED in output


# -- run_flow_with_progress --


def _make_ws(directory="/tmp", log_section_fn=None):
    section_fn = log_section_fn or (lambda self, msg: None)
    return type("WS", (), {
        "home": type("Home", (), {"reset": lambda self: None})(),
        "logger": type("L", (), {
            "info": lambda *a, **k: None,
            "log_section": section_fn,
            "log_separator": lambda *a, **k: None,
        })(),
        "flow": type("F", (), {"data": {"steps": []}, "path": ""})(),
        "directory": directory,
    })()


def _make_step(name, tool, log_file=""):
    return type("WSS", (), {"name": name, "tool": tool, "log": {"file": log_file}})()


def _make_flow(ws, steps, run_step_fn):
    return type("EF", (), {
        "workspace": ws,
        "workspace_steps": steps,
        "run_step": run_step_fn,
    })()


class TestRunFlowWithProgress:
    def test_success_summary_format(self, tmp_path):
        from chipcompiler.data import StateEnum
        from chipcompiler.cli.progress import run_flow_with_progress

        flow = _make_flow(
            _make_ws(str(tmp_path)),
            [_make_step("Synthesis", "yosys", str(tmp_path / "synth.log"))],
            lambda self, s: StateEnum.Success,
        )

        buf = FakeTTYStderr(True)
        result = run_flow_with_progress(flow, _make_ctx(), None, buf)
        assert result is True
        output = "".join(buf.written)
        assert "✓ synthesis (yosys)" in output
        assert "status=success" not in output

    def test_stops_on_failure(self):
        from chipcompiler.data import StateEnum
        from chipcompiler.cli.progress import run_flow_with_progress

        call_count = [0]

        def fake_run_step(self, s):
            call_count[0] += 1
            if s.name == "Synthesis":
                return StateEnum.Success
            return StateEnum.Imcomplete

        flow = _make_flow(
            _make_ws(),
            [_make_step("Synthesis", "yosys"), _make_step("Floorplan", "ecc")],
            fake_run_step,
        )

        buf = FakeTTYStderr(True)
        result = run_flow_with_progress(flow, _make_ctx(), None, buf)
        assert result is False
        assert call_count[0] == 2

    def test_summary_includes_inspect_detail_line(self):
        from chipcompiler.data import StateEnum
        from chipcompiler.cli.progress import run_flow_with_progress

        flow = _make_flow(
            _make_ws(),
            [_make_step("Synthesis", "yosys", "/tmp/synth.log")],
            lambda self, s: StateEnum.Success,
        )

        buf = FakeTTYStderr(True)
        run_flow_with_progress(flow, _make_ctx(), "myproject", buf)
        plain = _strip_ansi("".join(buf.written))
        assert "  inspect: ecc log synthesis --errors --project myproject\n" in plain

    def test_summary_includes_log_detail_line(self, tmp_path):
        from chipcompiler.data import StateEnum
        from chipcompiler.cli.progress import run_flow_with_progress

        log_file = tmp_path / "synth.log"
        log_file.write_text("content\n")

        flow = _make_flow(
            _make_ws(str(tmp_path)),
            [_make_step("Synthesis", "yosys", str(log_file))],
            lambda self, s: StateEnum.Success,
        )

        buf = FakeTTYStderr(True)
        run_flow_with_progress(flow, _make_ctx(), None, buf)
        output = "".join(buf.written)
        assert "  log:" in output

    def test_step_headers_emitted(self):
        from chipcompiler.data import StateEnum
        from chipcompiler.cli.progress import run_flow_with_progress

        flow = _make_flow(
            _make_ws(),
            [
                _make_step("Synthesis", "yosys"),
                _make_step("Floorplan", "ecc"),
            ],
            lambda self, s: StateEnum.Success,
        )

        buf = FakeTTYStderr(True)
        result = run_flow_with_progress(flow, _make_ctx(), None, buf)
        assert result is True
        plain = _strip_ansi("".join(buf.written))
        assert "> synthesis (yosys)\n" in plain
        assert "> floorplan (ecc)\n" in plain

    def test_run_header_emitted(self, tmp_path):
        from chipcompiler.data import StateEnum
        from chipcompiler.cli.progress import run_flow_with_progress

        flow = _make_flow(
            _make_ws(str(tmp_path)),
            [_make_step("Synthesis", "yosys")],
            lambda self, s: StateEnum.Success,
        )

        buf = FakeTTYStderr(True)
        run_flow_with_progress(flow, _make_ctx(), None, buf)
        output = "".join(buf.written)
        assert "[run]" in output
        assert "workspace=" in output

    def test_block_separator_between_steps(self):
        from chipcompiler.data import StateEnum
        from chipcompiler.cli.progress import run_flow_with_progress

        flow = _make_flow(
            _make_ws(),
            [
                _make_step("Synthesis", "yosys"),
                _make_step("Floorplan", "ecc"),
            ],
            lambda self, s: StateEnum.Success,
        )

        buf = FakeTTYStderr(True)
        result = run_flow_with_progress(flow, _make_ctx(), None, buf)
        assert result is True
        output = "".join(buf.written)
        synth_summary = output.find("✓ synthesis")
        fp_header = output.find("> floorplan")
        between = output[synth_summary:fp_header]
        assert "\n\n" in between

    def test_failure_summary_includes_status(self):
        from chipcompiler.data import StateEnum
        from chipcompiler.cli.progress import run_flow_with_progress

        def fake_run_step(self, s):
            if s.name == "Synthesis":
                return StateEnum.Success
            return StateEnum.Imcomplete

        flow = _make_flow(
            _make_ws(),
            [_make_step("Synthesis", "yosys"), _make_step("Floorplan", "ecc")],
            fake_run_step,
        )

        buf = FakeTTYStderr(True)
        result = run_flow_with_progress(flow, _make_ctx(), None, buf)
        assert result is False
        plain = _strip_ansi("".join(buf.written))
        assert "✗ floorplan (ecc)" in plain
        assert "incomplete" in plain

    def test_transient_line_shows_log_content(self, tmp_path):
        from chipcompiler.data import StateEnum
        from chipcompiler.cli.progress import run_flow_with_progress

        log_file = tmp_path / "synth.log"

        def fake_run_step(self, s):
            log_file.write_text("Synthesizing module top\n")
            time.sleep(1.0)
            return StateEnum.Success

        flow = _make_flow(
            _make_ws(str(tmp_path)),
            [_make_step("Synthesis", "yosys", str(log_file))],
            fake_run_step,
        )

        buf = FakeTTYStderr(True)
        result = run_flow_with_progress(flow, _make_ctx(), None, buf)
        assert result is True
        plain = _strip_ansi("".join(buf.written))
        assert "Synthesizing module top" in plain

        log_pos = plain.find("Synthesizing module top")
        summary_pos = plain.find("✓ synthesis")
        assert log_pos >= 0
        assert summary_pos >= 0
        assert log_pos < summary_pos

    def test_transient_shows_waiting_when_no_log(self):
        from chipcompiler.data import StateEnum
        from chipcompiler.cli.progress import run_flow_with_progress

        def fake_run_step(self, s):
            time.sleep(1.0)
            return StateEnum.Success

        flow = _make_flow(
            _make_ws(),
            [_make_step("Synthesis", "yosys", "/tmp/nonexistent_synth.log")],
            fake_run_step,
        )

        buf = FakeTTYStderr(True)
        result = run_flow_with_progress(flow, _make_ctx(), None, buf)
        assert result is True
        plain = _strip_ansi("".join(buf.written))
        assert "  log: waiting for log..." in plain

    def test_log_section_markers_emitted(self, tmp_path):
        from chipcompiler.data import StateEnum
        from chipcompiler.cli.progress import run_flow_with_progress

        sections = []
        flow = _make_flow(
            _make_ws(str(tmp_path), log_section_fn=lambda self, msg: sections.append(msg)),
            [_make_step("Synthesis", "yosys")],
            lambda self, s: StateEnum.Success,
        )

        buf = FakeTTYStderr(True)
        run_flow_with_progress(flow, _make_ctx(), None, buf)

        assert "yosys - begin step - Synthesis" in sections
        assert "yosys - end step - Synthesis" in sections
        assert sections.index("yosys - begin step - Synthesis") < sections.index("yosys - end step - Synthesis")

    def test_log_section_markers_around_run_step(self, tmp_path):
        from chipcompiler.data import StateEnum
        from chipcompiler.cli.progress import run_flow_with_progress

        call_order = []

        def fake_run_step(self, s):
            call_order.append(("run_step", s.name))
            return StateEnum.Success

        flow = _make_flow(
            _make_ws(str(tmp_path), log_section_fn=lambda self, msg: call_order.append(("section", msg))),
            [_make_step("Floorplan", "ecc")],
            fake_run_step,
        )

        buf = FakeTTYStderr(True)
        run_flow_with_progress(flow, _make_ctx(), None, buf)

        begin_idx = call_order.index(("section", "ecc - begin step - Floorplan"))
        run_idx = call_order.index(("run_step", "Floorplan"))
        end_idx = call_order.index(("section", "ecc - end step - Floorplan"))
        assert begin_idx < run_idx < end_idx

    def test_monitor_cleanup_on_run_step_exception(self, tmp_path):
        from chipcompiler.cli.progress import run_flow_with_progress

        def raising_run_step(self, s):
            raise RuntimeError("tool crashed")

        flow = _make_flow(
            _make_ws(str(tmp_path)),
            [_make_step("Synthesis", "yosys")],
            raising_run_step,
        )

        buf = FakeTTYStderr(True)
        with pytest.raises(RuntimeError, match="tool crashed"):
            run_flow_with_progress(flow, _make_ctx(), None, buf)

        output = "".join(buf.written)
        assert "\r\x1b[K" in output

    def test_color_enabled_for_tty_text(self, monkeypatch):
        from chipcompiler.data import StateEnum
        from chipcompiler.cli.progress import run_flow_with_progress

        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.setenv("TERM", "xterm-256color")

        flow = _make_flow(
            _make_ws(),
            [_make_step("Synthesis", "yosys")],
            lambda self, s: StateEnum.Success,
        )

        buf = FakeTTYStderr(True)
        run_flow_with_progress(flow, _make_ctx(), None, buf)
        output = "".join(buf.written)
        assert "\x1b[36m" in output  # cyan for step header

    def test_color_disabled_for_non_tty(self):
        from chipcompiler.data import StateEnum
        from chipcompiler.cli.progress import run_flow_with_progress

        flow = _make_flow(
            _make_ws(),
            [_make_step("Synthesis", "yosys")],
            lambda self, s: StateEnum.Success,
        )

        buf = FakeTTYStderr(False)
        run_flow_with_progress(flow, _make_ctx(), None, buf)
        output = "".join(buf.written)
        for code in (_BOLD, _CYAN, _GREEN, _RED, _DIM):
            assert code not in output
