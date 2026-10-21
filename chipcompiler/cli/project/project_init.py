"""Crash-consistent Project creation for ``ecc init``."""

import ctypes
import errno
import json
import os
import shutil
import stat
import tempfile
from copy import deepcopy
from pathlib import Path

from chipcompiler.cli.core.inputs import InitInput
from chipcompiler.project.manifest_write import build_project_document

_AT_FDCWD = -100
_RENAME_NOREPLACE = 1
_RENAME_EXCHANGE = 2
_MAX_MPC_SPEC_BYTES = 16 * 1024 * 1024
_RENAMEAT2_UNSUPPORTED_ERRNOS = frozenset(
    error
    for error in (
        errno.EINVAL,
        errno.ENOSYS,
        getattr(errno, "ENOTSUP", errno.EOPNOTSUPP),
        errno.EOPNOTSUPP,
        errno.EXDEV,
    )
)


class ProjectInitError(RuntimeError):
    def __init__(self, code: str, message: str, path: str | Path):
        super().__init__(message)
        self.code = code
        self.path = str(path)


def create_project(command_input: InitInput) -> Path:
    if not command_input.name or not command_input.name.strip():
        raise ProjectInitError("invalid_project", "Project path is required", command_input.name)
    target = Path(command_input.name).expanduser().absolute()
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)

    existing = _existing_empty_directory(target)
    default_name = target.name or "project"
    project_name = _nonempty(command_input.project_name, default_name, "Project name")
    design_name = _nonempty(command_input.design_name, default_name, "Design name")
    mpc = _load_mpc(command_input)

    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.staging-", dir=parent))
    published = False
    try:
        if existing is not None:
            os.chmod(staging, stat.S_IMODE(existing.st_mode))
        _populate(staging, target, project_name, design_name, mpc)
        try:
            if existing is None:
                _renameat2(staging, target, _RENAME_NOREPLACE)
            else:
                _verify_same_empty_directory(target, existing)
                _renameat2(staging, target, _RENAME_EXCHANGE)
        except OSError as exc:
            if exc.errno not in _RENAMEAT2_UNSUPPORTED_ERRNOS:
                raise
            _publish_without_renameat2(staging, target, existing)
        published = True
        _fsync_directory(parent)
    except ProjectInitError:
        raise
    except FileExistsError as exc:
        raise ProjectInitError("already_exists", "Project path already exists", target) from exc
    except OSError as exc:
        raise ProjectInitError("project_create_failed", str(exc), target) from exc
    finally:
        # After EXCHANGE, staging names the user's original empty directory.
        if staging.exists() and (published or not target.exists() or staging != target):
            shutil.rmtree(staging, ignore_errors=True)
    return target.resolve()


def _publish_without_renameat2(
    staging: Path, target: Path, existing: os.stat_result | None
) -> None:
    """Publish a project on filesystems that reject renameat2 flags.

    NFS commonly implements rename but rejects RENAME_NOREPLACE and
    RENAME_EXCHANGE with EINVAL. The fallback keeps the no-overwrite check at
    the directory boundary, then moves only the files ECC created. A failure
    restores moved entries and removes a newly-created target when possible.
    """
    created_target = existing is None
    moved: list[str] = []
    if created_target:
        try:
            target.mkdir(mode=stat.S_IMODE(staging.stat().st_mode))
        except FileExistsError as exc:
            raise ProjectInitError("already_exists", "Project path already exists", target) from exc
    else:
        _verify_same_empty_directory(target, existing)

    try:
        entries = sorted(staging.iterdir(), key=lambda entry: entry.name)
        for entry in entries:
            destination = target / entry.name
            if os.path.lexists(destination):
                raise ProjectInitError(
                    "already_exists",
                    "Project directory is no longer empty",
                    target,
                )
            os.rename(entry, destination)
            moved.append(entry.name)
        _fsync_directory(target)
    except BaseException:
        for name in reversed(moved):
            source = target / name
            destination = staging / name
            try:
                if os.path.lexists(source) and not os.path.lexists(destination):
                    os.rename(source, destination)
            except OSError:
                pass
        if created_target:
            try:
                if not os.listdir(target):
                    target.rmdir()
            except OSError:
                pass
        raise


def _existing_empty_directory(target: Path) -> os.stat_result | None:
    try:
        info = target.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise ProjectInitError("path_is_file", "Project path is not a real directory", target)
    try:
        next(target.iterdir())
    except StopIteration:
        return info
    raise ProjectInitError("already_exists", "Project directory is not empty", target)


