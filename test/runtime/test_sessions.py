from pathlib import Path

import pytest

from chipcompiler.runtime.sessions import WorkspaceSessionNotFound, WorkspaceSessionRegistry


def test_create_session_returns_workspace_id_and_resolved_directory(tmp_path):
    registry = WorkspaceSessionRegistry()
    workspace = object()

    session = registry.create_session(tmp_path / "ws", workspace=workspace)

    assert session.workspace_id.startswith("workspace-")
    assert session.directory == (tmp_path / "ws").resolve()
    assert session.workspace is workspace
    assert session.db_handle is None


def test_open_reuses_existing_session_for_same_directory(tmp_path):
    registry = WorkspaceSessionRegistry()

    first = registry.open_session(tmp_path / "ws", workspace="first")
    second = registry.open_session(Path(tmp_path / "ws"), workspace="second")

    assert second.workspace_id == first.workspace_id
    assert second.workspace == "first"


def test_get_session_rejects_unknown_and_closed_workspace_id(tmp_path):
    registry = WorkspaceSessionRegistry()
    session = registry.open_session(tmp_path / "ws", workspace=object())

    registry.close_session(session.workspace_id)

    with pytest.raises(WorkspaceSessionNotFound, match=session.workspace_id):
        registry.get_session(session.workspace_id)
    with pytest.raises(WorkspaceSessionNotFound, match="missing"):
        registry.get_session("missing")


def test_close_session_releases_reserved_db_slot(tmp_path):
    registry = WorkspaceSessionRegistry()
    session = registry.open_session(tmp_path / "ws", workspace=object())
    session.db_handle = object()

    registry.close_session(session.workspace_id)

    assert session.db_handle is None


def test_per_session_lock_serializes_mutating_commands(tmp_path):
    registry = WorkspaceSessionRegistry()
    session = registry.open_session(tmp_path / "ws", workspace=object())

    with session.mutation_lock:
        assert not session.mutation_lock.acquire(blocking=False)
