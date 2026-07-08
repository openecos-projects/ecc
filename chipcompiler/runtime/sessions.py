from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class WorkspaceSession:
    workspace_id: str
    directory: Path
    workspace: Any
    db_handle: Any = None
    mutation_lock: threading.Lock = field(default_factory=threading.Lock)


class WorkspaceSessionNotFound(KeyError):
    pass


def _close_db_handle(db_handle: Any) -> None:
    close = getattr(db_handle, "close", None)
    if callable(close):
        close()


class WorkspaceSessionRegistry:
    def __init__(self, db_releaser: Callable[[Any], None] | None = _close_db_handle):
        self._next_id = 1
        self._sessions: dict[str, WorkspaceSession] = {}
        self._sessions_by_directory: dict[Path, str] = {}
        self._db_releaser = db_releaser
        self._lock = threading.Lock()

    def create_session(self, directory: str | Path, *, workspace: Any) -> WorkspaceSession:
        resolved_directory = Path(directory).resolve()
        with self._lock:
            existing_id = self._sessions_by_directory.get(resolved_directory)
            if existing_id is not None:
                self._remove_session(existing_id)
            return self._create_session(resolved_directory, workspace=workspace)

    def open_session(self, directory: str | Path, *, workspace: Any) -> WorkspaceSession:
        resolved_directory = Path(directory).resolve()
        with self._lock:
            existing_id = self._sessions_by_directory.get(resolved_directory)
            if existing_id is not None:
                return self._sessions[existing_id]

            return self._create_session(resolved_directory, workspace=workspace)

    def get_session(self, workspace_id: str) -> WorkspaceSession:
        try:
            return self._sessions[workspace_id]
        except KeyError as exc:
            raise WorkspaceSessionNotFound(workspace_id) from exc

    def close_session(self, workspace_id: str) -> None:
        with self._lock:
            self._remove_session(workspace_id)

    def close_all(self) -> None:
        with self._lock:
            for session in self._sessions.values():
                self._release_session_db(session)
            self._sessions.clear()
            self._sessions_by_directory.clear()

    def release_session_db(self, session: WorkspaceSession) -> bool:
        return self._release_session_db(session)

    def _create_session(self, directory: Path, *, workspace: Any) -> WorkspaceSession:
        workspace_id = f"workspace-{self._next_id}"
        self._next_id += 1
        session = WorkspaceSession(
            workspace_id=workspace_id,
            directory=directory,
            workspace=workspace,
        )
        self._sessions[workspace_id] = session
        self._sessions_by_directory[directory] = workspace_id
        return session

    def _remove_session(self, workspace_id: str) -> None:
        session = self._sessions.pop(workspace_id, None)
        if session is None:
            raise WorkspaceSessionNotFound(workspace_id)
        self._release_session_db(session)
        self._sessions_by_directory.pop(session.directory, None)

    def _release_session_db(self, session: WorkspaceSession) -> bool:
        db_handle = session.db_handle
        if db_handle is None:
            return False

        session.db_handle = None
        if self._db_releaser is not None:
            self._db_releaser(db_handle)
        return True
