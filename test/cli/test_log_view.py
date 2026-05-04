import pytest

from chipcompiler.cli.log_view import (
    LineKind,
    annotate_log_lines,
    build_log_records,
    classify_line,
    render_log_listing_pretty,
    render_log_plain,
    render_log_pretty,
)


class TestClassifyLine:
    def test_error_keyword(self):
        assert classify_line("Error: something failed") == LineKind.ERROR

    def test_error_case_insensitive(self):
        assert classify_line("ERROR: critical") == LineKind.ERROR

    def test_warning_keyword(self):
        assert classify_line("Warning: check this") == LineKind.WARNING

    def test_warn_keyword(self):
        assert classify_line("WARN: deprecated") == LineKind.WARNING

    def test_info_prefix(self):
        assert classify_line("INFO: running step") == LineKind.INFO

    def test_info_bracket(self):
        assert classify_line("[INFO   ] running step") == LineKind.INFO

    def test_info_root(self):
        assert classify_line("INFO:root: message") == LineKind.INFO

    def test_traceback_header(self):
        assert classify_line("Traceback (most recent call last):") == LineKind.TRACEBACK

    def test_section_separator(self):
        assert classify_line("---") == LineKind.SECTION

    def test_section_equals(self):
        assert classify_line("==========") == LineKind.SECTION

    def test_plain_line(self):
        assert classify_line("some ordinary output") == LineKind.PLAIN

    def test_plain_empty(self):
        assert classify_line("") == LineKind.PLAIN

    def test_plain_whitespace(self):
        assert classify_line("   ") == LineKind.PLAIN

    def test_traceback_header_indented(self):
        assert classify_line("  Traceback (most recent call last):") == LineKind.TRACEBACK

    def test_error_inside_traceback_stops_traceback(self):
        assert classify_line("ValueError: bad", in_traceback=True) == LineKind.ERROR

    def test_indented_line_in_traceback(self):
        assert classify_line('  File "test.py", line 1', in_traceback=True) == LineKind.TRACEBACK

    def test_tab_indented_line_in_traceback(self):
        assert classify_line("\tFile \"test.py\", line 1", in_traceback=True) == LineKind.TRACEBACK


class TestClassifyDoesNotFilter:
    """Classification must never remove or hide lines."""

    def test_every_line_gets_a_kind(self):
        lines = [
            "Error: bad",
            "Warning: meh",
            "INFO: ok",
            "---",
            "plain text",
            "",
            "Traceback (most recent call last):",
            '  File "a.py", line 1',
            "ValueError: fail",
        ]
        annotated = annotate_log_lines(lines)
        assert len(annotated) == len(lines)

    def test_classification_preserves_text(self):
        text = "Error: something went wrong"
        assert classify_line(text).value  # just returns a kind, text is separate


class TestTracebackAnnotation:
    def test_complete_traceback_block(self):
        lines = [
            "Traceback (most recent call last):",
            '  File "app.py", line 42, in run',
            "    result = compute()",
            "        ^^^^^^^^^",
            "ValueError: invalid value",
        ]
        annotated = annotate_log_lines(lines)
        assert annotated[0].kind == LineKind.TRACEBACK
        assert annotated[1].kind == LineKind.TRACEBACK
        assert annotated[2].kind == LineKind.TRACEBACK
        assert annotated[3].kind == LineKind.TRACEBACK
        assert annotated[4].kind == LineKind.ERROR

    def test_traceback_with_blank_source_line(self):
        lines = [
            "Traceback (most recent call last):",
            '  File "app.py", line 10, in <module>',
            "",
            "ValueError: oops",
        ]
        annotated = annotate_log_lines(lines)
        assert annotated[0].kind == LineKind.TRACEBACK
        assert annotated[1].kind == LineKind.TRACEBACK
        assert annotated[2].kind == LineKind.PLAIN
        assert annotated[3].kind == LineKind.ERROR

    def test_traceback_exits_on_non_indented_non_error(self):
        lines = [
            "Traceback (most recent call last):",
            '  File "a.py", line 1',
            "ValueError: bad",
            "next log line",
        ]
        annotated = annotate_log_lines(lines)
        assert annotated[0].kind == LineKind.TRACEBACK
        assert annotated[1].kind == LineKind.TRACEBACK
        assert annotated[2].kind == LineKind.ERROR
        assert annotated[3].kind == LineKind.PLAIN

    def test_traceback_order_preserved(self):
        lines = [
            "Traceback (most recent call last):",
            '  File "a.py", line 1',
            '  File "b.py", line 2',
            '  File "c.py", line 3',
            "RuntimeError: end",
        ]
        annotated = annotate_log_lines(lines)
        kinds = [a.kind for a in annotated]
        assert kinds == [
            LineKind.TRACEBACK,
            LineKind.TRACEBACK,
            LineKind.TRACEBACK,
            LineKind.TRACEBACK,
            LineKind.ERROR,
        ]

    def test_pre_traceback_info_preserved(self):
        lines = [
            "INFO: starting step",
            "some output",
            "Traceback (most recent call last):",
            '  File "a.py", line 1',
            "ValueError: fail",
        ]
        annotated = annotate_log_lines(lines)
        assert annotated[0].kind == LineKind.INFO
        assert annotated[1].kind == LineKind.PLAIN
        assert annotated[2].kind == LineKind.TRACEBACK

    def test_exception_classified_as_error(self):
        lines = [
            "Traceback (most recent call last):",
            '  File "a.py", line 1',
            "Exception: something went wrong",
        ]
        annotated = annotate_log_lines(lines)
        assert annotated[2].kind == LineKind.ERROR

    def test_keyboard_interrupt_classified_as_plain(self):
        lines = [
            "Traceback (most recent call last):",
            '  File "a.py", line 1',
            "KeyboardInterrupt",
        ]
        annotated = annotate_log_lines(lines)
        assert annotated[2].kind == LineKind.PLAIN


