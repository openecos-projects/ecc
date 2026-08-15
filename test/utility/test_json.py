import gzip
import json
import os
import stat

import pytest

from chipcompiler.data import Workspace
from chipcompiler.data.workspace.layout import EccStep
from chipcompiler.utility.json import JsonReadError, json_read, json_read_strict, json_write


class Unserializable:
    pass


def test_json_write_keeps_existing_file_when_normal_json_dump_fails(tmp_path):
    path = tmp_path / "data.json"
    path.write_text(json.dumps({"existing": True}))

    assert json_write(path, {"bad": Unserializable()}) is False

    assert json.loads(path.read_text()) == {"existing": True}
    assert list(tmp_path.iterdir()) == [path]


def test_json_write_preserves_existing_file_mode(tmp_path):
    path = tmp_path / "data.json"
    path.write_text(json.dumps({"existing": True}))
    path.chmod(0o664)

    assert json_write(path, {"updated": True})

    assert stat.S_IMODE(path.stat().st_mode) == 0o664
    assert json.loads(path.read_text()) == {"updated": True}


def test_json_write_preserves_symlink_and_updates_target(tmp_path):
    target = tmp_path / "target.json"
    link = tmp_path / "link.json"
    target.write_text(json.dumps({"existing": True}))
    link.symlink_to(target)

    assert json_write(link, {"updated": True})

    assert link.is_symlink()
    assert link.resolve() == target
    assert json.loads(target.read_text()) == {"updated": True}


def test_json_read_accepts_path_input(tmp_path):
    path = tmp_path / "data.json"
    path.write_text(json.dumps({"value": 1}))

    assert json_read(path) == {"value": 1}


def test_json_write_accepts_path_input(tmp_path):
    path = tmp_path / "data.json"

    assert json_write(path, {"value": 1})

    assert json.loads(path.read_text()) == {"value": 1}


def test_json_read_accepts_gz_path_input(tmp_path):
    path = tmp_path / "data.json.gz"
    with gzip.open(path, "wt") as f:
        json.dump({"value": 1}, f)

    assert json_read(path) == {"value": 1}


def test_json_write_accepts_gz_path_input(tmp_path):
    path = tmp_path / "data.json.gz"

    assert json_write(path, {"value": 1})

    with gzip.open(path, "rt") as f:
        assert json.load(f) == {"value": 1}


# --- Phase 2: Silent failure regression tests ---


class TestJsonReadStrict:
    """Tests for json_read_strict — mandatory JSON file reading."""

    def test_returns_valid_empty_json(self, tmp_path):
        path = tmp_path / "empty.json"
        path.write_text("{}")
        assert json_read_strict(path) == {}

    def test_returns_valid_nonempty_json(self, tmp_path):
        path = tmp_path / "data.json"
        path.write_text(json.dumps({"key": "value"}))
        assert json_read_strict(path) == {"key": "value"}

    def test_raises_on_missing_file(self, tmp_path):
        path = tmp_path / "nonexistent.json"
        with pytest.raises(FileNotFoundError, match="not found"):
            json_read_strict(path)

    def test_raises_on_invalid_json(self, tmp_path):
        path = tmp_path / "corrupt.json"
        path.write_text("{invalid json content")
        with pytest.raises(JsonReadError, match="Invalid JSON"):
            json_read_strict(path)

    @pytest.mark.skipif(os.getuid() == 0, reason="root bypasses file permissions")
    def test_raises_on_io_error(self, tmp_path):
        path = tmp_path / "unreadable.json"
        path.write_text("{}")
        path.chmod(0o000)
        try:
            with pytest.raises(JsonReadError, match="Failed to read"):
                json_read_strict(path)
        finally:
            path.chmod(0o644)

    def test_distinguishes_empty_from_missing(self, tmp_path):
        empty = tmp_path / "empty.json"
        empty.write_text("{}")
        assert json_read_strict(empty) == {}

        missing = tmp_path / "missing.json"
        with pytest.raises(FileNotFoundError):
            json_read_strict(missing)

    def test_read_still_returns_empty_dict_for_missing(self, tmp_path):
        """json_read backward compatibility: missing file returns {}."""
        path = tmp_path / "nonexistent.json"
        assert json_read(path) == {}

    def test_read_still_returns_empty_dict_for_corrupt(self, tmp_path):
        """json_read backward compatibility: corrupt file returns {}."""
        path = tmp_path / "corrupt.json"
        path.write_text("{bad")
        assert json_read(path) == {}


