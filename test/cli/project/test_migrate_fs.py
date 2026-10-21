import ctypes
import errno
import os

from chipcompiler.cli.project import migrate_fs


def _reject_renameat2(*_args):
    ctypes.set_errno(errno.EINVAL)
    return -1


def test_move_noreplace_falls_back_when_nfs_rejects_flags(tmp_path, monkeypatch):
    source_parent = tmp_path / "runs"
    destination_parent = tmp_path / "project"
    source = source_parent / "workspace"
    source.mkdir(parents=True)
    destination_parent.mkdir()
    (source / "identity").write_text("source")
    monkeypatch.setattr(migrate_fs, "_renameat2", _reject_renameat2)

    source_fd = os.open(source_parent, os.O_RDONLY | os.O_DIRECTORY)
    destination_fd = os.open(destination_parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        result = migrate_fs.move_noreplace(source_fd, "workspace", destination_fd, "workspace")
    finally:
        os.close(source_fd)
        os.close(destination_fd)

    assert result == 0
    assert not source.exists()
    assert (destination_parent / "workspace" / "identity").read_text() == "source"


def test_move_noreplace_fallback_preserves_an_existing_target(tmp_path, monkeypatch):
    source_parent = tmp_path / "runs"
    destination_parent = tmp_path / "project"
    source = source_parent / "workspace"
    target = destination_parent / "workspace"
    source.mkdir(parents=True)
    target.mkdir(parents=True)
    (source / "identity").write_text("source")
    (target / "identity").write_text("target")
    monkeypatch.setattr(migrate_fs, "_renameat2", _reject_renameat2)

    source_fd = os.open(source_parent, os.O_RDONLY | os.O_DIRECTORY)
    destination_fd = os.open(destination_parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        result = migrate_fs.move_noreplace(source_fd, "workspace", destination_fd, "workspace")
    finally:
        os.close(source_fd)
        os.close(destination_fd)

    assert result == errno.EEXIST
    assert (source / "identity").read_text() == "source"
    assert (target / "identity").read_text() == "target"
