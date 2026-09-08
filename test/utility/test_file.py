import os
import stat

import pytest

from chipcompiler.utility.file import write_text_atomic


def test_write_text_atomic_replaces_content(tmp_path):
    target = tmp_path / "config.toml"
    target.write_text("old = 1\n")

    write_text_atomic(str(target), "new = 2\n")

    assert target.read_text() == "new = 2\n"
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".")] == []


def test_write_text_atomic_preserves_existing_mode(tmp_path):
    target = tmp_path / "ecc.toml"
    target.write_text("a = 1\n")
    os.chmod(target, 0o664)

    write_text_atomic(str(target), "a = 2\n")

    # mkstemp creates 0600; the replacement must not silently narrow a
    # shared config file's permissions.
    assert stat.S_IMODE(target.stat().st_mode) == 0o664


def test_write_text_atomic_new_file_gets_umask_default(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "umask", lambda mask: 0o022, raising=False)

    target = tmp_path / "new.toml"
    write_text_atomic(str(target), "a = 1\n")

    assert stat.S_IMODE(target.stat().st_mode) == 0o644


@pytest.mark.parametrize("broken_step", ["write", "replace"])
def test_write_text_atomic_failure_keeps_original(tmp_path, monkeypatch, broken_step):
    target = tmp_path / "ecc.toml"
    target.write_text("a = 1\n")

    if broken_step == "write":

        def broken_fdopen(*args, **kwargs):
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(os, "fdopen", broken_fdopen)
    else:

        def broken_replace(src, dst):
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(os, "replace", broken_replace)

    with pytest.raises(OSError):
        write_text_atomic(str(target), "a = 2\n")

    # The original content survives the failed write, and no temp litter or
    # truncated target is left behind.
    assert target.read_text() == "a = 1\n"
    assert [p.name for p in tmp_path.iterdir()] == ["ecc.toml"]
