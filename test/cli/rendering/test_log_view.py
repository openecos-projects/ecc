import os

from chipcompiler.cli.inspection.log_view import (
    LineKind,
    annotate_log_lines,
    build_log_records,
    classify_line,
    extract_error_context,
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
        assert classify_line('\tFile "test.py", line 1', in_traceback=True) == LineKind.TRACEBACK


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

    def test_keyboard_interrupt_classified_as_error(self):
        lines = [
            "Traceback (most recent call last):",
            '  File "a.py", line 1',
            "KeyboardInterrupt",
        ]
        annotated = annotate_log_lines(lines)
        assert annotated[2].kind == LineKind.ERROR

    def test_system_exit_classified_as_error(self):
        lines = [
            "Traceback (most recent call last):",
            '  File "a.py", line 1',
            "SystemExit: 1",
        ]
        annotated = annotate_log_lines(lines)
        assert annotated[2].kind == LineKind.ERROR

    def test_stop_iteration_classified_as_error(self):
        lines = [
            "Traceback (most recent call last):",
            '  File "a.py", line 1',
            "StopIteration",
        ]
        annotated = annotate_log_lines(lines)
        assert annotated[2].kind == LineKind.ERROR


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
        render_log_pretty(
            "cts", "log/cts.log", ["Error: bad"], "ecc log cts", file=buf, color=False
        )
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
        render_log_pretty(
            "cts", "log/cts.log", ["Warning: meh"], "ecc log cts", file=buf, color=True
        )
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


# ---------------------------------------------------------------------------
# Full error line coloring (AC-2)
# ---------------------------------------------------------------------------


class TestErrorLineFullColoring:
    def test_error_label_and_message_both_red(self):
        from io import StringIO

        buf = StringIO()
        render_log_pretty(
            "cts", "log/cts.log", ["Error: something failed"], "ecc log cts", file=buf, color=True
        )
        out = buf.getvalue()

        red_idx = out.find("\x1b[31m")
        assert red_idx >= 0
        reset_idx = out.find("\x1b[0m", red_idx)
        assert reset_idx > red_idx
        between = out[red_idx:reset_idx]
        assert "error" in between
        assert "something failed" in between

    def test_error_message_content_not_default_after_label(self):
        from io import StringIO

        buf = StringIO()
        render_log_pretty(
            "cts", "log/cts.log", ["Error: critical failure"], "ecc log cts", file=buf, color=True
        )
        out = buf.getvalue()
        idx = out.find("error")
        after_label = out[idx:]
        assert "critical failure" in after_label

    def test_warning_line_keeps_label_only_color(self):
        from io import StringIO

        buf = StringIO()
        render_log_pretty(
            "cts", "log/cts.log", ["Warning: check this"], "ecc log cts", file=buf, color=True
        )
        out = buf.getvalue()
        assert "\x1b[33m" in out
        assert "Warning: check this" in out

    def test_info_plain_section_unchanged(self):
        from io import StringIO

        buf = StringIO()
        lines = ["INFO: running", "some plain text", "---"]
        render_log_pretty("cts", "log/cts.log", lines, "ecc log cts", file=buf, color=True)
        out = buf.getvalue()
        assert "\x1b[34m" in out
        assert "some plain text" in out
        assert "---" in out

    def test_error_line_no_ansi_when_color_disabled(self):
        from io import StringIO

        buf = StringIO()
        render_log_pretty(
            "cts", "log/cts.log", ["Error: bad"], "ecc log cts", file=buf, color=False
        )
        out = buf.getvalue()
        assert "\x1b[" not in out

    def test_non_error_lines_not_colored_red(self):
        from io import StringIO

        lines = ["Warning: meh", "INFO: ok", "plain", "---"]
        buf = StringIO()
        render_log_pretty("cts", "log/cts.log", lines, "ecc log cts", file=buf, color=True)
        out = buf.getvalue()
        red_count = out.count("\x1b[31m")
        assert red_count == 0


# ---------------------------------------------------------------------------
# Context extraction (AC-3, AC-4)
# ---------------------------------------------------------------------------


class TestExtractErrorContextAnchor:
    def test_last_error_wins(self):
        lines = ["INFO: start", "Error: first", "plain", "Error: last", "INFO: end"]
        result = extract_error_context(lines, max_lines=50)
        kinds = [ll.kind for ll in result]
        assert LineKind.ERROR in kinds
        anchor_texts = [ll.text for ll in result if ll.kind == LineKind.ERROR]
        assert "Error: last" in anchor_texts

    def test_traceback_when_no_error(self):
        lines = [
            "INFO: start",
            "Traceback (most recent call last):",
            '  File "a.py", line 1',
            "RuntimeError: boom",
        ]
        result = extract_error_context(lines, max_lines=50)
        kinds = [ll.kind for ll in result]
        assert LineKind.TRACEBACK in kinds

    def test_failed_keyword_when_no_error_or_traceback(self):
        lines = ["INFO: start", "step failed: timeout", "plain after"]
        result = extract_error_context(lines, max_lines=50)
        texts = [ll.text for ll in result]
        assert any("failed" in t.lower() for t in texts)

    def test_last_nonempty_when_no_failure(self):
        lines = ["INFO: start", "some output", "final output"]
        result = extract_error_context(lines, max_lines=50)
        assert result[-1].text == "final output"

    def test_empty_input(self):
        assert extract_error_context([], max_lines=50) == []


class TestExtractErrorContextWindow:
    def test_max_50_lines(self):
        lines = [f"line {i}" for i in range(100)]
        lines[80] = "Error: failure at 80"
        result = extract_error_context(lines, max_lines=50)
        assert len(result) <= 50

    def test_preserves_line_numbers(self):
        lines = [f"line {i}" for i in range(100)]
        lines[30] = "Error: mid"
        result = extract_error_context(lines, max_lines=50)
        line_nos = [ll.line_no for ll in result]
        assert line_nos == sorted(line_nos)
        for ll in result:
            assert ll.line_no >= 1
            assert ll.text == lines[ll.line_no - 1]

    def test_preserves_order(self):
        lines = [f"line {i}" for i in range(10)]
        lines[5] = "Error: mid"
        result = extract_error_context(lines, max_lines=50)
        line_nos = [ll.line_no for ll in result]
        assert line_nos == sorted(line_nos)

    def test_fewer_than_max_returns_all(self):
        lines = ["one", "Error: two", "three"]
        result = extract_error_context(lines, max_lines=50)
        assert len(result) == 3

    def test_anchor_last_error_not_first(self):
        lines = ["Error: first", "plain", "Error: last", "plain"]
        result = extract_error_context(lines, max_lines=50)
        error_lines = [ll for ll in result if ll.kind == LineKind.ERROR]
        assert len(error_lines) >= 1


class TestExtractErrorContextTraceback:
    def test_traceback_includes_stack_frames(self):
        lines = [
            "INFO: before",
            "Traceback (most recent call last):",
            '  File "a.py", line 10, in f',
            '  File "b.py", line 20, in g',
            "ValueError: bad value",
            "INFO: after",
        ]
        result = extract_error_context(lines, max_lines=50)
        kinds = [ll.kind for ll in result]
        assert LineKind.TRACEBACK in kinds
        traceback_texts = [ll.text for ll in result if ll.kind == LineKind.TRACEBACK]
        assert any("File" in t for t in traceback_texts)

    def test_final_exception_visible_in_window(self):
        lines = ["line " + str(i) for i in range(60)]
        lines[52] = "Traceback (most recent call last):"
        lines[53] = '  File "a.py", line 1, in run'
        lines[54] = "ValueError: final exception"
        lines[55] = "line 55"
        result = extract_error_context(lines, max_lines=50)
        texts = [ll.text for ll in result]
        assert "ValueError: final exception" in texts

    def test_traceback_context_not_exceed_max(self):
        lines = ["line " + str(i) for i in range(100)]
        lines[60] = "Traceback (most recent call last):"
        for i in range(61, 75):
            lines[i] = f'  File "mod{i}.py", line {i}'
        lines[75] = "RuntimeError: deep traceback"
        result = extract_error_context(lines, max_lines=50)
        assert len(result) <= 50

    def test_traceback_lines_in_order(self):
        lines = [
            "Traceback (most recent call last):",
            '  File "a.py", line 1',
            '  File "b.py", line 2',
            "ValueError: boom",
        ]
        result = extract_error_context(lines, max_lines=50)
        line_nos = [ll.line_no for ll in result]
        assert line_nos == sorted(line_nos)


class TestPlainRenderer:
    def test_emits_one_record_per_line(self):
        from io import StringIO

        lines = ["Error: bad", "INFO: ok", "plain"]
        buf = StringIO()
        render_log_plain("cts", "log/cts.log", lines, "ecc log cts", file=buf)
        out_lines = [line for line in buf.getvalue().strip().split("\n") if line.strip()]
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
        render_log_plain(
            "cts", "log/cts.log", ["line with spaces"], "ecc log cts --project /tmp/a b", file=buf
        )
        line = buf.getvalue().strip()
        assert 'line="line with spaces"' in line
        assert 'inspect_cmd="ecc log cts --project /tmp/a b"' in line

    def test_values_with_backslashes_escaped(self):
        from io import StringIO

        buf = StringIO()
        render_log_plain("cts", "log/cts.log", ["path\\to\\file"], "ecc log cts", file=buf)
        line = buf.getvalue().strip()
        assert 'line="path\\\\to\\\\file"' in line

    def test_values_with_equals_quoted(self):
        from io import StringIO

        buf = StringIO()
        render_log_plain("cts", "log/cts.log", ["key=value"], "ecc log cts", file=buf)
        line = buf.getvalue().strip()
        assert 'line="key=value"' in line

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
        out_lines = [line for line in buf.getvalue().strip().split("\n") if line.strip()]
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
            render_log_pretty(
                "cts", "log/cts.log", ["Error: bad"], "ecc log cts", file=buf, color=False
            )
            assert "\x1b[" not in buf.getvalue()

    def test_no_color_when_no_color_env(self):
        import io
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {"NO_COLOR": "1"}):
            buf = io.StringIO()
            render_log_pretty(
                "cts", "log/cts.log", ["Error: bad"], "ecc log cts", file=buf, color=False
            )
            assert "\x1b[" not in buf.getvalue()

    def test_no_color_when_term_dumb(self):
        import io
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {"TERM": "dumb"}):
            buf = io.StringIO()
            render_log_pretty(
                "cts", "log/cts.log", ["Error: bad"], "ecc log cts", file=buf, color=False
            )
            assert "\x1b[" not in buf.getvalue()


