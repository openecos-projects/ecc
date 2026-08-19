"""Tests for chipcompiler.runtime.log_stream — marker protocol parsing and emission."""

import io
import os

import pytest

from chipcompiler.runtime.log_stream import (
    MARKER_PREFIX,
    LogStreamReader,
    StepMarker,
    emit_step_marker,
    parse_marker,
)


class _ChunkedStream:
    """A binary stream that returns fixed-size chunks regardless of read size."""

    def __init__(self, data: bytes, chunk_size: int):
        self._data = data
        self._chunk_size = chunk_size
        self._pos = 0

    def read(self, n: int = -1) -> bytes:
        if self._pos >= len(self._data):
            return b""
        size = self._chunk_size if n < 0 else min(n, self._chunk_size)
        part = self._data[self._pos : self._pos + size]
        self._pos += size
        return part


class TestParseMarker:
    def test_valid_begin(self):
        line = b'\x1eECC-STEP {"v":1,"event":"begin","step":"Synthesis","tool":"yosys"}\n'
        m = parse_marker(line)
        assert m == StepMarker(event="begin", step="Synthesis", tool="yosys")

    def test_valid_end(self):
        line = b'\x1eECC-STEP {"v":1,"event":"end","step":"Placement","tool":"ecc"}\n'
        m = parse_marker(line)
        assert m == StepMarker(event="end", step="Placement", tool="ecc")

    def test_no_prefix(self):
        assert parse_marker(b"normal log line\n") is None

    def test_malformed_json(self):
        assert parse_marker(b"\x1eECC-STEP {bad json}\n") is None

    def test_missing_fields(self):
        line = b'\x1eECC-STEP {"v":1,"event":"begin"}\n'
        assert parse_marker(line) is None

    def test_wrong_field_types(self):
        line = b'\x1eECC-STEP {"v":1,"event":1,"step":"A","tool":"B"}\n'
        assert parse_marker(line) is None

    def test_no_trailing_newline(self):
        line = b'\x1eECC-STEP {"v":1,"event":"begin","step":"S","tool":"T"}'
        m = parse_marker(line)
        assert m is not None
        assert m.event == "begin"

    def test_missing_version_rejected(self):
        line = b'\x1eECC-STEP {"event":"begin","step":"S","tool":"T"}\n'
        assert parse_marker(line) is None

    def test_unsupported_version_rejected(self):
        line = b'\x1eECC-STEP {"v":2,"event":"begin","step":"S","tool":"T"}\n'
        assert parse_marker(line) is None

    def test_string_version_rejected(self):
        line = b'\x1eECC-STEP {"v":"1","event":"begin","step":"S","tool":"T"}\n'
        assert parse_marker(line) is None

    def test_boolean_version_rejected(self):
        line = b'\x1eECC-STEP {"v":true,"event":"begin","step":"S","tool":"T"}\n'
        assert parse_marker(line) is None

    def test_non_utf8_payload_rejected(self):
        line = b'\x1eECC-STEP {"v":1,"event":"begin","step":"S\xff","tool":"T"}\n'
        assert parse_marker(line) is None

    @pytest.mark.parametrize("payload", ["[]", "null", "42", '"hello"', "true"])
    def test_non_object_payload_rejected(self, payload):
        line = f"\x1eECC-STEP {payload}\n".encode()
        assert parse_marker(line) is None


class TestEmitStepMarker:
    def test_payload_carries_version_and_round_trips(self, monkeypatch):
        written = []
        real_write = os.write

        def fake_write(fd, data):
            if fd == 2:
                written.append(data)
                return len(data)
            return real_write(fd, data)

        monkeypatch.setattr(os, "write", fake_write)
        emit_step_marker("begin", step="Synthesis", tool="yosys")

        assert written == [
            MARKER_PREFIX + b'{"v":1,"event":"begin","step":"Synthesis","tool":"yosys"}\n'
        ]
        assert parse_marker(written[0]) == StepMarker(event="begin", step="Synthesis", tool="yosys")

    def test_c_stdio_buffer_drains_before_marker(self, tmp_path):
        """Native buffered output must reach fd 2 ahead of the marker bytes."""
        import ctypes

        libc = ctypes.CDLL(None)
        libc.fdopen.restype = ctypes.c_void_p
        libc.fdopen.argtypes = [ctypes.c_int, ctypes.c_char_p]
        libc.setvbuf.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_size_t]
        libc.fputs.argtypes = [ctypes.c_char_p, ctypes.c_void_p]
        libc.fclose.argtypes = [ctypes.c_void_p]
        _IOFBF = 0

        sink = tmp_path / "fd2.bin"
        saved_fd = os.dup(2)
        try:
            with sink.open("wb") as handle:
                os.dup2(handle.fileno(), 2)
            # A fully buffered FILE* targeting fd 2: fputs bytes stay in the C
            # buffer until something flushes the process streams.
            stream = libc.fdopen(os.dup(2), b"w")
            assert stream
            assert libc.setvbuf(stream, None, _IOFBF, 4096) == 0
            libc.fputs(b"native-before-end\n", stream)
            emit_step_marker("end", step="S", tool="T")
            libc.fclose(stream)
        finally:
            os.dup2(saved_fd, 2)
            os.close(saved_fd)

        content = sink.read_bytes()
        assert content == (
            b"native-before-end\n"
            + MARKER_PREFIX
            + b'{"v":1,"event":"end","step":"S","tool":"T"}\n'
        )


