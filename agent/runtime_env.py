"""Process environment preparation for the opt-in Agent runtime."""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_SIZER_EXECUTABLES = (
    Path("bin") / "Sizer",
    Path("build") / "src" / "Sizer",
    Path("build") / "Sizer",
    Path("Sizer"),
)


def _packaged_sizer_executable() -> Path | None:
    root_value = os.environ.get("CHIPCOMPILER_ECC_SIZER_ROOT", "").strip()
    if not root_value:
        return None

    root = Path(root_value).expanduser()
    return next(
        (
            candidate.resolve()
            for relative in _SIZER_EXECUTABLES
            if (candidate := root / relative).is_file() and os.access(candidate, os.X_OK)
        ),
        None,
    )


def prepare_agent_runtime_environment() -> None:
    executable = _packaged_sizer_executable()
    if executable is None:
        return

    binary_dir = str(executable.parent)
    path_entries = os.environ.get("PATH", "").split(os.pathsep)
    if binary_dir not in path_entries:
        os.environ["PATH"] = os.pathsep.join((binary_dir, *filter(None, path_entries)))


@contextmanager
def isolated_sizer_loader_environment() -> Iterator[None]:
    if _packaged_sizer_executable() is None:
        yield
        return

    names = ("LD_LIBRARY_PATH", "LD_PRELOAD")
    previous = {name: os.environ.pop(name, None) for name in names}
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is not None:
                os.environ[name] = value
            else:
                os.environ.pop(name, None)
