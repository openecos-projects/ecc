import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "packaging" / "stamp_build_info.py"


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _repository(root: Path) -> str:
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "ECC Test")
    _git(root, "config", "user.email", "ecc-test@example.invalid")
    (root / "tracked.txt").write_text("clean\n", encoding="utf-8")
    _git(root, "add", "tracked.txt")
    _git(root, "commit", "-q", "-m", "initial")
    return _git(root, "rev-parse", "HEAD")


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_stamp_records_the_exact_clean_head(tmp_path):
    commit = _repository(tmp_path)

    completed = _run(tmp_path)

    assert completed.returncode == 0, completed.stderr
    stamp = (tmp_path / "chipcompiler" / "_build_info.py").read_text(encoding="utf-8")
    assert f'BUILD_COMMIT = "{commit}"' in stamp
    assert "BUILD_DATE = " in stamp


def test_stamp_rejects_tracked_changes(tmp_path):
    _repository(tmp_path)
    (tmp_path / "tracked.txt").write_text("modified\n", encoding="utf-8")

    completed = _run(tmp_path)

    assert completed.returncode != 0
    assert "tracked changes" in completed.stderr
    assert not (tmp_path / "chipcompiler" / "_build_info.py").exists()


def test_stamp_ignores_untracked_build_output(tmp_path):
    commit = _repository(tmp_path)
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "bundle").write_text("generated\n", encoding="utf-8")

    completed = _run(tmp_path)

    assert completed.returncode == 0, completed.stderr
    stamp = (tmp_path / "chipcompiler" / "_build_info.py").read_text(encoding="utf-8")
    assert f'BUILD_COMMIT = "{commit}"' in stamp