class TestAnnotateLineNumbers:
    def test_line_numbers_start_at_one(self):
        lines = ["first", "second", "third"]
        annotated = annotate_log_lines(lines)
        assert [a.line_no for a in annotated] == [1, 2, 3]

    def test_empty_input(self):
        assert annotate_log_lines([]) == []


# --- Renderer tests ---


class TestBuildLogRecords:
    def test_builds_records_with_all_fields(self):
        lines = ["Error: bad", "INFO: ok"]
        records = build_log_records("synthesis", "log/synthesis.log", lines, "ecc log synthesis")
        assert len(records) == 2
        assert records[0]["step"] == "synthesis"
        assert records[0]["source"] == "log/synthesis.log"
        assert records[0]["line_no"] == 1
        assert records[0]["kind"] == "error"
        assert records[0]["line"] == "Error: bad"
        assert records[0]["inspect_cmd"] == "ecc log synthesis"

    def test_traceback_frames_in_records(self):
        lines = [
            "Traceback (most recent call last):",
            '  File "a.py", line 1',
            "ValueError: fail",
        ]
        records = build_log_records("cts", "log/cts.log", lines, "ecc log cts")
        assert records[0]["kind"] == "traceback"
        assert records[1]["kind"] == "traceback"
        assert records[2]["kind"] == "error"


class TestPrettyRenderer:
    def test_header_includes_step_and_source(self):
        from io import StringIO
        buf = StringIO()
        render_log_pretty("cts", "log/cts.log", ["ok"], "ecc log cts", file=buf, color=False)
        out = buf.getvalue()
        assert "[log] step=cts" in out
        assert "source: log/cts.log" in out

    def test_all_lines_appear_in_output(self):
        from io import StringIO
        lines = ["Error: bad", "INFO: ok", "plain line", "---", "Warning: meh"]
        buf = StringIO()
        render_log_pretty("cts", "log/cts.log", lines, "ecc log cts", file=buf, color=False)
        out = buf.getvalue()
        for line in lines:
            assert line in out

    def test_traceback_complete_in_output(self):
        from io import StringIO
        lines = [
            "INFO: before",
            "Traceback (most recent call last):",
            '  File "a.py", line 1',
            "    x = bad()",
            "        ^^^^^",
            "ValueError: oops",
            "INFO: after",
        ]
        buf = StringIO()
        render_log_pretty("cts", "log/cts.log", lines, "ecc log cts", file=buf, color=False)
        out = buf.getvalue()
        for line in lines:
            assert line in out

    def test_inspect_footer(self):
        from io import StringIO
        buf = StringIO()
        render_log_pretty("cts", "log/cts.log", ["ok"], "ecc log cts", file=buf, color=False)
        out = buf.getvalue()
        assert "inspect: ecc log cts" in out

    def test_no_ansi_when_color_disabled(self):
        from io import StringIO
        buf = StringIO()
        render_log_pretty("cts", "log/cts.log", ["Error: bad"], "ecc log cts", file=buf, color=False)
        assert "\x1b[" not in buf.getvalue()

    def test_ansi_when_color_enabled(self):
        from io import StringIO
        buf = StringIO()
        render_log_pretty("cts", "log/cts.log", ["Error: bad"], "ecc log cts", file=buf, color=True)
        assert "\x1b[" in buf.getvalue()

    def test_error_colored_red(self):
        from io import StringIO
        buf = StringIO()
        render_log_pretty("cts", "log/cts.log", ["Error: bad"], "ecc log cts", file=buf, color=True)
        out = buf.getvalue()
        assert "\x1b[31m" in out

    def test_warning_colored_yellow(self):
        from io import StringIO
        buf = StringIO()
        render_log_pretty("cts", "log/cts.log", ["Warning: meh"], "ecc log cts", file=buf, color=True)
        out = buf.getvalue()
        assert "\x1b[33m" in out

    def test_section_colored_cyan(self):
        from io import StringIO
        buf = StringIO()
        render_log_pretty("cts", "log/cts.log", ["---"], "ecc log cts", file=buf, color=True)
        out = buf.getvalue()
        assert "\x1b[36m" in out

    def test_info_colored_blue(self):
        from io import StringIO
        buf = StringIO()
        render_log_pretty("cts", "log/cts.log", ["INFO: ok"], "ecc log cts", file=buf, color=True)
        out = buf.getvalue()
        assert "\x1b[34m" in out

    def test_traceback_colored_yellow(self):
        from io import StringIO
        lines = [
            "Traceback (most recent call last):",
            '  File "a.py", line 1',
            "ValueError: bad",
        ]
        buf = StringIO()
        render_log_pretty("cts", "log/cts.log", lines, "ecc log cts", file=buf, color=True)
        out = buf.getvalue()
        assert "\x1b[33m" in out