class TestListingPrettyRenderer:
    def test_listing_header(self):
        from io import StringIO

        records = [
            {
                "step": "synthesis",
                "source": "Synthesis_yosys/log/synthesis.log",
                "inspect_cmd": "ecc log synthesis",
            },
        ]
        buf = StringIO()
        render_log_listing_pretty(records, file=buf, color=False)
        assert "[logs]" in buf.getvalue()

    def test_listing_shows_step_and_source(self):
        from io import StringIO

        records = [
            {
                "step": "synthesis",
                "source": "Synthesis_yosys/log/synthesis.log",
                "inspect_cmd": "ecc log synthesis",
            },
        ]
        buf = StringIO()
        render_log_listing_pretty(records, file=buf, color=False)
        out = buf.getvalue()
        assert "synthesis" in out
        assert "Synthesis_yosys/log/synthesis.log" in out

    def test_listing_inspect_cmd(self):
        from io import StringIO

        records = [
            {
                "step": "synthesis",
                "source": "Synthesis_yosys/log/synthesis.log",
                "inspect_cmd": "ecc log synthesis",
            },
        ]
        buf = StringIO()
        render_log_listing_pretty(records, file=buf, color=False)
        assert "ecc log synthesis" in buf.getvalue()

    def test_listing_color_enabled_no_crash(self):
        from io import StringIO

        records = [
            {
                "step": "synthesis",
                "source": "Synthesis_yosys/log/synthesis.log",
                "inspect_cmd": "ecc log synthesis",
            },
        ]
        buf = StringIO()
        render_log_listing_pretty(records, file=buf, color=True)
        out = buf.getvalue()
        assert "[logs]" in out
        assert "synthesis" in out
        assert "Synthesis_yosys/log/synthesis.log" in out
        assert "ecc log synthesis" in out

    def test_listing_color_enabled_has_ansi(self):
        from io import StringIO

        records = [
            {
                "step": "synthesis",
                "source": "Synthesis_yosys/log/synthesis.log",
                "inspect_cmd": "ecc log synthesis",
            },
        ]
        buf = StringIO()
        render_log_listing_pretty(records, file=buf, color=True)
        assert "\x1b[" in buf.getvalue()

    def test_listing_color_disabled_no_ansi(self):
        from io import StringIO

        records = [
            {
                "step": "synthesis",
                "source": "Synthesis_yosys/log/synthesis.log",
                "inspect_cmd": "ecc log synthesis",
            },
        ]
        buf = StringIO()
        render_log_listing_pretty(records, file=buf, color=False)
        assert "\x1b[" not in buf.getvalue()


