"""Tests for chipcompiler.runtime.log_stream — marker parsing and archive."""

import io

from chipcompiler.runtime.log_stream import (
    LogStreamReader,
    StepMarker,
    parse_marker,
)


class TestParseMarker:
    def test_valid_begin(self):
        line = b'\x1eECC-STEP {"event":"begin","step":"Synthesis","tool":"yosys"}\n'
        m = parse_marker(line)
        assert m == StepMarker(event="begin", step="Synthesis", tool="yosys")

    def test_valid_end(self):
        line = b'\x1eECC-STEP {"event":"end","step":"Placement","tool":"ecc"}\n'
        m = parse_marker(line)
        assert m == StepMarker(event="end", step="Placement", tool="ecc")

    def test_no_prefix(self):
        assert parse_marker(b"normal log line\n") is None

    def test_malformed_json(self):
        assert parse_marker(b"\x1eECC-STEP {bad json}\n") is None

    def test_missing_fields(self):
        line = b'\x1eECC-STEP {"event":"begin"}\n'
        assert parse_marker(line) is None

    def test_wrong_field_types(self):
        line = b'\x1eECC-STEP {"event":1,"step":"A","tool":"B"}\n'
        assert parse_marker(line) is None

    def test_no_trailing_newline(self):
        line = b'\x1eECC-STEP {"event":"begin","step":"S","tool":"T"}'
        m = parse_marker(line)
        assert m is not None
        assert m.event == "begin"