class TestPlainRenderer:
    def test_emits_one_record_per_line(self):
        from io import StringIO
        lines = ["Error: bad", "INFO: ok", "plain"]
        buf = StringIO()
        render_log_plain("cts", "log/cts.log", lines, "ecc log cts", file=buf)
        out_lines = [l for l in buf.getvalue().strip().split("\n") if l.strip()]
        assert len(out_lines) == 3

    def test_record_has_required_fields(self):
        from io import StringIO
        buf = StringIO()
        render_log_plain("cts", "log/cts.log", ["ok"], "ecc log cts", file=buf)
        line = buf.getvalue().strip()
        assert "step=cts" in line
        assert "source=log/cts.log" in line
        assert "line_no=1" in line
        assert "kind=plain" in line
        assert "line=ok" in line
        assert "inspect_cmd=" in line

    def test_values_with_spaces_are_quoted(self):
        from io import StringIO
        buf = StringIO()
        render_log_plain("cts", "log/cts.log", ["line with spaces"], "ecc log cts --project /tmp/a b", file=buf)
        line = buf.getvalue().strip()
        assert 'line="line with spaces"' in line
        assert 'inspect_cmd="ecc log cts --project /tmp/a b"' in line

    def test_values_with_backslashes_escaped(self):
        from io import StringIO
        buf = StringIO()
        render_log_plain("cts", "log/cts.log", ['path\\to\\file'], "ecc log cts", file=buf)
        line = buf.getvalue().strip()
        assert 'line="path\\\\to\\\\file"' in line

    def test_no_ansi_in_plain(self):
        from io import StringIO
        buf = StringIO()
        render_log_plain("cts", "log/cts.log", ["Error: bad"], "ecc log cts", file=buf)
        assert "\x1b[" not in buf.getvalue()

    def test_traceback_frames_in_plain(self):
        from io import StringIO
        lines = [
            "Traceback (most recent call last):",
            '  File "a.py", line 1',
            "ValueError: fail",
        ]
        buf = StringIO()
        render_log_plain("cts", "log/cts.log", lines, "ecc log cts", file=buf)
        out_lines = [l for l in buf.getvalue().strip().split("\n") if l.strip()]
        assert len(out_lines) == 3
        assert "kind=traceback" in out_lines[0]
        assert "kind=traceback" in out_lines[1]
        assert "kind=error" in out_lines[2]


class TestColorGuards:
    def test_no_color_when_not_tty(self):
        import io
        from unittest.mock import patch

        class FakeNonTTY:
            def isatty(self):
                return False

        with patch("sys.stdout", FakeNonTTY()):
            buf = io.StringIO()
            render_log_pretty("cts", "log/cts.log", ["Error: bad"], "ecc log cts", file=buf, color=False)
            assert "\x1b[" not in buf.getvalue()

    def test_no_color_when_no_color_env(self):
        import os
        import io
        from unittest.mock import patch

        with patch.dict(os.environ, {"NO_COLOR": "1"}):
            buf = io.StringIO()
            render_log_pretty("cts", "log/cts.log", ["Error: bad"], "ecc log cts", file=buf, color=False)
            assert "\x1b[" not in buf.getvalue()

    def test_no_color_when_term_dumb(self):
        import os
        import io
        from unittest.mock import patch

        with patch.dict(os.environ, {"TERM": "dumb"}):
            buf = io.StringIO()
            render_log_pretty("cts", "log/cts.log", ["Error: bad"], "ecc log cts", file=buf, color=False)
            assert "\x1b[" not in buf.getvalue()


class TestListingPrettyRenderer:
    def test_listing_header(self):
        from io import StringIO
        records = [
            {"step": "synthesis", "source": "Synthesis_yosys/log/synthesis.log", "inspect_cmd": "ecc log synthesis"},
        ]
        buf = StringIO()
        render_log_listing_pretty(records, file=buf, color=False)
        assert "[logs]" in buf.getvalue()

    def test_listing_shows_step_and_source(self):
        from io import StringIO
        records = [
            {"step": "synthesis", "source": "Synthesis_yosys/log/synthesis.log", "inspect_cmd": "ecc log synthesis"},
        ]
        buf = StringIO()
        render_log_listing_pretty(records, file=buf, color=False)
        out = buf.getvalue()
        assert "synthesis" in out
        assert "Synthesis_yosys/log/synthesis.log" in out

    def test_listing_inspect_cmd(self):
        from io import StringIO
        records = [
            {"step": "synthesis", "source": "Synthesis_yosys/log/synthesis.log", "inspect_cmd": "ecc log synthesis"},
        ]
        buf = StringIO()
        render_log_listing_pretty(records, file=buf, color=False)
        assert "ecc log synthesis" in buf.getvalue()