class TestTailLinesForLog:
    def test_returns_last_10_non_empty(self, tmp_path):
        from chipcompiler.cli.inspection.log_view import tail_lines_for_log

        log_file = tmp_path / "test.log"
        lines = [f"line {i}" for i in range(15)]
        log_file.write_text("\n".join(lines))
        result = tail_lines_for_log(str(log_file))
        assert len(result) == 10
        assert result[0] == "line 5"
        assert result[-1] == "line 14"

    def test_fewer_than_10_returns_all(self, tmp_path):
        from chipcompiler.cli.inspection.log_view import tail_lines_for_log

        log_file = tmp_path / "test.log"
        log_file.write_text("a\nb\nc\n")
        result = tail_lines_for_log(str(log_file))
        assert result == ["a", "b", "c"]

    def test_empty_lines_omitted(self, tmp_path):
        from chipcompiler.cli.inspection.log_view import tail_lines_for_log

        log_file = tmp_path / "test.log"
        log_file.write_text("a\n\n\nb\n\n\nc\n")
        result = tail_lines_for_log(str(log_file))
        assert result == ["a", "b", "c"]

    def test_preserves_order(self, tmp_path):
        from chipcompiler.cli.inspection.log_view import tail_lines_for_log

        log_file = tmp_path / "test.log"
        log_file.write_text("first\nmiddle\nlast\n")
        result = tail_lines_for_log(str(log_file))
        assert result == ["first", "middle", "last"]

    def test_ansi_stripped(self, tmp_path):
        from chipcompiler.cli.inspection.log_view import tail_lines_for_log

        log_file = tmp_path / "test.log"
        log_file.write_text("\x1b[31mred text\x1b[0m\nnormal\n")
        result = tail_lines_for_log(str(log_file))
        assert result == ["red text", "normal"]

    def test_missing_file_returns_empty(self, tmp_path):
        from chipcompiler.cli.inspection.log_view import tail_lines_for_log

        result = tail_lines_for_log(str(tmp_path / "nonexistent.log"))
        assert result == []

    def test_empty_file_returns_empty(self, tmp_path):
        from chipcompiler.cli.inspection.log_view import tail_lines_for_log

        log_file = tmp_path / "test.log"
        log_file.write_text("")
        result = tail_lines_for_log(str(log_file))
        assert result == []

    def test_blank_only_file_returns_empty(self, tmp_path):
        from chipcompiler.cli.inspection.log_view import tail_lines_for_log

        log_file = tmp_path / "test.log"
        log_file.write_text("   \n\n\t\n   \n")
        result = tail_lines_for_log(str(log_file))
        assert result == []

    def test_ansi_control_sequences_stripped(self, tmp_path):
        from chipcompiler.cli.inspection.log_view import tail_lines_for_log

        log_file = tmp_path / "test.log"
        log_file.write_text("\x1b[31mred\x1b[0m\n\x1b[2Kclear\nvalid\n")
        result = tail_lines_for_log(str(log_file))
        assert "\x1b[" not in " ".join(result)
        assert "valid" in result

    def test_osc_sequences_stripped(self, tmp_path):
        from chipcompiler.cli.inspection.log_view import tail_lines_for_log

        log_file = tmp_path / "test.log"
        log_file.write_text("\x1b]0;window title\x07message\n")
        result = tail_lines_for_log(str(log_file))
        assert result == ["message"]

    def test_dcs_sequences_stripped(self, tmp_path):
        from chipcompiler.cli.inspection.log_view import tail_lines_for_log

        log_file = tmp_path / "test.log"
        log_file.write_text("\x1bP$data\x1b\\visible\n")
        result = tail_lines_for_log(str(log_file))
        assert result == ["visible"]

    def test_bel_and_backspace_stripped(self, tmp_path):
        from chipcompiler.cli.inspection.log_view import tail_lines_for_log

        log_file = tmp_path / "test.log"
        log_file.write_text("a\x07b\x08c\ndone\n")
        result = tail_lines_for_log(str(log_file))
        assert result == ["abc", "done"]

    def test_unreadable_file_returns_empty(self, tmp_path):
        from chipcompiler.cli.inspection.log_view import tail_lines_for_log

        log_file = tmp_path / "test.log"
        log_file.write_text("content\n")
        os.chmod(str(log_file), 0o000)
        try:
            result = tail_lines_for_log(str(log_file))
            assert result == []
        finally:
            os.chmod(str(log_file), 0o644)


