import os
import shutil
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def get_sizer_root() -> Path:
    override = os.environ.get("CHIPCOMPILER_ECC_SIZER_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return _repo_root() / "chipcompiler" / "thirdparty" / "ecc-sizer"


def get_sizer_command() -> list[str]:
    for executable in ("sizer", "Sizer"):
        sizer = shutil.which(executable)
        if sizer:
            return [sizer]
    return []


def is_eda_exist() -> bool:
    return bool(get_sizer_command())
