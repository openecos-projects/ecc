"""Import external RTL sources into a manifest project."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from chipcompiler.cli.project.toml_edit import set_scoped_key
from chipcompiler.project.manifest_write import update_manifest
from chipcompiler.utility.filelist import parse_filelist


class RtlImportError(RuntimeError):
    def __init__(self, code: str, message: str, path: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.path = path


def import_project_rtl(
    project_dir: str,
    *,
    filelist: str | None = None,
    verilog: tuple[str, ...] = (),
    force: bool = False,
) -> dict:
    root = Path(project_dir).resolve()
    config_path = root / "ecc.toml"
    if not config_path.is_file():
        raise RtlImportError("missing_config", "ecc.toml was not found", str(config_path))
    if not (root / "project.json").is_file():
        raise RtlImportError("missing_manifest", "project.json was not found", str(root))
    if filelist and verilog:
        raise RtlImportError("rtl_inputs_exclusive", "use --filelist or --verilog, not both")

    rtl_root = root / "rtl"
    rtl_root.mkdir(exist_ok=True)
    copied: list[tuple[Path, Path]] = []
    if filelist:
        source_list = Path(filelist).expanduser().resolve()
        if not source_list.is_file():
            raise RtlImportError("filelist_not_found", "filelist was not found", str(source_list))
        try:
            entries = parse_filelist(str(source_list))
        except (OSError, ValueError) as exc:
            raise RtlImportError("filelist_invalid", str(exc), str(source_list)) from exc
        if not entries:
            raise RtlImportError("filelist_empty", "filelist contains no source files", str(source_list))
        list_target = _target_for(source_list, source_list.parent, rtl_root)
        copied.append((source_list, list_target))
        for entry in entries:
            source = (source_list.parent / entry).resolve()
            if not source.is_file():
                raise RtlImportError("rtl_source_not_found", "filelist source was not found", str(source))
            copied.append((source, _target_for(source, source_list.parent, rtl_root)))
        rtl_entries = [str(path.relative_to(root)) for _, path in copied[1:]]
        rtl_config = [str(list_target.relative_to(root))]
    else:
        if not verilog:
            raise RtlImportError("rtl_inputs_missing", "no RTL input was provided")
        for item in verilog:
            source = Path(item).expanduser().resolve()
            if not source.is_file():
                raise RtlImportError("rtl_source_not_found", "Verilog source was not found", str(source))
            copied.append((source, _target_for(source, source.parent, rtl_root)))
        rtl_entries = [str(path.relative_to(root)) for _, path in copied]
        rtl_config = rtl_entries

    _ensure_targets_available(copied, force)
    for source, target in copied:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    if filelist:
        _write_filelist(copied[0][1], source_list, copied[1:])

    text = config_path.read_text(encoding="utf-8")
    text = set_scoped_key(text, "design", "rtl", rtl_config)
    config_path.write_text(text, encoding="utf-8")

    def mutate(document: dict) -> None:
        base = document.setdefault("base_design", {})
        base["rtl_list"] = rtl_entries
        base["origin_verilog"] = rtl_entries[0] if rtl_entries else ""
        if filelist:
            base["origin_filelist"] = rtl_config[0]
        document["design_name"] = document.get("design_name") or root.name

    update_manifest(root, mutate)
    return {
        "project": str(root),
        "status": "rtl_imported",
        "filelist": rtl_config[0] if filelist else None,
        "rtl": rtl_entries,
    }


def _target_for(source: Path, base: Path, rtl_root: Path) -> Path:
    try:
        relative = source.relative_to(base)
    except ValueError:
        relative = Path(source.name)
    target = (rtl_root / relative).resolve()
    if target != rtl_root and rtl_root not in target.parents:
        raise RtlImportError("rtl_path_escape", "RTL target escapes project rtl directory", str(source))
    return target


def _ensure_targets_available(copied: list[tuple[Path, Path]], force: bool) -> None:
    targets = set()
    for source, target in copied:
        if target in targets:
            raise RtlImportError("rtl_target_collision", "multiple inputs map to the same target", str(target))
        targets.add(target)
        if target.exists() and not force:
            raise RtlImportError("rtl_target_exists", "target exists; use --force to replace it", str(target))


def _write_filelist(target: Path, source_list: Path, sources: list[tuple[Path, Path]]) -> None:
    original = source_list.read_text(encoding="utf-8")
    replacements = {
        str(source): os.path.relpath(target_path, target.parent)
        for source, target_path in sources
    }
    lines = []
    for line in original.splitlines():
        stripped = line.strip().strip("\"'")
        if stripped and not stripped.startswith(("#", "//", "+", "-")):
            resolved = (source_list.parent / stripped).resolve()
            if str(resolved) in replacements:
                line = replacements[str(resolved)]
        lines.append(line)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
