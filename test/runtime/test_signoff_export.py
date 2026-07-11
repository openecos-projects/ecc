import queue
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from chipcompiler.runtime.requests import WorkspaceExportSignoffRequest
from chipcompiler.runtime.sessions import WorkspaceSessionRegistry
from chipcompiler.runtime.workspace_api import RuntimeApiError, WorkspaceRuntimeApi


def test_workspace_export_signoff_returns_exact_output_path(monkeypatch, tmp_path):
    workspace = SimpleNamespace(directory=tmp_path / "workspace")
    sessions = WorkspaceSessionRegistry()
    session = sessions.open_session(workspace.directory, workspace=workspace)
    output_path = tmp_path / "exports" / "custom name.tar.gz"
    calls = []

    def fake_export(active_workspace, requested_output):
        calls.append((active_workspace, requested_output))
        return str(output_path)

    monkeypatch.setattr(
        "chipcompiler.runtime.signoff_export.export_signoff_package_archive",
        fake_export,
    )
    api = WorkspaceRuntimeApi(sessions=sessions)

    result = api.export_signoff(
        WorkspaceExportSignoffRequest(
            workspace_id=session.workspace_id,
            output_path=str(output_path),
        )
    )

    assert result == {"outputPath": str(output_path)}
    assert calls == [(workspace, str(output_path))]


def test_workspace_export_signoff_waits_for_session_mutation_lock(monkeypatch, tmp_path):
    workspace = SimpleNamespace(directory=tmp_path / "workspace")
    sessions = WorkspaceSessionRegistry()
    session = sessions.open_session(workspace.directory, workspace=workspace)
    output_path = tmp_path / "export.tar.gz"
    entered = threading.Event()
    results = queue.Queue()

    def fake_export(_workspace, requested_output):
        entered.set()
        return requested_output

    monkeypatch.setattr(
        "chipcompiler.runtime.signoff_export.export_signoff_package_archive",
        fake_export,
    )
    api = WorkspaceRuntimeApi(sessions=sessions)

    def run_export():
        try:
            results.put(
                api.export_signoff(
                    WorkspaceExportSignoffRequest(
                        workspace_id=session.workspace_id,
                        output_path=str(output_path),
                    )
                )
            )
        except BaseException as error:  # pragma: no cover - re-raised below
            results.put(error)

    with session.mutation_lock:
        worker = threading.Thread(target=run_export)
        worker.start()
        assert not entered.wait(0.1)
        assert worker.is_alive()

    worker.join(timeout=2)
    assert not worker.is_alive()
    result = results.get_nowait()
    if isinstance(result, BaseException):
        raise result
    assert result == {"outputPath": str(output_path)}
    assert entered.is_set()


def test_export_signoff_package_archive_collects_temporarily_and_replaces_atomically(
    monkeypatch,
    tmp_path,
):
    from chipcompiler.runtime.signoff_export import export_signoff_package_archive

    output_path = tmp_path / "nested" / "chosen.tar.gz"
    captured_output_dirs = []

    class FakeFlow:
        def __init__(self, workspace):
            assert workspace == "workspace"

        def collect_signoff_package(self, options):
            captured_output_dirs.append(options.output_dir)
            archive = Path(options.output_dir) / "design_signoff_package.tar.gz"
            archive.write_bytes(b"archive")
            return SimpleNamespace(
                ok=True,
                archive_path=str(archive),
                missing_required=[],
            )

    monkeypatch.setattr(
        "chipcompiler.runtime.signoff_export.EngineFlow",
        FakeFlow,
    )

    result = export_signoff_package_archive("workspace", str(output_path))

    assert result == str(output_path.resolve())
    assert output_path.read_bytes() == b"archive"
    assert captured_output_dirs
    assert not Path(captured_output_dirs[0]).exists()
    assert not list(output_path.parent.glob(f".{output_path.name}.*"))


def test_export_signoff_package_archive_preserves_existing_target_on_incomplete_result(
    monkeypatch,
    tmp_path,
):
    from chipcompiler.runtime.signoff_export import export_signoff_package_archive

    output_path = tmp_path / "existing.tar.gz"
    output_path.write_bytes(b"old")

    class FakeFlow:
        def __init__(self, workspace):
            pass

        def collect_signoff_package(self, options):
            return SimpleNamespace(
                ok=False,
                archive_path=None,
                missing_required=["harden/design.gds", "harden/design.lef"],
            )

    monkeypatch.setattr(
        "chipcompiler.runtime.signoff_export.EngineFlow",
        FakeFlow,
    )

    with pytest.raises(RuntimeApiError) as exc_info:
        export_signoff_package_archive("workspace", str(output_path))

    assert exc_info.value.code == "command_failed"
    assert "harden/design.gds" in exc_info.value.message
    assert "harden/design.lef" in exc_info.value.message
    assert output_path.read_bytes() == b"old"


def test_export_signoff_package_archive_replaces_symlink_entry_not_target(
    monkeypatch,
    tmp_path,
):
    from chipcompiler.runtime.signoff_export import export_signoff_package_archive

    target = tmp_path / "target.tar.gz"
    target.write_bytes(b"target")
    output_path = tmp_path / "chosen.tar.gz"
    try:
        output_path.symlink_to(target.name)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable")

    class FakeFlow:
        def __init__(self, workspace):
            pass

        def collect_signoff_package(self, options):
            archive = Path(options.output_dir) / "archive.tar.gz"
            archive.write_bytes(b"new")
            return SimpleNamespace(ok=True, archive_path=str(archive), missing_required=[])

    monkeypatch.setattr(
        "chipcompiler.runtime.signoff_export.EngineFlow",
        FakeFlow,
    )

    export_signoff_package_archive("workspace", str(output_path))

    assert not output_path.is_symlink()
    assert output_path.read_bytes() == b"new"
    assert target.read_bytes() == b"target"
