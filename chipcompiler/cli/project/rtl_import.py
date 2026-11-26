"""Import external RTL sources into a manifest project."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from chipcompiler.cli.project.toml_edit import set_scoped_key
from chipcompiler.project.manifest import CONFIG_FILENAME, MANIFEST_FILENAME
from chipcompiler.project.manifest_write import manifest_lock, update_manifest_locked
from chipcompiler.utility.file import write_text_atomic
from chipcompiler.utility.filelist import (
    _remove_inline_comment,
    parse_filelist,
    parse_incdir_directives,
)


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
    config_path = root / CONFIG_FILENAME
    if not config_path.is_file():
        raise RtlImportError("missing_config", "ecc.toml was not found", str(config_path))
    if not (root / MANIFEST_FILENAME).is_file():
        raise RtlImportError("missing_manifest", "project.json was not found", str(root))
    with manifest_lock(root):
        plan = plan_project_rtl(root, filelist=filelist, verilog=verilog)
        plan.copy(force=force)
        rtl_config, rtl_entries = plan.configured_paths, plan.rtl_entries

        text = config_path.read_text(encoding="utf-8")
        write_text_atomic(config_path, set_scoped_key(text, "design", "rtl", rtl_config))

        def mutate(document: dict) -> None:
            base = document.setdefault("base_design", {})
            base["rtl_list"] = rtl_entries
            base["origin_verilog"] = rtl_entries[0] if rtl_entries else ""
            if filelist:
                base["origin_filelist"] = rtl_config[0]
            document["design_name"] = document.get("design_name") or root.name

        update_manifest_locked(root, mutate)
    return {
        "project": str(root),
        "status": "rtl_imported",
        "filelist": rtl_config[0] if filelist else None,
        "rtl": rtl_entries,
        "include_dirs": [str(path.relative_to(root)) for path in plan.include_dirs.values()]
        or None,
    }


@dataclass(frozen=True)
class RtlImportPlan:
    copied: list[tuple[Path, Path]]
    source_list: Path | None
    configured_paths: list[str]
    rtl_entries: list[str]
    include_dirs: dict[Path, Path]

    @property
    def source_paths(self) -> list[str]:
        return (
            [str(self.source_list)]
            if self.source_list
            else [str(source) for source, _ in self.copied]
        )

    def copy(self, *, force: bool = False) -> None:
        _ensure_targets_available(self.copied, force=force)
        for source, target in self.copied:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        if self.source_list:
            _write_filelist(
                self.copied[0][1],
                self.source_list,
                self.copied[1 : 1 + len(self.rtl_entries)],
                self.include_dirs,
            )


def plan_project_rtl(
    root: Path,
    *,
    filelist: str | None = None,
    verilog: tuple[str, ...] = (),
    allow_dangling_links: bool = True,
) -> RtlImportPlan:
    if filelist and verilog:
        raise RtlImportError("rtl_inputs_exclusive", "use --filelist or --verilog, not both")

    targets = _RtlTargets(root / "rtl", allow_dangling_links)
    copied: list[tuple[Path, Path]] = []
    include_dirs: dict[Path, Path] = {}
    source_list: Path | None = None
    if filelist:
        source_list = Path(filelist).expanduser().resolve()
        if not source_list.is_file():
            raise RtlImportError("filelist_not_found", "filelist was not found", str(source_list))
        try:
            entries = parse_filelist(str(source_list))
        except (OSError, ValueError) as exc:
            raise RtlImportError("filelist_invalid", str(exc), str(source_list)) from exc
        if not entries:
            raise RtlImportError(
                "filelist_empty", "filelist contains no source files", str(source_list)
            )
        list_target = targets.for_source(source_list, source_list.parent)
        copied.append((source_list, list_target))
        for entry in entries:
            source = (source_list.parent / entry).resolve()
            if not source.is_file():
                raise RtlImportError(
                    "rtl_source_not_found", "filelist source was not found", str(source)
                )
            copied.append((source, targets.for_source(source, source_list.parent)))
        rtl_entries = [str(path.relative_to(root)) for _, path in copied[1:]]
        rtl_config = [str(list_target.relative_to(root))]
        include_dirs = _include_directories(source_list, targets)
        copied.extend(_include_files(include_dirs, root, targets, copied))
    else:
        if not verilog:
            raise RtlImportError("rtl_inputs_missing", "no RTL input was provided")
        for item in verilog:
            source = Path(item).expanduser().resolve()
            if not source.is_file():
                raise RtlImportError(
                    "rtl_source_not_found", "Verilog source was not found", str(source)
                )
            copied.append((source, targets.for_source(source, source.parent)))
        rtl_entries = [str(path.relative_to(root)) for _, path in copied]
        rtl_config = rtl_entries

    _validate_plan_targets(copied)
    return RtlImportPlan(copied, source_list, rtl_config, rtl_entries, include_dirs)


@dataclass(frozen=True)
class _RtlTargets:
    root: Path
    allow_dangling_links: bool

    def for_source(self, source: Path, base: Path) -> Path:
        relative = source.relative_to(base) if source.is_relative_to(base) else Path(source.name)
        return self.contained(self.root / relative, source)

    def contained(self, target: Path, source: Path) -> Path:
        resolved = target.resolve()
        if not resolved.is_relative_to(self.root):
            raise RtlImportError(
                "rtl_path_escape", "RTL target escapes project rtl directory", str(source)
            )
        if not self.allow_dangling_links and resolved != target:
            # A dangling link occupies its name even though its referent is absent.
            require_rtl_target_parents(target)
            if target.is_symlink() and not target.exists():
                raise FileExistsError(f"RTL target is a symbolic link: {target}")
        return resolved


def _include_directories(source_list: Path, layout: _RtlTargets) -> dict[Path, Path]:
    """Map each ``+incdir+`` directory of the filelist to its place below ``rtl/``.

    A directory below the filelist's own directory keeps its relative path,
    any other one (``../common``, an absolute path) is placed under ``rtl/``
    by its name - the rule the listed sources follow.
    """
    targets: dict[Path, Path] = {}
    for entry in parse_incdir_directives(str(source_list)):
        source_dir = (source_list.parent / entry).resolve()
        if source_dir in targets:
            continue
        if not source_dir.is_dir():
            raise RtlImportError(
                "rtl_incdir_not_found", "filelist include directory was not found", str(source_dir)
            )
        target = layout.for_source(source_dir, source_list.parent)
        if target in targets.values():
            raise RtlImportError(
                "rtl_target_collision",
                "multiple include directories map to the same target",
                str(target),
            )
        targets[source_dir] = target
    return targets


def _include_files(
    include_dirs: dict[Path, Path],
    project_root: Path,
    layout: _RtlTargets,
    copied: list[tuple[Path, Path]],
) -> list[tuple[Path, Path]]:
    """The files below the include directories that still have to be copied.

    Every file is taken, as workspace creation does for a filelist: an
    ``include`` may name a path below the directory. Files the filelist
    already lists, the project itself when it lies inside an include
    directory, and ``rtl/`` - the output of an earlier import, when the
    include directory is the project root - are left out. Each destination is
    checked like the target of a listed source: it has to stay below ``rtl/``.

    A directory link inside an include directory is followed, so a header
    included through the link is there after the import. A directory the
    walk has already entered on the way down is not entered again, however
    it is reached, so links that point at each other cannot make it loop.
    """
    known = set(copied)
    files: list[tuple[Path, Path]] = []
    for source_dir, target_dir in include_dirs.items():
        # The real directories entered on the way to each walked path.
        ancestry: dict[str, frozenset[Path]] = {
            str(source_dir): frozenset({Path(source_dir).resolve()})
        }
        for current, directories, names in os.walk(source_dir, followlinks=True):
            entered = ancestry.pop(current, frozenset({Path(current).resolve()}))
            kept = []
            for name in sorted(directories):
                resolved = (Path(current) / name).resolve()
                if resolved in (project_root, layout.root) or resolved in entered:
                    continue
                kept.append(name)
                ancestry[os.path.join(current, name)] = entered | {resolved}
            directories[:] = kept
            for name in sorted(names):
                source = Path(current) / name
                target = layout.contained(target_dir / source.relative_to(source_dir), source)
                pair = (source, target)
                if pair in known or source.resolve() == pair[1]:
                    continue
                known.add(pair)
                files.append(pair)
    return files


def require_rtl_target_parents(target: Path) -> None:
    """A target can only create directories through missing path components."""
    for parent in target.parents:
        if (parent.exists() or parent.is_symlink()) and not parent.is_dir():
            raise FileExistsError(f"RTL target parent is not a directory: {parent}")


def _validate_plan_targets(copied: list[tuple[Path, Path]]) -> set[Path]:
    targets: set[Path] = set()
    for _source, target in copied:
        if target in targets:
            raise RtlImportError(
                "rtl_target_collision", "multiple inputs map to the same target", str(target)
            )
        targets.add(target)
    # A file cannot be written where another input needs a directory: a listed
    # source named like an include directory would stop the copy half-way.
    for target in sorted(targets):
        if any(parent in targets for parent in target.parents):
            raise RtlImportError(
                "rtl_target_collision", "one input maps into the target of another", str(target)
            )
    return targets


def _ensure_targets_available(copied: list[tuple[Path, Path]], *, force: bool) -> None:
    targets = _validate_plan_targets(copied)
    for _source, target in copied:
        if target.exists() and not force:
            raise RtlImportError(
                "rtl_target_exists", "target exists; use --force to replace it", str(target)
            )
    for target in sorted(targets):
        try:
            require_rtl_target_parents(target)
        except FileExistsError as exc:
            raise RtlImportError("rtl_target_collision", str(exc), str(target)) from exc


def _write_filelist(
    target: Path,
    source_list: Path,
    sources: list[tuple[Path, Path]],
    include_dirs: dict[Path, Path],
) -> None:
    original = source_list.read_text(encoding="utf-8")
    replacements = {
        str(source): os.path.relpath(target_path, target.parent) for source, target_path in sources
    }
    lines = []
    for line in original.splitlines():
        stripped = line.strip().strip("\"'")
        if line.strip().startswith("+incdir+"):
            # Only the path is replaced, and only when it changes: quoting and
            # an inline comment stay as written.
            prefix, _, rest = line.partition("+incdir+")
            entry = _remove_inline_comment(rest).strip().strip("\"'")
            include_target = include_dirs.get((source_list.parent / entry).resolve())
            if entry and include_target is not None:
                local = os.path.relpath(include_target, target.parent)
                if local != os.path.normpath(entry):
                    line = f"{prefix}+incdir+{rest.replace(entry, local, 1)}"
        elif stripped and not stripped.startswith(("#", "//", "+", "-")):
            resolved = (source_list.parent / stripped).resolve()
            if str(resolved) in replacements:
                line = replacements[str(resolved)]
        lines.append(line)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