class TestJsonWriteFailureLogging:
    """Tests for json_write failure behavior."""

    def test_returns_false_on_write_failure(self, tmp_path):
        path = tmp_path / "readonly" / "data.json"
        # Parent directory doesn't exist and can't be created in read-only context
        assert json_write(path, {"key": "value"}) is False

    def test_returns_true_on_success(self, tmp_path):
        path = tmp_path / "data.json"
        assert json_write(path, {"key": "value"}) is True


class TestFlowSetStatePersistence:
    """Tests for EngineFlow.set_state json_write failure handling."""

    def test_set_state_updates_in_memory_when_save_fails(self, tmp_path, monkeypatch):
        from chipcompiler.engine.flow import EngineFlow
        from chipcompiler.data import StateEnum

        flow_path = tmp_path / "flow.json"
        flow_path.write_text(json.dumps({
            "steps": [{"name": "SYNTHESIS", "tool": "yosys", "state": "Unstart"}]
        }))

        workspace = type("MockWorkspace", (), {
            "flow": type("Flow", (), {"path": flow_path, "data": json.loads(flow_path.read_text())})(),
            "logger": type("Logger", (), {
                "error": lambda self, *a, **kw: None,
                "info": lambda self, *a, **kw: None,
                "warning": lambda self, *a, **kw: None,
                "log_section": lambda self, *a: None,
            })(),
        })()

        flow = EngineFlow.__new__(EngineFlow)
        flow.workspace = workspace
        flow.workspace_steps = []

        monkeypatch.setattr("chipcompiler.utility.json_write", lambda *a, **kw: False)

        result = flow.set_state("SYNTHESIS", "yosys", StateEnum.Success)
        assert result is True
        # In-memory state is updated
        assert workspace.flow.data["steps"][0]["state"] == StateEnum.Success.value

    def test_stale_file_causes_rerun_on_resume(self, tmp_path, monkeypatch):
        """When save() fails, file stays stale; a fresh resume load sees stale state."""
        from chipcompiler.engine.flow import EngineFlow
        from chipcompiler.data import StateEnum
        from chipcompiler.engine import rerun

        flow_path = tmp_path / "flow.json"
        flow_data = {
            "steps": [
                {"name": "SYNTHESIS", "tool": "yosys", "state": "Unstart"},
                {"name": "FLOORPLAN", "tool": "ecc", "state": "Unstart"},
            ]
        }
        flow_path.write_text(json.dumps(flow_data))

        # First run: mark SYNTHESIS as Success but save fails
        workspace = Workspace(directory=tmp_path)
        workspace.flow.path = flow_path
        workspace.flow.data = json.loads(json.dumps(flow_data))
        engine_flow = EngineFlow(workspace)
        engine_flow.workspace_steps = [
            EccStep(name="SYNTHESIS", directory=tmp_path, tool="yosys"),
            EccStep(name="FLOORPLAN", directory=tmp_path, tool="ecc"),
        ]
        monkeypatch.setattr("chipcompiler.utility.json_write", lambda *a, **kw: False)
        engine_flow.set_state("SYNTHESIS", "yosys", StateEnum.Success)
        # File is still Unstart (save failed)

        # Simulate resume: fresh load from disk (what production does)
        workspace2 = Workspace(directory=tmp_path)
        workspace2.flow.path = flow_path
        engine_flow2 = EngineFlow(workspace2)
        # workspace2.flow.data was loaded from stale file
        selected = rerun.selected_step_names(engine_flow2)
        assert "SYNTHESIS" in selected
        assert "FLOORPLAN" in selected

    def test_persisted_success_skips_on_resume(self, tmp_path):
        """When save() succeeds, resume correctly skips successful steps."""
        from chipcompiler.engine.flow import EngineFlow
        from chipcompiler.data import StateEnum
        from chipcompiler.engine import rerun

        flow_path = tmp_path / "flow.json"
        flow_data = {
            "steps": [
                {"name": "SYNTHESIS", "tool": "yosys", "state": "Unstart"},
                {"name": "FLOORPLAN", "tool": "ecc", "state": "Unstart"},
            ]
        }
        flow_path.write_text(json.dumps(flow_data))

        workspace = Workspace(directory=tmp_path)
        workspace.flow.path = flow_path
        workspace.flow.data = json.loads(json.dumps(flow_data))

        engine_flow = EngineFlow(workspace)

        # Mark SYNTHESIS as Success — save() succeeds
        engine_flow.set_state("SYNTHESIS", "yosys", StateEnum.Success)

        # Verify file was updated
        persisted = json.loads(flow_path.read_text())
        assert persisted["steps"][0]["state"] == StateEnum.Success.value

        # resume: only FLOORPLAN should be selected
        selected = rerun.selected_step_names(engine_flow)
        assert selected == ["FLOORPLAN"]
