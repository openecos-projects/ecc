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
