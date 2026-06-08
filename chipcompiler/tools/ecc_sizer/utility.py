import os
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def get_sizer_root() -> Path:
    override = os.environ.get("CHIPCOMPILER_ECC_SIZER_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return _repo_root() / "chipcompiler" / "thirdparty" / "ecc-sizer"


def get_sizer_command() -> list[str]:
    override = os.environ.get("CHIPCOMPILER_ECC_SIZER_BIN", "").strip()
    if override:
        return [str(Path(override).expanduser().resolve())]

    installed = _repo_root() / "chipcompiler" / "tools" / "ecc_sizer" / "bin" / "Sizer"
    if installed.exists():
        return [str(installed)]

    return [str(get_sizer_root() / "build" / "src" / "Sizer")]


def is_eda_exist() -> bool:
    command = get_sizer_command()
    return bool(command and os.path.isfile(command[0]) and os.access(command[0], os.X_OK))
