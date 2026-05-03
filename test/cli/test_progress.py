import io
import os
import sys

import pytest

from chipcompiler.cli.progress import (
    RunProgressRenderer,
    latest_log_line,
    sanitize_log_line,
    should_enable_run_progress,
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
    def test_running_writes_carriage_return_clear(self):
        buf = FakeTTYStderr(True)
        r = RunProgressRenderer(buf, width_fn=lambda: 80)
        r.running("working...")
        output = "".join(buf.written)
        assert output.startswith("\r\x1b[K")
        assert "working..." in output

    def test_summary_clears_transient_first(self):
        buf = FakeTTYStderr(True)
        r = RunProgressRenderer(buf, width_fn=lambda: 80)
        r.running("transient")
        r.summary("done")
        output = "".join(buf.written)
        # After transient, clear should be written before summary
        assert "\r\x1b[K" in output
        assert "done\n" in output

    def test_clear_noop_without_transient(self):
        buf = FakeTTYStderr(True)
        r = RunProgressRenderer(buf, width_fn=lambda: 80)
        r.clear()
        assert buf.written == []

    def test_truncates_long_running_text(self):
        buf = FakeTTYStderr(True)
        r = RunProgressRenderer(buf, width_fn=lambda: 10)
        r.running("x" * 100)
        output = "".join(buf.written)
        # \r\x1b[K + truncated text (10 chars max)
        display = output.replace("\r\x1b[K", "")
        assert len(display) <= 10


# -- run_flow_with_progress --


class TestRunFlowWithProgress:
    def test_mirrors_run_steps_success(self, tmp_path):
        from chipcompiler.data import StateEnum
        from chipcompiler.cli.progress import run_flow_with_progress

        ws = type("WS", (), {
            "home": type("Home", (), {"reset": lambda self: None})(),
            "logger": type("L", (), {"info": lambda *a, **k: None, "log_section": lambda *a, **k: None, "log_separator": lambda *a, **k: None})(),
            "flow": type("F", (), {"data": {"steps": []}, "path": ""})(),
            "directory": str(tmp_path),
        })()

        ws_step = type("WSS", (), {
            "name": "Synthesis",
            "tool": "yosys",
            "log": {"file": str(tmp_path / "synth.log")},
        })()

        flow = type("EF", (), {
            "workspace": ws,
            "workspace_steps": [ws_step],
            "run_step": lambda self, s: StateEnum.Success,
        })()

        buf = FakeTTYStderr(True)
        result = run_flow_with_progress(flow, _make_ctx(), None, buf)
        assert result is True
        output = "".join(buf.written)
        assert "step=synthesis" in output
        assert "status=success" in output

    def test_stops_on_failure(self):
        from chipcompiler.data import StateEnum
        from chipcompiler.cli.progress import run_flow_with_progress

        ws = type("WS", (), {
            "home": type("Home", (), {"reset": lambda self: None})(),
            "logger": type("L", (), {"info": lambda *a, **k: None, "log_section": lambda *a, **k: None, "log_separator": lambda *a, **k: None})(),
            "flow": type("F", (), {"data": {"steps": []}, "path": ""})(),
            "directory": "/tmp",
        })()

        ws_step1 = type("WSS", (), {
            "name": "Synthesis",
            "tool": "yosys",
            "log": {"file": ""},
        })()
        ws_step2 = type("WSS", (), {
            "name": "Floorplan",
            "tool": "ecc",
            "log": {"file": ""},
        })()

        call_count = [0]

        def fake_run_step(self, s):
            call_count[0] += 1
            if s.name == "Synthesis":
                return StateEnum.Success
            return StateEnum.Imcomplete

        flow = type("EF", (), {
            "workspace": ws,
            "workspace_steps": [ws_step1, ws_step2],
            "run_step": fake_run_step,
        })()

        buf = FakeTTYStderr(True)
        result = run_flow_with_progress(flow, _make_ctx(), None, buf)
        assert result is False
        assert call_count[0] == 2  # Floorplan ran but didn't continue beyond it

    def test_summary_includes_inspect(self):
        from chipcompiler.data import StateEnum
        from chipcompiler.cli.progress import run_flow_with_progress

        ws = type("WS", (), {
            "home": type("Home", (), {"reset": lambda self: None})(),
            "logger": type("L", (), {"info": lambda *a, **k: None, "log_section": lambda *a, **k: None, "log_separator": lambda *a, **k: None})(),
            "flow": type("F", (), {"data": {"steps": []}, "path": ""})(),
            "directory": "/tmp",
        })()

        ws_step = type("WSS", (), {
            "name": "Synthesis",
            "tool": "yosys",
            "log": {"file": "/tmp/synth.log"},
        })()

        flow = type("EF", (), {
            "workspace": ws,
            "workspace_steps": [ws_step],
            "run_step": lambda self, s: StateEnum.Success,
        })()

        buf = FakeTTYStderr(True)
        run_flow_with_progress(flow, _make_ctx(), "myproject", buf)
        output = "".join(buf.written)
        assert "ecc log synthesis --errors" in output

    def test_summary_includes_log_path(self, tmp_path):
        from chipcompiler.data import StateEnum
        from chipcompiler.cli.progress import run_flow_with_progress

        log_file = tmp_path / "synth.log"
        log_file.write_text("content\n")

        ws = type("WS", (), {
            "home": type("Home", (), {"reset": lambda self: None})(),
            "logger": type("L", (), {"info": lambda *a, **k: None, "log_section": lambda *a, **k: None, "log_separator": lambda *a, **k: None})(),
            "flow": type("F", (), {"data": {"steps": []}, "path": ""})(),
            "directory": str(tmp_path),
        })()

        ws_step = type("WSS", (), {
            "name": "Synthesis",
            "tool": "yosys",
            "log": {"file": str(log_file)},
        })()

        flow = type("EF", (), {
            "workspace": ws,
            "workspace_steps": [ws_step],
            "run_step": lambda self, s: StateEnum.Success,
        })()

        buf = FakeTTYStderr(True)
        run_flow_with_progress(flow, _make_ctx(), None, buf)
        output = "".join(buf.written)
        assert "log=" in output

    def test_transient_line_shows_log_content(self, tmp_path):
        import time
        from chipcompiler.data import StateEnum
        from chipcompiler.cli.progress import run_flow_with_progress

        log_file = tmp_path / "synth.log"

        def fake_run_step(self, s):
            log_file.write_text("Synthesizing module top\n")
            time.sleep(1.0)
            return StateEnum.Success

        ws = type("WS", (), {
            "home": type("Home", (), {"reset": lambda self: None})(),
            "logger": type("L", (), {"info": lambda *a, **k: None, "log_section": lambda *a, **k: None, "log_separator": lambda *a, **k: None})(),
            "flow": type("F", (), {"data": {"steps": []}, "path": ""})(),
            "directory": str(tmp_path),
        })()

        ws_step = type("WSS", (), {
            "name": "Synthesis",
            "tool": "yosys",
            "log": {"file": str(log_file)},
        })()

        flow = type("EF", (), {
            "workspace": ws,
            "workspace_steps": [ws_step],
            "run_step": fake_run_step,
        })()

        buf = FakeTTYStderr(True)
        result = run_flow_with_progress(flow, _make_ctx(), None, buf)
        assert result is True

        output = "".join(buf.written)
        assert "Synthesizing module top" in output

        # Transient running line uses the contract prefix and appears before summary
        running_pos = output.find("running step=synthesis tool=yosys")
        summary_pos = output.find("step=synthesis")
        assert running_pos >= 0, "Missing transient running line with contract prefix"
        assert summary_pos >= 0, "Missing summary line"
        assert running_pos < summary_pos, "Transient line should appear before summary"

    def test_transient_shows_waiting_when_no_log(self):
        import time
        from chipcompiler.data import StateEnum
        from chipcompiler.cli.progress import run_flow_with_progress

        def fake_run_step(self, s):
            time.sleep(1.0)
            return StateEnum.Success

        ws = type("WS", (), {
            "home": type("Home", (), {"reset": lambda self: None})(),
            "logger": type("L", (), {"info": lambda *a, **k: None, "log_section": lambda *a, **k: None, "log_separator": lambda *a, **k: None})(),
            "flow": type("F", (), {"data": {"steps": []}, "path": ""})(),
            "directory": "/tmp",
        })()

        ws_step = type("WSS", (), {
            "name": "Synthesis",
            "tool": "yosys",
            "log": {"file": "/tmp/nonexistent_synth.log"},
        })()

        flow = type("EF", (), {
            "workspace": ws,
            "workspace_steps": [ws_step],
            "run_step": fake_run_step,
        })()

        buf = FakeTTYStderr(True)
        result = run_flow_with_progress(flow, _make_ctx(), None, buf)
        assert result is True

        output = "".join(buf.written)
        assert "running step=synthesis tool=yosys | waiting for log..." in output

    def test_log_section_markers_emitted(self, tmp_path):
        from chipcompiler.data import StateEnum
        from chipcompiler.cli.progress import run_flow_with_progress

        sections = []

        ws = type("WS", (), {
            "home": type("Home", (), {"reset": lambda self: None})(),
            "logger": type("L", (), {
                "info": lambda *a, **k: None,
                "log_section": lambda self, msg: sections.append(msg),
                "log_separator": lambda *a, **k: None,
            })(),
            "flow": type("F", (), {"data": {"steps": []}, "path": ""})(),
            "directory": str(tmp_path),
        })()

        ws_step = type("WSS", (), {
            "name": "Synthesis",
            "tool": "yosys",
            "log": {"file": ""},
        })()

        flow = type("EF", (), {
            "workspace": ws,
            "workspace_steps": [ws_step],
            "run_step": lambda self, s: StateEnum.Success,
        })()

        buf = FakeTTYStderr(True)
        run_flow_with_progress(flow, _make_ctx(), None, buf)

        assert "yosys - begin step - Synthesis" in sections
        assert "yosys - end step - Synthesis" in sections
        begin_idx = sections.index("yosys - begin step - Synthesis")
        end_idx = sections.index("yosys - end step - Synthesis")
        assert begin_idx < end_idx

    def test_log_section_markers_around_run_step(self, tmp_path):
        from chipcompiler.data import StateEnum
        from chipcompiler.cli.progress import run_flow_with_progress

        call_order = []

        ws = type("WS", (), {
            "home": type("Home", (), {"reset": lambda self: None})(),
            "logger": type("L", (), {
                "info": lambda *a, **k: None,
                "log_section": lambda self, msg: call_order.append(("section", msg)),
                "log_separator": lambda *a, **k: None,
            })(),
            "flow": type("F", (), {"data": {"steps": []}, "path": ""})(),
            "directory": str(tmp_path),
        })()

        ws_step = type("WSS", (), {
            "name": "Floorplan",
            "tool": "ecc",
            "log": {"file": ""},
        })()

        def fake_run_step(self, s):
            call_order.append(("run_step", s.name))
            return StateEnum.Success

        flow = type("EF", (), {
            "workspace": ws,
            "workspace_steps": [ws_step],
            "run_step": fake_run_step,
        })()

        buf = FakeTTYStderr(True)
        run_flow_with_progress(flow, _make_ctx(), None, buf)

        begin_idx = call_order.index(("section", "ecc - begin step - Floorplan"))
        run_idx = call_order.index(("run_step", "Floorplan"))
        end_idx = call_order.index(("section", "ecc - end step - Floorplan"))
        assert begin_idx < run_idx < end_idx

    def test_monitor_cleanup_on_run_step_exception(self, tmp_path):
        from chipcompiler.cli.progress import run_flow_with_progress

        def fake_run_step(self, s):
            raise RuntimeError("tool crashed")

        ws = type("WS", (), {
            "home": type("Home", (), {"reset": lambda self: None})(),
            "logger": type("L", (), {"info": lambda *a, **k: None, "log_section": lambda *a, **k: None, "log_separator": lambda *a, **k: None})(),
            "flow": type("F", (), {"data": {"steps": []}, "path": ""})(),
            "directory": str(tmp_path),
        })()

        ws_step = type("WSS", (), {
            "name": "Synthesis",
            "tool": "yosys",
            "log": {"file": ""},
        })()

        flow = type("EF", (), {
            "workspace": ws,
            "workspace_steps": [ws_step],
            "run_step": fake_run_step,
        })()

        buf = FakeTTYStderr(True)
        with pytest.raises(RuntimeError, match="tool crashed"):
            run_flow_with_progress(flow, _make_ctx(), None, buf)

        # The transient line must be cleared even after an exception
        output = "".join(buf.written)
        assert "\r\x1b[K" in output
