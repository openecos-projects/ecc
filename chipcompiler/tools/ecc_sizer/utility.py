import os
import shutil
from pathlib import Path

_SIZER_RUNTIME_SENTINEL = Path("src") / "sizer_os.tcl"


def _is_sizer_root(path: Path) -> bool:
    return (path / _SIZER_RUNTIME_SENTINEL).is_file()


def _candidate_roots_from_binary(binary: str) -> list[Path]:
    resolved = Path(binary).expanduser().resolve()
    candidates: list[Path] = []
    seen: set[Path] = set()
    for parent in (resolved.parent, *resolved.parents):
        for candidate in (
            parent,
            parent / "share" / "ecc-sizer",
            parent / "share" / "sizer",
        ):
            if candidate not in seen:
                seen.add(candidate)
                candidates.append(candidate)
    return candidates


def find_sizer_root() -> Path | None:
    override = os.environ.get("CHIPCOMPILER_ECC_SIZER_ROOT", "").strip()
    candidates: list[Path] = []
    if override:
        candidates.append(Path(override).expanduser().resolve())

    command = get_sizer_command()
    if command:
        candidates.extend(_candidate_roots_from_binary(command[0]))

    for candidate in candidates:
        if _is_sizer_root(candidate):
            return candidate
    return None


def get_sizer_root() -> Path | None:
    return find_sizer_root()


def get_sizer_command() -> list[str]:
    sizer = shutil.which("Sizer")
    return [str(Path(sizer).resolve())] if sizer else []


def is_eda_exist() -> bool:
    return bool(get_sizer_command())


def is_sizer_runtime_exist() -> bool:
    return find_sizer_root() is not None