class TestLogStreamReader:
    def _make_stream(self, chunks: list[bytes]) -> io.BytesIO:
        return io.BytesIO(b"".join(chunks))

    def test_archives_to_step_file(self, tmp_path):
        log_path = tmp_path / "synth.log"

        def resolver(step, tool):
            return log_path

        stream_data = (
            b'\x1eECC-STEP {"event":"begin","step":"Synthesis","tool":"yosys"}\n'
            b"yosys output line 1\n"
            b"yosys output line 2\n"
            b'\x1eECC-STEP {"event":"end","step":"Synthesis","tool":"yosys"}\n'
        )
        stream = io.BytesIO(stream_data)
        reader = LogStreamReader(stream, log_path_resolver=resolver)
        reader.start()
        reader.join(timeout=5)

        assert log_path.exists()
        content = log_path.read_bytes()
        assert b"yosys output line 1\n" in content
        assert b"yosys output line 2\n" in content
        assert b"ECC-STEP" not in content

    def test_markers_not_archived(self, tmp_path):
        log_path = tmp_path / "step.log"

        def resolver(step, tool):
            return log_path

        stream_data = (
            b'\x1eECC-STEP {"event":"begin","step":"S","tool":"T"}\n'
            b"data\n"
            b'\x1eECC-STEP {"event":"end","step":"S","tool":"T"}\n'
        )
        reader = LogStreamReader(io.BytesIO(stream_data), log_path_resolver=resolver)
        reader.start()
        reader.join(timeout=5)
        assert log_path.read_bytes() == b"data\n"

    def test_multiple_steps(self, tmp_path):
        paths = {}

        def resolver(step, tool):
            p = tmp_path / f"{step}.log"
            paths[step] = p
            return p

        stream_data = (
            b'\x1eECC-STEP {"event":"begin","step":"A","tool":"t"}\n'
            b"output A\n"
            b'\x1eECC-STEP {"event":"end","step":"A","tool":"t"}\n'
            b'\x1eECC-STEP {"event":"begin","step":"B","tool":"t"}\n'
            b"output B\n"
            b'\x1eECC-STEP {"event":"end","step":"B","tool":"t"}\n'
        )
        reader = LogStreamReader(io.BytesIO(stream_data), log_path_resolver=resolver)
        reader.start()
        reader.join(timeout=5)
        assert paths["A"].read_bytes() == b"output A\n"
        assert paths["B"].read_bytes() == b"output B\n"
        assert reader.state.steps_seen == ["A", "B"]

    def test_non_utf8_bytes_preserved(self, tmp_path):
        log_path = tmp_path / "step.log"

        def resolver(step, tool):
            return log_path

        raw = b"\x80\x81\xff\xfe binary data\n"
        stream_data = (
            b'\x1eECC-STEP {"event":"begin","step":"S","tool":"T"}\n'
            + raw
            + b'\x1eECC-STEP {"event":"end","step":"S","tool":"T"}\n'
        )
        reader = LogStreamReader(io.BytesIO(stream_data), log_path_resolver=resolver)
        reader.start()
        reader.join(timeout=5)
        assert log_path.read_bytes() == raw

    def test_malformed_marker_treated_as_data(self, tmp_path):
        log_path = tmp_path / "step.log"

        def resolver(step, tool):
            return log_path

        stream_data = (
            b'\x1eECC-STEP {"event":"begin","step":"S","tool":"T"}\n'
            b"\x1eECC-STEP {bad json}\n"
            b'\x1eECC-STEP {"event":"end","step":"S","tool":"T"}\n'
        )
        reader = LogStreamReader(io.BytesIO(stream_data), log_path_resolver=resolver)
        reader.start()
        reader.join(timeout=5)
        assert b"{bad json}" in log_path.read_bytes()

    def test_on_output_callback(self):
        received = []
        stream_data = b"hello world\n"
        reader = LogStreamReader(io.BytesIO(stream_data), on_output=received.append)
        reader.start()
        reader.join(timeout=5)
        assert b"hello world\n" in b"".join(received)

    def test_tail_bytes_maintained(self):
        data = b"x" * 8000 + b"\n"
        reader = LogStreamReader(io.BytesIO(data), tail_size=100)
        reader.start()
        reader.join(timeout=5)
        assert len(reader.state.tail_bytes) == 100

    def test_unknown_marker_event_archived_as_data(self, tmp_path):
        """A valid marker with an unrecognized event must be archived as raw data."""
        log_path = tmp_path / "step.log"

        def resolver(step, tool):
            return log_path

        unknown_line = b'\x1eECC-STEP {"event":"pause","step":"S","tool":"T"}\n'
        stream_data = (
            b'\x1eECC-STEP {"event":"begin","step":"S","tool":"T"}\n'
            + unknown_line
            + b'\x1eECC-STEP {"event":"end","step":"S","tool":"T"}\n'
        )
        reader = LogStreamReader(io.BytesIO(stream_data), log_path_resolver=resolver)
        reader.start()
        reader.join(timeout=5)
        assert log_path.read_bytes() == unknown_line

    def test_archive_write_error_surfaces_in_state(self, tmp_path):
        """An OSError during archive write must be captured in state.error."""
        log_path = tmp_path / "step.log"

        def resolver(step, tool):
            return log_path

        stream_data = (
            b'\x1eECC-STEP {"event":"begin","step":"S","tool":"T"}\n'
            b"some output\n"
            b'\x1eECC-STEP {"event":"end","step":"S","tool":"T"}\n'
        )
        reader = LogStreamReader(io.BytesIO(stream_data), log_path_resolver=resolver)
        reader.start()
        reader.join(timeout=5)

        log_path.unlink()
        log_path.mkdir()

        stream_data2 = (
            b'\x1eECC-STEP {"event":"begin","step":"S","tool":"T"}\n'
            b"more output\n"
            b'\x1eECC-STEP {"event":"end","step":"S","tool":"T"}\n'
        )
        reader2 = LogStreamReader(io.BytesIO(stream_data2), log_path_resolver=resolver)
        reader2.start()
        reader2.join(timeout=5)
        assert reader2.state.error is not None
        assert isinstance(reader2.state.error, OSError)

    def test_archive_open_error_surfaces_in_state(self, tmp_path):
        """An OSError when opening an archive must be captured in state.error."""

        def resolver(step, tool):
            return tmp_path / "nonexistent_dir" / "sub" / "step.log"

        (tmp_path / "nonexistent_dir").write_text("not a directory")

        stream_data = (
            b'\x1eECC-STEP {"event":"begin","step":"S","tool":"T"}\n'
            b"output\n"
            b'\x1eECC-STEP {"event":"end","step":"S","tool":"T"}\n'
        )
        reader = LogStreamReader(io.BytesIO(stream_data), log_path_resolver=resolver)
        reader.start()
        reader.join(timeout=5)
        assert reader.state.error is not None
        assert isinstance(reader.state.error, OSError)

    def test_mismatched_end_marker_does_not_close_archive(self, tmp_path):
        """begin A -> end B -> data -> end A: data must be in A's archive."""
        log_path = tmp_path / "step.log"

        def resolver(step, tool):
            return log_path

        mismatched_end = b'\x1eECC-STEP {"event":"end","step":"B","tool":"T"}\n'
        stream_data = (
            b'\x1eECC-STEP {"event":"begin","step":"A","tool":"T"}\n'
            b"before\n"
            + mismatched_end
            + b"after\n"
            + b'\x1eECC-STEP {"event":"end","step":"A","tool":"T"}\n'
        )
        reader = LogStreamReader(io.BytesIO(stream_data), log_path_resolver=resolver)
        reader.start()
        reader.join(timeout=5)
        content = log_path.read_bytes()
        assert b"before\n" in content
        assert mismatched_end in content
        assert b"after\n" in content

    def test_active_step_tracked_in_state(self, tmp_path):
        """State tracks the active step/tool during archiving."""
        log_path = tmp_path / "step.log"

        def resolver(step, tool):
            return log_path

        stream_data = b'\x1eECC-STEP {"event":"begin","step":"Synthesis","tool":"yosys"}\ndata\n'
        reader = LogStreamReader(io.BytesIO(stream_data), log_path_resolver=resolver)
        reader.start()
        reader.join(timeout=5)
        assert reader.state.active_step == "Synthesis"
        assert reader.state.active_tool == "yosys"

    def test_duplicate_begin_does_not_switch_archive(self, tmp_path):
        """begin A -> data -> begin B -> data -> end A: all data stays in A's archive."""
        log_path = tmp_path / "step.log"

        def resolver(step, tool):
            return log_path

        begin_b = b'\x1eECC-STEP {"event":"begin","step":"B","tool":"T"}\n'
        stream_data = (
            b'\x1eECC-STEP {"event":"begin","step":"A","tool":"T"}\n'
            b"before\n"
            + begin_b
            + b"after\n"
            + b'\x1eECC-STEP {"event":"end","step":"A","tool":"T"}\n'
        )
        reader = LogStreamReader(io.BytesIO(stream_data), log_path_resolver=resolver)
        reader.start()
        reader.join(timeout=5)
        content = log_path.read_bytes()
        assert b"before\n" in content
        assert begin_b in content
        assert b"after\n" in content
        assert reader.state.active_step is None
        assert reader.state.steps_seen == ["A"]


