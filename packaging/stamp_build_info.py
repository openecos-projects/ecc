"""Write the build identity consumed by packaged ECC bundles."""

from __future__ import annotations

import argparse
import subprocess
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
STAMP_PATH = Path("chipcompiler") / "_build_info.py"


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def stamp(root: Path = REPOSITORY_ROOT, *, now: datetime | None = None) -> tuple[str, str]:
    """Stamp the exact clean checkout revision into the package source."""
    root = root.resolve()
    if _git(root, "status", "--porcelain", "--untracked-files=no"):
        raise RuntimeError("Refusing to stamp a build from a checkout with tracked changes")
    commit = _git(root, "rev-parse", "HEAD")
    build_date = (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y%m%d")
    destination = root / STAMP_PATH
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".py.tmp")
    temporary.write_text(
        f'BUILD_COMMIT = "{commit}"\nBUILD_DATE = "{build_date}"\n',
        encoding="utf-8",
    )
    temporary.replace(destination)
    return commit, build_date


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPOSITORY_ROOT)
    arguments = parser.parse_args(argv)
    commit, build_date = stamp(arguments.root)
    print(f"Stamped build identity: {commit} ({build_date})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
