"""Tests for chipcompiler.runtime.log_stream — reader archiving and resilience."""

import io

from chipcompiler.runtime.log_stream import LogStreamReader


class TestLogStreamReader:
    def _make_stream(self, chunks: list[bytes]) -> io.BytesIO:
        return io.BytesIO(b"".join(chunks))

    def test_archives_to_step_file(self, tmp_path):
        log_path = tmp_path / "synth.log"

        def resolver(step, tool):
            return log_path

        stream_data = (
            b'\x1eECC-STEP {"v":1,"event":"begin","step":"Synthesis","tool":"yosys"}\n'
            b"yosys output line 1\n"
            b"yosys output line 2\n"
            b'\x1eECC-STEP {"v":1,"event":"end","step":"Synthesis","tool":"yosys"}\n'
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
            b'\x1eECC-STEP {"v":1,"event":"begin","step":"S","tool":"T"}\n'
            b"data\n"
            b'\x1eECC-STEP {"v":1,"event":"end","step":"S","tool":"T"}\n'
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
            b'\x1eECC-STEP {"v":1,"event":"begin","step":"A","tool":"t"}\n'
            b"output A\n"
            b'\x1eECC-STEP {"v":1,"event":"end","step":"A","tool":"t"}\n'
            b'\x1eECC-STEP {"v":1,"event":"begin","step":"B","tool":"t"}\n'
            b"output B\n"
            b'\x1eECC-STEP {"v":1,"event":"end","step":"B","tool":"t"}\n'
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
            b'\x1eECC-STEP {"v":1,"event":"begin","step":"S","tool":"T"}\n'
            + raw
            + b'\x1eECC-STEP {"v":1,"event":"end","step":"S","tool":"T"}\n'
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
            b'\x1eECC-STEP {"v":1,"event":"begin","step":"S","tool":"T"}\n'
            b"\x1eECC-STEP {bad json}\n"
            b'\x1eECC-STEP {"v":1,"event":"end","step":"S","tool":"T"}\n'
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

        unknown_line = b'\x1eECC-STEP {"v":1,"event":"pause","step":"S","tool":"T"}\n'
        stream_data = (
            b'\x1eECC-STEP {"v":1,"event":"begin","step":"S","tool":"T"}\n'
            + unknown_line
            + b'\x1eECC-STEP {"v":1,"event":"end","step":"S","tool":"T"}\n'
        )
        reader = LogStreamReader(io.BytesIO(stream_data), log_path_resolver=resolver)
        reader.start()
        reader.join(timeout=5)
        assert log_path.read_bytes() == unknown_line

    def test_unversioned_marker_archived_as_data(self, tmp_path):
        """A marker frame without a supported version is archived as raw data."""
        log_path = tmp_path / "step.log"

        def resolver(step, tool):
            return log_path

        unversioned_begin = b'\x1eECC-STEP {"event":"begin","step":"S","tool":"T"}\n'
        stream_data = (
            b'\x1eECC-STEP {"v":1,"event":"begin","step":"S","tool":"T"}\n'
            + unversioned_begin
            + b'\x1eECC-STEP {"v":1,"event":"end","step":"S","tool":"T"}\n'
        )
        reader = LogStreamReader(io.BytesIO(stream_data), log_path_resolver=resolver)
        reader.start()
        reader.join(timeout=5)
        assert log_path.read_bytes() == unversioned_begin
        assert reader.state.steps_seen == ["S"]

    def test_archive_write_error_surfaces_in_state(self, tmp_path):
        """An OSError during archive write must be captured in state.error."""
        log_path = tmp_path / "step.log"

        def resolver(step, tool):
            return log_path

        stream_data = (
            b'\x1eECC-STEP {"v":1,"event":"begin","step":"S","tool":"T"}\n'
            b"some output\n"
            b'\x1eECC-STEP {"v":1,"event":"end","step":"S","tool":"T"}\n'
        )
        reader = LogStreamReader(io.BytesIO(stream_data), log_path_resolver=resolver)
        reader.start()
        reader.join(timeout=5)

        log_path.unlink()
        log_path.mkdir()

        stream_data2 = (
            b'\x1eECC-STEP {"v":1,"event":"begin","step":"S","tool":"T"}\n'
            b"more output\n"
            b'\x1eECC-STEP {"v":1,"event":"end","step":"S","tool":"T"}\n'
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
            b'\x1eECC-STEP {"v":1,"event":"begin","step":"S","tool":"T"}\n'
            b"output\n"
            b'\x1eECC-STEP {"v":1,"event":"end","step":"S","tool":"T"}\n'
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

        mismatched_end = b'\x1eECC-STEP {"v":1,"event":"end","step":"B","tool":"T"}\n'
        stream_data = (
            b'\x1eECC-STEP {"v":1,"event":"begin","step":"A","tool":"T"}\n'
            b"before\n"
            + mismatched_end
            + b"after\n"
            + b'\x1eECC-STEP {"v":1,"event":"end","step":"A","tool":"T"}\n'
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

        stream_data = (
            b'\x1eECC-STEP {"v":1,"event":"begin","step":"Synthesis","tool":"yosys"}\ndata\n'
        )
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

        begin_b = b'\x1eECC-STEP {"v":1,"event":"begin","step":"B","tool":"T"}\n'
        stream_data = (
            b'\x1eECC-STEP {"v":1,"event":"begin","step":"A","tool":"T"}\n'
            b"before\n"
            + begin_b
            + b"after\n"
            + b'\x1eECC-STEP {"v":1,"event":"end","step":"A","tool":"T"}\n'
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


class TestLiveStreaming:
    def test_short_output_flows_without_waiting_for_8kib(self):
        """read1 delivers available bytes immediately; read(8192) would block
        until the buffer fills or EOF and stall live progress."""
        import os
        import time

        read_fd, write_fd = os.pipe()
        received = []
        reader = LogStreamReader(os.fdopen(read_fd, "rb"), on_output=received.append)
        reader.start()
        try:
            os.write(write_fd, b"short line\n")
            deadline = time.monotonic() + 2.0
            while not received and time.monotonic() < deadline:
                time.sleep(0.01)
            assert received == [b"short line\n"]
        finally:
            os.close(write_fd)
            reader.join(timeout=5)
            reader.stop()


class TestArchiveOwnStepLogs:
    """In-process executor runs self-archive through the fd-2 pipe."""

    def test_archives_step_bytes_and_echoes_without_markers(self, tmp_path, capfd):
        import json
        import os

        from chipcompiler.runtime.log_stream import archive_own_step_logs, emit_step_marker

        workspace = tmp_path / "ws"
        (workspace / "home").mkdir(parents=True)
        (workspace / "home" / "flow.json").write_text(
            json.dumps({"steps": [{"name": "S", "tool": "T", "state": "Ongoing"}]})
        )

        with archive_own_step_logs(workspace) as reader:
            emit_step_marker("begin", step="S", tool="T")
            os.write(2, b"tool output\n")
            os.write(1, b"stdout line\n")
            emit_step_marker("end", step="S", tool="T")
            os.write(2, b"unscoped tail\n")

        assert reader.state.error is None
        # fd 1 and fd 2 bytes both land in the archive, markers never do.
        assert (workspace / "S_T" / "log" / "S.log").read_bytes() == (b"tool output\nstdout line\n")
        echoed = capfd.readouterr().err
        assert "tool output" in echoed
        assert "stdout line" in echoed
        assert "unscoped tail" in echoed
        assert "ECC-STEP" not in echoed


class TestArchiveOwnStepLogsPassthrough:
    def test_external_client_or_nesting_passes_through(self, tmp_path, capfd):
        """A worker/sidecar process (marked) or an already-active outer context
        must not double-wrap: markers keep flowing to the outer client."""
        import os

        import chipcompiler.runtime.log_stream as log_stream_module
        from chipcompiler.runtime.log_stream import archive_own_step_logs, emit_step_marker

        workspace = tmp_path / "ws"
        (workspace / "home").mkdir(parents=True)

        # Nested: the outer context archives; the inner one passes through.
        with (
            archive_own_step_logs(workspace),
            archive_own_step_logs(workspace) as inner,
        ):
            assert inner is None
            emit_step_marker("begin", step="S", tool="T")
            os.write(2, b"bytes\n")
            emit_step_marker("end", step="S", tool="T")
        assert (workspace / "S_T" / "log" / "S.log").read_bytes() == b"bytes\n"
        assert "ECC-STEP" not in capfd.readouterr().err

        # Marked external client: no self-archive at all, bytes pass through.
        log_stream_module.mark_external_log_client()
        try:
            with archive_own_step_logs(workspace) as reader:
                assert reader is None
                os.write(2, b"raw\n")
        finally:
            log_stream_module._EXTERNAL_LOG_CLIENT = False
        assert "raw" in capfd.readouterr().err


class TestLogStreamResilience:
    def test_resolver_exception_disables_archive_continues_drain(self):
        """A resolver that raises must not kill the drain thread."""
        received = []
        call_count = [0]

        def failing_resolver(step, tool):
            call_count[0] += 1
            raise RuntimeError("resolver failed")

        stream_data = (
            b'\x1eECC-STEP {"v":1,"event":"begin","step":"S","tool":"T"}\n'
            b"output after failed resolver\n"
            b'\x1eECC-STEP {"v":1,"event":"end","step":"S","tool":"T"}\n'
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
            b'\x1eECC-STEP {"v":1,"event":"begin","step":"S","tool":"T"}\n'
            b"line 1\n"
            b"line 2\n"
            b'\x1eECC-STEP {"v":1,"event":"end","step":"S","tool":"T"}\n'
        )
        reader = LogStreamReader(
            io.BytesIO(stream_data),
            log_path_resolver=resolver,
            on_output=failing_callback,
        )
        reader.start()
        reader.join(timeout=5)
        assert reader.completed
        assert isinstance(reader.state.display_error, ValueError)
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