class TestMarkerBoundaryScanning:
    """Markers are recognized wherever the reserved prefix appears."""

    def test_end_marker_after_unterminated_output(self, tmp_path):
        log_path = tmp_path / "step.log"
        stream_data = (
            b'\x1eECC-STEP {"v":1,"event":"begin","step":"S","tool":"T"}\n'
            b"last line without newline"
            b'\x1eECC-STEP {"v":1,"event":"end","step":"S","tool":"T"}\n'
        )
        reader = LogStreamReader(
            io.BytesIO(stream_data), log_path_resolver=lambda step, tool: log_path
        )
        reader.start()
        reader.join(timeout=5)
        assert log_path.read_bytes() == b"last line without newline"
        assert reader.state.active_step is None
        assert reader.state.steps_seen == ["S"]

    def test_end_marker_split_after_unterminated_output(self, tmp_path):
        log_path = tmp_path / "step.log"
        end_frame = b'\x1eECC-STEP {"v":1,"event":"end","step":"S","tool":"T"}\n'
        stream_data = (
            b'\x1eECC-STEP {"v":1,"event":"begin","step":"S","tool":"T"}\nunterminated' + end_frame
        )
        reader = LogStreamReader(
            _ChunkedStream(stream_data, 7), log_path_resolver=lambda step, tool: log_path
        )
        reader.start()
        reader.join(timeout=5)
        assert log_path.read_bytes() == b"unterminated"
        assert reader.state.active_step is None

    def test_invalid_marker_mid_line_is_data(self, tmp_path):
        log_path = tmp_path / "step.log"
        stream_data = (
            b'\x1eECC-STEP {"v":1,"event":"begin","step":"S","tool":"T"}\n'
            b"glued text \x1eECC-STEP {bad json}\n"
            b'\x1eECC-STEP {"v":1,"event":"end","step":"S","tool":"T"}\n'
        )
        reader = LogStreamReader(
            io.BytesIO(stream_data), log_path_resolver=lambda step, tool: log_path
        )
        reader.start()
        reader.join(timeout=5)
        content = log_path.read_bytes()
        assert b"glued text " in content
        assert b"{bad json}" in content
        assert reader.state.active_step is None

    def test_overlong_candidate_recovers_following_marker(self, tmp_path):
        log_path = tmp_path / "step.log"
        stream_data = (
            b'\x1eECC-STEP {"v":1,"event":"begin","step":"S","tool":"T"}\n'
            b"\x1eECC-STEP "
            + b"a" * 600
            + b'\x1eECC-STEP {"v":1,"event":"end","step":"S","tool":"T"}\n'
        )
        reader = LogStreamReader(
            _ChunkedStream(stream_data, 100), log_path_resolver=lambda step, tool: log_path
        )
        reader.start()
        reader.join(timeout=5)
        content = log_path.read_bytes()
        assert b"a" * 600 in content
        assert b'"event":"end"' not in content
        assert reader.state.active_step is None

    def test_candidate_at_exactly_512_bytes_is_held(self, tmp_path):
        """A 512-byte candidate without its newline is held, then consumed."""
        log_path = tmp_path / "step.log"
        wrapper = b'{"v":1,"event":"begin","step":"%s","tool":"T"}'
        pad = 512 - len(b"\x1eECC-STEP ") - (len(wrapper) - 2)
        payload = wrapper % (b"S" * pad)
        frame_head = b"\x1eECC-STEP " + payload
        assert len(frame_head) == 512
        reader = LogStreamReader(
            _ChunkedStream(
                frame_head + b"\nbody\n" + frame_head.replace(b"begin", b"end") + b"\n", 512
            ),
            log_path_resolver=lambda step, tool: log_path,
        )
        reader.start()
        reader.join(timeout=5)
        assert log_path.read_bytes() == b"body\n"
        assert reader.state.active_step is None

    def test_candidate_beyond_512_bytes_degrades(self, tmp_path):
        received = []
        overlong = b"\x1eECC-STEP " + b"a" * 503
        assert len(overlong) > 512
        reader = LogStreamReader(_ChunkedStream(overlong, 64), on_output=received.append)
        reader.start()
        reader.join(timeout=5)
        assert b"".join(received) == overlong
        assert reader.state.active_step is None