def _verify_same_empty_directory(target: Path, expected: os.stat_result) -> None:
    descriptor = os.open(target, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        actual = os.fstat(descriptor)
        if (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino):
            raise ProjectInitError("project_path_changed", "Project directory changed", target)
        if os.listdir(descriptor):
            raise ProjectInitError("already_exists", "Project directory is no longer empty", target)
    finally:
        os.close(descriptor)


def _populate(
    staging: Path,
    target: Path,
    project_name: str,
    design_name: str,
    mpc: dict | None,
) -> None:
    rtl = staging / "rtl"
    constraints = staging / "constraints"
    rtl.mkdir()
    constraints.mkdir()
    config = _default_toml(design_name)
    _write_file(staging / "ecc.toml", config)
    base_design = {
        "pdk": "ics55",
        "top_module": design_name,
        "clock": "clk",
        "rtl_list": [f"rtl/{design_name}.v"],
        "origin_verilog": f"rtl/{design_name}.v",
        "parameters": {
            "design": design_name,
            "top_module": design_name,
            "clock": "clk",
            "frequency_max": 100.0,
        },
    }
    document = build_project_document(
        str(target.resolve()),
        design_name=design_name,
        base_design=base_design,
        name=project_name,
        mpc=mpc,
    )
    _write_file(
        staging / "project.json",
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
    )
    _fsync_directory(rtl)
    _fsync_directory(constraints)
    _fsync_directory(staging)


def _default_toml(design_name: str) -> str:
    return f'''[design]
name = "{design_name}"
top = "{design_name}"
rtl = ["rtl/{design_name}.v"]
clock_port = "clk"
frequency_mhz = 100.0

[pdk]
name = "ics55"
root = ""

[flow]
# preset: rtl2gds | syn_sta | synthesis_lec
preset = "rtl2gds"
# LEC is skipped by default; clear the list to enable it.
skip_steps = ["lec"]
'''


def _load_mpc(command_input: InitInput) -> dict | None:
    values = (
        command_input.mpc_resource_id,
        command_input.mpc_display_name,
        command_input.mpc_version,
        command_input.mpc_root,
        command_input.mpc_design_index,
    )
    if all(value is None for value in values):
        return None
    if any(value is None for value in values):
        raise ProjectInitError(
            "mpc_options_incomplete",
            "All MPC options must be provided together",
            command_input.name,
        )
    resource_id = str(command_input.mpc_resource_id).strip()
    display_name = str(command_input.mpc_display_name).strip()
    version = str(command_input.mpc_version).strip()
    if (
        not resource_id.startswith("mpc:")
        or resource_id == "mpc:"
        or not display_name
        or not version
    ):
        raise ProjectInitError("mpc_invalid", "Invalid MPC identity", command_input.mpc_root or "")
    root = Path(str(command_input.mpc_root)).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ProjectInitError("mpc_invalid", "MPC root is not a directory", root)
    spec_path = (root / "spec" / "spec.json.in").resolve(strict=True)
    if spec_path.parent.parent != root or not spec_path.is_file():
        raise ProjectInitError("mpc_invalid", "MPC spec path escapes its root", spec_path)
    if spec_path.stat().st_size > _MAX_MPC_SPEC_BYTES:
        raise ProjectInitError("mpc_invalid", "MPC spec is too large", spec_path)
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProjectInitError("mpc_invalid", f"Invalid MPC spec: {exc}", spec_path) from exc
    if not isinstance(spec, dict) or not isinstance(spec.get("designs"), list):
        raise ProjectInitError("mpc_invalid", "MPC spec must contain a designs array", spec_path)
    designs = spec["designs"]
    declared_count = spec.get("number")
    if declared_count is not None and (
        isinstance(declared_count, bool)
        or not isinstance(declared_count, int)
        or declared_count != len(designs)
    ):
        raise ProjectInitError("mpc_invalid", "MPC design count does not match", spec_path)
    for key, expected in (("resource_id", resource_id), ("version", version)):
        if key in spec and spec[key] != expected:
            raise ProjectInitError("mpc_invalid", f"MPC spec {key} does not match", spec_path)
    index = int(command_input.mpc_design_index)
    if index >= len(designs) or not isinstance(designs[index], dict):
        raise ProjectInitError("mpc_invalid", "MPC design index is invalid", spec_path)
    design = designs[index]
    core_template = design.get("core_template")
    if not isinstance(core_template, dict):
        raise ProjectInitError("mpc_invalid", "MPC design has no core_template object", spec_path)
    design_name = design.get("design_name")
    if not isinstance(design_name, str) or not design_name.strip():
        design_name = f"Design {index + 1}"
    design_snapshot: dict[str, object] = {"index": index, "design_name": design_name}
    directory = design.get("directory")
    if isinstance(directory, str) and directory.strip():
        design_snapshot["directory"] = directory
    return {
        "resource_id": resource_id,
        "display_name": display_name,
        "installed_version": version,
        "path": str(root),
        "spec_path": str(spec_path),
        "design": design_snapshot,
        "core_template": deepcopy(core_template),
    }


def _write_file(path: Path, content: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _renameat2(source: Path, target: Path, flags: int) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise OSError(errno.ENOSYS, "renameat2 is not available", target)
    result = renameat2(
        _AT_FDCWD,
        os.fsencode(source),
        _AT_FDCWD,
        os.fsencode(target),
        flags,
    )
    if result == 0:
        return
    error = ctypes.get_errno()
    if error == errno.EEXIST:
        raise FileExistsError(error, os.strerror(error), target)
    raise OSError(error, os.strerror(error), target)


def _nonempty(value: str | None, fallback: str, label: str) -> str:
    selected = fallback if value is None else value.strip()
    if not selected:
        raise ProjectInitError("invalid_project", f"{label} must not be empty", fallback)
    return selected
