"""Tests for chipcompiler.runtime.log_stream — archive targets and step events."""

import io

from chipcompiler.runtime.log_stream import LogStreamReader


class TestLogStreamAllowlist:
    def test_unknown_step_marker_treated_as_data(self, tmp_path):
        """A begin marker for a pair not in valid_steps is archived as data."""
        log_path = tmp_path / "step.log"

        def resolver(step, tool):
            return log_path

        valid = {("Synthesis", "yosys")}
        unknown_begin = (
            b'\x1eECC-STEP {"v":1,"event":"begin","step":"../../escape","tool":"evil"}\n'
        )
        stream_data = (
            b'\x1eECC-STEP {"v":1,"event":"begin","step":"Synthesis","tool":"yosys"}\n'
            + unknown_begin
            + b"normal data\n"
            + b'\x1eECC-STEP {"v":1,"event":"end","step":"Synthesis","tool":"yosys"}\n'
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
        stream_data = (
            b'\x1eECC-STEP {"v":1,"event":"begin","step":"Bogus","tool":"fake"}\ntrailing\n'
        )
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
            b'\x1eECC-STEP {"v":1,"event":"begin","step":"Escape","tool":"evil"}\n'
            b"should not be written\n"
            b'\x1eECC-STEP {"v":1,"event":"end","step":"Escape","tool":"evil"}\n'
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
            b'\x1eECC-STEP {"v":1,"event":"begin","step":"Synthesis","tool":"yosys"}\n'
            b"tool output\n"
            b'\x1eECC-STEP {"v":1,"event":"end","step":"Synthesis","tool":"yosys"}\n'
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


class TestArchiveTargetSanitization:
    def test_separator_in_name_degrades_to_data(self, tmp_path):
        """An allowlisted begin with a path separator is ordinary bytes, not a marker."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        received = []

        def resolver(step, tool):
            base = workspace
            return base / f"{step}_{tool}" / "log" / f"{step}.log"

        unsafe_begin = b'\x1eECC-STEP {"v":1,"event":"begin","step":"foo/bar","tool":"ecc"}\n'
        stream_data = unsafe_begin + b"body bytes\n"
        reader = LogStreamReader(
            io.BytesIO(stream_data),
            log_path_resolver=resolver,
            valid_steps={("foo/bar", "ecc")},
            workspace_dir=workspace,
            on_output=received.append,
        )
        reader.start()
        reader.join(timeout=5)
        combined = b"".join(received)
        assert unsafe_begin in combined
        assert b"body bytes\n" in combined
        assert reader.state.active_step is None
        assert reader.state.steps_seen == []
        assert isinstance(reader.state.error, ValueError)
        assert not (workspace / "foo").exists()

    def test_dotdot_in_name_degrades_to_data(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        received = []
        unsafe_begin = b'\x1eECC-STEP {"v":1,"event":"begin","step":"..","tool":".."}\n'
        reader = LogStreamReader(
            io.BytesIO(unsafe_begin),
            log_path_resolver=lambda step, tool: workspace / "x" / "x.log",
            valid_steps={("..", "..")},
            workspace_dir=workspace,
            on_output=received.append,
        )
        reader.start()
        reader.join(timeout=5)
        assert b"".join(received) == unsafe_begin
        assert reader.state.active_step is None
        assert isinstance(reader.state.error, ValueError)

    def test_containment_violation_degrades_begin_to_data(self, tmp_path):
        """A begin whose archive escapes the workspace is forwarded as data."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        escape_target = tmp_path / "outside.log"
        received = []
        unsafe_begin = b'\x1eECC-STEP {"v":1,"event":"begin","step":"Escape","tool":"evil"}\n'
        stream_data = unsafe_begin + b"not archived\n"
        reader = LogStreamReader(
            io.BytesIO(stream_data),
            log_path_resolver=lambda step, tool: escape_target,
            valid_steps={("Escape", "evil")},
            workspace_dir=workspace,
            on_output=received.append,
        )
        reader.start()
        reader.join(timeout=5)
        combined = b"".join(received)
        assert unsafe_begin in combined
        assert b"not archived\n" in combined
        assert reader.state.active_step is None
        assert not escape_target.exists()
        assert "escapes workspace" in str(reader.state.error)


class TestStepLogArchiveResolver:
    def test_resolver_produces_canonical_step_log_path(self, tmp_path):
        from chipcompiler.runtime.log_stream import step_log_archive_resolver

        resolver = step_log_archive_resolver(tmp_path)
        assert resolver("Synthesis", "yosys") == (
            tmp_path / "Synthesis_yosys" / "log" / "Synthesis.log"
        )
        assert resolver("Floorplan", "ecc") == (
            tmp_path / "Floorplan_ecc" / "log" / "Floorplan.log"
        )


class TestOnStepEvent:
    def test_fires_on_matched_begin_and_end(self, tmp_path):
        events = []
        log_path = tmp_path / "step.log"
        stream_data = (
            b'\x1eECC-STEP {"v":1,"event":"begin","step":"S","tool":"T"}\n'
            b"data\n"
            b'\x1eECC-STEP {"v":1,"event":"end","step":"S","tool":"T"}\n'
        )
        reader = LogStreamReader(
            io.BytesIO(stream_data),
            log_path_resolver=lambda step, tool: log_path,
            on_step_event=lambda event, step, tool: events.append((event, step, tool)),
        )
        reader.start()
        reader.join(timeout=5)
        assert events == [("begin", "S", "T"), ("end", "S", "T")]

    def test_does_not_fire_on_unmatched_markers(self, tmp_path):
        events = []
        log_path = tmp_path / "step.log"
        nested_begin = b'\x1eECC-STEP {"v":1,"event":"begin","step":"B","tool":"T"}\n'
        mismatched_end = b'\x1eECC-STEP {"v":1,"event":"end","step":"X","tool":"T"}\n'
        stream_data = (
            b'\x1eECC-STEP {"v":1,"event":"begin","step":"A","tool":"T"}\n'
            + nested_begin
            + mismatched_end
            + b'\x1eECC-STEP {"v":1,"event":"end","step":"A","tool":"T"}\n'
        )
        reader = LogStreamReader(
            io.BytesIO(stream_data),
            log_path_resolver=lambda step, tool: log_path,
            on_step_event=lambda event, step, tool: events.append((event, step, tool)),
        )
        reader.start()
        reader.join(timeout=5)
        assert events == [("begin", "A", "T"), ("end", "A", "T")]

    def test_does_not_fire_on_disallowed_marker(self, tmp_path):
        events = []
        stream_data = b'\x1eECC-STEP {"v":1,"event":"begin","step":"Bogus","tool":"fake"}\n'
        reader = LogStreamReader(
            io.BytesIO(stream_data),
            on_step_event=lambda event, step, tool: events.append((event, step, tool)),
            valid_steps={("Real", "tool")},
        )
        reader.start()
        reader.join(timeout=5)
        assert events == []

    def test_callback_exception_disables_callback_continues_drain(self, tmp_path):
        log_path = tmp_path / "step.log"
        calls = [0]

        def failing_callback(event, step, tool):
            calls[0] += 1
            raise RuntimeError("step event exploded")

        stream_data = (
            b'\x1eECC-STEP {"v":1,"event":"begin","step":"S","tool":"T"}\n'
            b"line 1\n"
            b'\x1eECC-STEP {"v":1,"event":"end","step":"S","tool":"T"}\n'
            b'\x1eECC-STEP {"v":1,"event":"begin","step":"S2","tool":"T"}\n'
            b"line 2\n"
        )
        reader = LogStreamReader(
            io.BytesIO(stream_data),
            log_path_resolver=lambda step, tool: log_path,
            on_step_event=failing_callback,
        )
        reader.start()
        reader.join(timeout=5)
        assert reader.completed
        assert calls[0] == 1
        assert isinstance(reader.state.error, RuntimeError)
        # The second begin re-opened (truncated) the shared log path, so its
        # content proves archiving continued after the callback was disabled.
        assert log_path.read_bytes() == b"line 2\n"