class TestLogStreamAllowlist:
    def test_unknown_step_marker_treated_as_data(self, tmp_path):
        """A begin marker for a pair not in valid_steps is archived as data."""
        log_path = tmp_path / "step.log"

        def resolver(step, tool):
            return log_path

        valid = {("Synthesis", "yosys")}
        unknown_begin = b'\x1eECC-STEP {"event":"begin","step":"../../escape","tool":"evil"}\n'
        stream_data = (
            b'\x1eECC-STEP {"event":"begin","step":"Synthesis","tool":"yosys"}\n'
            + unknown_begin
            + b"normal data\n"
            + b'\x1eECC-STEP {"event":"end","step":"Synthesis","tool":"yosys"}\n'
        )
        reader = LogStreamReader(
            io.BytesIO(stream_data), log_path_resolver=resolver, valid_steps=valid
        )
        reader.start()
        reader.join(timeout=5)
        content = log_path.read_bytes()
        assert unknown_begin in content
        assert b"normal data\n" in content
        assert reader.state.steps_seen == ["Synthesis"]

    def test_unknown_step_before_any_active_is_data(self):
        """An unknown begin marker with no active step is sent to callback as data."""
        received = []
        valid = {("Place", "ecc")}
        stream_data = b'\x1eECC-STEP {"event":"begin","step":"Bogus","tool":"fake"}\ntrailing\n'
        reader = LogStreamReader(
            io.BytesIO(stream_data), on_output=received.append, valid_steps=valid
        )
        reader.start()
        reader.join(timeout=5)
        combined = b"".join(received)
        assert b"Bogus" in combined
        assert b"trailing\n" in combined
        assert reader.state.active_step is None

    def test_path_escape_does_not_open_archive(self, tmp_path):
        """A resolved path outside workspace_dir must not open an archive file."""
        escape_target = tmp_path / "outside.log"

        def resolver(step, tool):
            return escape_target

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        valid = {("Escape", "evil")}
        stream_data = (
            b'\x1eECC-STEP {"event":"begin","step":"Escape","tool":"evil"}\n'
            b"should not be written\n"
            b'\x1eECC-STEP {"event":"end","step":"Escape","tool":"evil"}\n'
        )
        reader = LogStreamReader(
            io.BytesIO(stream_data),
            log_path_resolver=resolver,
            valid_steps=valid,
            workspace_dir=workspace,
        )
        reader.start()
        reader.join(timeout=5)
        assert not escape_target.exists()
        assert reader.state.error is not None
        assert "escapes workspace" in str(reader.state.error)

    def test_contained_path_opens_normally(self, tmp_path):
        """A path that resolves inside workspace_dir opens and archives."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        log_path = workspace / "Synthesis_yosys" / "log" / "Synthesis.log"

        def resolver(step, tool):
            return log_path

        valid = {("Synthesis", "yosys")}
        stream_data = (
            b'\x1eECC-STEP {"event":"begin","step":"Synthesis","tool":"yosys"}\n'
            b"tool output\n"
            b'\x1eECC-STEP {"event":"end","step":"Synthesis","tool":"yosys"}\n'
        )
        reader = LogStreamReader(
            io.BytesIO(stream_data),
            log_path_resolver=resolver,
            valid_steps=valid,
            workspace_dir=workspace,
        )
        reader.start()
        reader.join(timeout=5)
        assert log_path.read_bytes() == b"tool output\n"
        assert reader.state.error is None


class TestLogStreamResilience:
    def test_resolver_exception_disables_archive_continues_drain(self):
        """A resolver that raises must not kill the drain thread."""
        received = []
        call_count = [0]

        def failing_resolver(step, tool):
            call_count[0] += 1
            raise RuntimeError("resolver failed")

        stream_data = (
            b'\x1eECC-STEP {"event":"begin","step":"S","tool":"T"}\n'
            b"output after failed resolver\n"
            b'\x1eECC-STEP {"event":"end","step":"S","tool":"T"}\n'
            b"trailing data\n"
        )
        reader = LogStreamReader(
            io.BytesIO(stream_data),
            log_path_resolver=failing_resolver,
            on_output=received.append,
        )
        reader.start()
        reader.join(timeout=5)
        assert reader.completed
        assert isinstance(reader.state.error, RuntimeError)
        assert "resolver failed" in str(reader.state.error)
        combined = b"".join(received)
        assert b"output after failed resolver\n" in combined
        assert b"trailing data\n" in combined

    def test_callback_exception_disables_callback_continues_drain(self, tmp_path):
        """An on_output callback that raises must not kill archiving."""
        log_path = tmp_path / "step.log"
        call_count = [0]

        def failing_callback(data):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ValueError("callback exploded")

        def resolver(step, tool):
            return log_path

        stream_data = (
            b'\x1eECC-STEP {"event":"begin","step":"S","tool":"T"}\n'
            b"line 1\n"
            b"line 2\n"
            b'\x1eECC-STEP {"event":"end","step":"S","tool":"T"}\n'
        )
        reader = LogStreamReader(
            io.BytesIO(stream_data),
            log_path_resolver=resolver,
            on_output=failing_callback,
        )
        reader.start()
        reader.join(timeout=5)
        assert reader.completed
        assert isinstance(reader.state.error, ValueError)
        content = log_path.read_bytes()
        assert b"line 1\n" in content
        assert b"line 2\n" in content

    def test_drain_completes_after_callback_disabled(self):
        """After callback is disabled, remaining data is still drained."""
        call_count = [0]

        def failing_callback(data):
            call_count[0] += 1
            raise RuntimeError("always fails")

        stream_data = b"line 1\nline 2\nline 3\n"
        reader = LogStreamReader(
            io.BytesIO(stream_data),
            on_output=failing_callback,
        )
        reader.start()
        reader.join(timeout=5)
        assert reader.completed
        assert call_count[0] == 1
        assert b"line 3\n" in reader.state.tail_bytes
