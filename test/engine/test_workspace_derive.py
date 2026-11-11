import pytest

from chipcompiler.engine.workspace_derive import derive_workspace
from chipcompiler.engine.workspace_lifecycle import WorkspaceLifecycleError


def test_derive_rejects_existing_target(tmp_path):
    source = tmp_path / "source"
    (source / "home").mkdir(parents=True)
    (source / "home" / "engineering-snapshot.json").write_text("{}", encoding="utf-8")

    with pytest.raises(WorkspaceLifecycleError) as excinfo:
        derive_workspace(source, tmp_path)

    assert excinfo.value.code == "workspace_exists"


def test_derive_rejects_source_without_engineering_snapshot(tmp_path):
    source = tmp_path / "source"
    (source / "home").mkdir(parents=True)

    with pytest.raises(WorkspaceLifecycleError) as excinfo:
        derive_workspace(source, tmp_path / "target")

    assert excinfo.value.code == "workspace_invalid"


def test_derive_rejects_target_inside_source(tmp_path):
    source = tmp_path / "source"
    (source / "home").mkdir(parents=True)
    (source / "home" / "engineering-snapshot.json").write_text("{}", encoding="utf-8")

    with pytest.raises(WorkspaceLifecycleError) as excinfo:
        derive_workspace(source, source / "nested" / "target")

    assert excinfo.value.code == "workspace_invalid"
    assert not (source / "nested").exists()


def test_derive_no_wait_leaves_no_target_lock_when_source_busy(tmp_path):
    fcntl = pytest.importorskip("fcntl")
    # "child" sorts before "probe", so a sorted acquisition would create the
    # target lock file before discovering the busy source lock.
    source = tmp_path / "probe"
    (source / "home").mkdir(parents=True)
    (source / "home" / "engineering-snapshot.json").write_text("{}", encoding="utf-8")
    target = tmp_path / "child"

    with (tmp_path / "probe.lock").open("a") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX)
        with pytest.raises(BlockingIOError):
            derive_workspace(source, target, blocking=False)

    assert not (tmp_path / "child.lock").exists()
    assert not target.exists()
