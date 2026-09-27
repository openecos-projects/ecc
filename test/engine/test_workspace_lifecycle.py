import ctypes
import errno

from chipcompiler.engine.workspace_lifecycle import _exchange_directories


def test_exchange_directories_falls_back_when_nfs_rejects_rename_exchange(tmp_path, monkeypatch):
    left = tmp_path / "workspace"
    right = tmp_path / ".workspace.staging-test"
    left.mkdir()
    right.mkdir()
    (left / "identity").write_text("old")
    (right / "identity").write_text("new")

    class UnsupportedRenameExchange:
        @staticmethod
        def renameat2(*_args):
            ctypes.set_errno(errno.EINVAL)
            return -1

    monkeypatch.setattr(ctypes, "CDLL", lambda *_args, **_kwargs: UnsupportedRenameExchange())

    _exchange_directories(left, right)

    assert (left / "identity").read_text() == "new"
    assert (right / "identity").read_text() == "old"
    assert not (tmp_path / ".workspace.staging-test.exchange-old").exists()