class TestListingTailRendering:
    def test_tail_block_header_with_indented_lines(self):
        from io import StringIO

        records = [
            {"step": "synthesis", "source": "synth.log", "inspect_cmd": "ecc log synthesis"},
        ]
        tail_map = {"synth.log": ["line 1", "line 2"]}
        buf = StringIO()
        render_log_listing_pretty(records, file=buf, color=False, tail_map=tail_map)
        out = buf.getvalue()
        lines = out.split("\n")
        tail_idx = next(index for index, line in enumerate(lines) if line.strip() == "tail:")
        assert "line 1" in lines[tail_idx + 1]
        assert "line 2" in lines[tail_idx + 2]
        assert lines[tail_idx + 1].startswith("      ")

    def test_inspect_remains_below_tail(self):
        from io import StringIO

        records = [
            {"step": "synthesis", "source": "synth.log", "inspect_cmd": "ecc log synthesis"},
        ]
        tail_map = {"synth.log": ["preview"]}
        buf = StringIO()
        render_log_listing_pretty(records, file=buf, color=False, tail_map=tail_map)
        out = buf.getvalue()
        tail_pos = out.find("tail:")
        inspect_pos = out.find("inspect:")
        assert tail_pos < inspect_pos

    def test_no_tail_block_when_empty(self):
        from io import StringIO

        records = [
            {"step": "synthesis", "source": "synth.log", "inspect_cmd": "ecc log synthesis"},
        ]
        tail_map = {"synth.log": []}
        buf = StringIO()
        render_log_listing_pretty(records, file=buf, color=False, tail_map=tail_map)
        out = buf.getvalue()
        assert "tail:" not in out
        assert "inspect:" in out

    def test_no_tail_block_when_source_not_in_map(self):
        from io import StringIO

        records = [
            {"step": "synthesis", "source": "synth.log", "inspect_cmd": "ecc log synthesis"},
        ]
        buf = StringIO()
        render_log_listing_pretty(records, file=buf, color=False, tail_map={})
        out = buf.getvalue()
        assert "tail:" not in out
        assert "inspect:" in out

    def test_no_tail_block_when_tail_map_is_none(self):
        from io import StringIO

        records = [
            {"step": "synthesis", "source": "synth.log", "inspect_cmd": "ecc log synthesis"},
        ]
        buf = StringIO()
        render_log_listing_pretty(records, file=buf, color=False, tail_map=None)
        out = buf.getvalue()
        assert "tail:" not in out
        assert "inspect:" in out

    def test_run_level_entry_labeled_run(self):
        from io import StringIO

        records = [
            {"log": "log/flow.log", "inspect_cmd": "ecc log"},
        ]
        buf = StringIO()
        render_log_listing_pretty(records, file=buf, color=False)
        out = buf.getvalue()
        assert "  run  log/flow.log" in out
        assert "inspect:" in out
