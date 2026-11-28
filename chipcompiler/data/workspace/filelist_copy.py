#!/usr/bin/env python

"""Filelist freezing for workspace creation.

``copy_filelist_with_sources`` copies a filelist plus every referenced
source file and include directory into ``workspace/origin/``, preserving
the layout relative to the filelist for contained entries, anchoring
external (absolute or parent-relative ``..``) entries inside
``workspace/origin/`` with duplicate-basename disambiguation, and
rewriting those external entries so frozen runs never write outside or
depend on the original project tree.
"""

import os
import shutil
from pathlib import Path

from chipcompiler.utility.filelist import (
    _remove_inline_comment,
    parse_filelist,
    parse_incdir_directives,
    resolve_path,
)

_MAX_DISAMBIGUATION_SUFFIX = 99


def _contained_relative(entry: str, filelist_dir: Path) -> str | None:
    """Normalized relative path if *entry* stays within *filelist_dir*, else None."""
    if os.path.isabs(entry):
        return None
    norm = os.path.normpath(entry)
    if norm == ".." or norm.startswith(f"..{os.sep}"):
        return None
    resolved = (filelist_dir / norm).resolve()
    if not resolved.is_relative_to(filelist_dir):
        return None
    return norm


def _disambiguate_name(base_name: str, abs_path: str, taken: set[str], *, kind: str) -> str:
    """Return *base_name* if free in *taken*, else disambiguate via parent dir name."""
    if base_name not in taken:
        return base_name
    parent = os.path.basename(os.path.dirname(abs_path))
    candidate = f"{parent}_{base_name}" if parent else base_name
    suffix = 2
    while candidate in taken:
        candidate = f"{parent}_{suffix}_{base_name}" if parent else f"_{suffix}_{base_name}"
        suffix += 1
        if suffix > _MAX_DISAMBIGUATION_SUFFIX:
            raise ValueError(f"filelist {kind} collide on basename {base_name}: {abs_path}")
    return candidate


def copy_filelist_with_sources(input_filelist: str, workspace_dir: str, logger=None) -> str:
    """Copy a filelist and all referenced sources/incdirs into ``workspace_dir/origin/``."""
    origin_dir = os.path.join(workspace_dir, "origin")
    os.makedirs(origin_dir, exist_ok=True)
    origin_root = Path(origin_dir).resolve()

    filelist_base = os.path.dirname(os.path.abspath(input_filelist))
    filelist_dir = Path(input_filelist).resolve().parent
    copied_files: set[str] = set()
    rewritten_sources: dict[str, str] = {}
    rewritten_incdirs: dict[str, str] = {}
    stats = {"copied": 0, "missing": 0, "incdir_copied": 0, "incdir_skipped": 0}

    try:
        source_files = parse_filelist(input_filelist)
    except Exception as e:
        if logger:
            logger.error(f"Failed to parse filelist {input_filelist}: {e}")
        raise

    try:
        incdir_paths = parse_incdir_directives(input_filelist)
    except Exception as e:
        if logger:
            logger.warning(f"Failed to parse +incdir directives: {e}")
        incdir_paths = []

    reserved_in_tree = {
        c for p in source_files if (c := _contained_relative(p, filelist_dir)) is not None
    }
    reserved_incdir_roots = {
        c.split(os.sep, 1)[0]
        for p in incdir_paths
        if (c := _contained_relative(p, filelist_dir)) not in (None, ".")
    }

    for src_path in source_files:
        abs_src = resolve_path(src_path, filelist_base)
        norm_abs = os.path.normpath(abs_src)

        if not os.path.exists(norm_abs):
            if logger:
                logger.warning(f"File not found (skipping): {norm_abs}")
            stats["missing"] += 1
            continue

        contained = _contained_relative(src_path, filelist_dir)
        if contained is None:
            if norm_abs in rewritten_sources:
                if logger:
                    logger.debug(f"Skipping duplicate external source: {norm_abs}")
                continue
            base_name = os.path.basename(norm_abs)
            rel_path = _disambiguate_name(
                base_name,
                norm_abs,
                copied_files | reserved_in_tree,
                kind="sources",
            )
            if rel_path != base_name and logger:
                logger.info(f"Disambiguating duplicate basename: {norm_abs} -> {rel_path}")
        else:
            rel_path = contained
            if rel_path in copied_files:
                if logger:
                    logger.debug(f"Skipping duplicate: {rel_path}")
                continue

        dst_file = os.path.join(origin_dir, rel_path)
        if _copy_file_safely(norm_abs, dst_file, origin_root, logger, src_path):
            copied_files.add(rel_path)
            if contained is None:
                rewritten_sources[norm_abs] = rel_path
            stats["copied"] += 1

    for incdir_path in incdir_paths:
        abs_incdir = resolve_path(incdir_path, filelist_base)
        norm_abs = os.path.normpath(abs_incdir)

        if not os.path.exists(norm_abs):
            if logger:
                logger.warning(f"Include directory not found: {norm_abs}")
            continue

        if not os.path.isdir(norm_abs):
            if logger:
                logger.warning(f"Include path is not a directory: {norm_abs}")
            continue

        contained = _contained_relative(incdir_path, filelist_dir)
        incdir_anchor = ""
        if contained is None:
            if norm_abs in rewritten_incdirs:
                if logger:
                    logger.debug(f"Skipping duplicate external +incdir+: {norm_abs}")
                continue
            # Anchor external include dirs directly inside origin/ and never
            # merge distinct directories or shadow in-tree entries/dirs.
            base_name = os.path.basename(norm_abs.rstrip(os.sep))
            taken = (
                copied_files
                | reserved_in_tree
                | reserved_incdir_roots
                | set(rewritten_incdirs.values())
                | {p.split(os.sep, 1)[0] for p in copied_files | reserved_in_tree}
            )
            incdir_anchor = _disambiguate_name(
                base_name,
                norm_abs,
                taken,
                kind="include directories",
            )
            if incdir_anchor != base_name and logger:
                logger.info(f"Disambiguating include anchor: {norm_abs} -> {incdir_anchor}")
            rewritten_incdirs[norm_abs] = incdir_anchor

        for root, _dirs, files in os.walk(norm_abs):
            for filename in files:
                src_file = os.path.join(root, filename)
                rel_in_incdir = os.path.relpath(src_file, norm_abs)
                if contained is None:
                    rel_from_filelist = os.path.join(incdir_anchor, rel_in_incdir)
                else:
                    rel_from_filelist = os.path.normpath(os.path.join(contained, rel_in_incdir))

                if rel_from_filelist in copied_files:
                    stats["incdir_skipped"] += 1
                    if logger:
                        logger.debug(f"Skipping duplicate from +incdir: {rel_from_filelist}")
                    continue

                dst_file = os.path.join(origin_dir, rel_from_filelist)
                context = f"+incdir/{src_file}"
                if _copy_file_safely(src_file, dst_file, origin_root, logger, context):
                    copied_files.add(rel_from_filelist)
                    stats["incdir_copied"] += 1

    new_filelist = os.path.join(origin_dir, os.path.basename(input_filelist))
    try:
        shutil.copy2(input_filelist, new_filelist)
    except Exception as e:
        if logger:
            logger.error(f"Failed to copy filelist: {e}")
        raise

    if rewritten_sources or rewritten_incdirs:
        _rewrite_filelist_entries(
            new_filelist, filelist_base, rewritten_sources, logger, rewritten_incdirs
        )

    if logger:
        logger.info(
            f"Copied filelist and sources: "
            f"{stats['copied']} files from filelist, "
            f"{stats['incdir_copied']} files from +incdir, "
            f"{stats['missing']} missing, "
            f"{stats['incdir_skipped']} duplicates skipped"
        )

    return new_filelist


def _rewrite_filelist_entries(
    filelist_path: str,
    filelist_dir: str,
    rewritten_sources: dict[str, str],
    logger=None,
    rewritten_incdirs: dict[str, str] | None = None,
) -> None:
    """Point external (absolute or parent-relative) entries at frozen origin copies."""
    with open(filelist_path, encoding="utf-8") as f:
        lines = f.read().splitlines(keepends=True)

    incdirs = rewritten_incdirs or {}
    rewritten = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("+incdir+"):
            prefix, _, rest = line.partition("+incdir+")
            directive = _remove_inline_comment(rest).strip()
            include_path = directive.strip("\"'")
            if include_path:
                norm_abs = os.path.normpath(resolve_path(include_path, filelist_dir))
                mapped = incdirs.get(norm_abs)
                if mapped is not None:
                    line = f"{prefix}+incdir+{rest.replace(include_path, mapped, 1)}"
        elif stripped and not stripped.startswith(("+", "-", "#", "//", "`")):
            candidate = _remove_inline_comment(stripped).strip("\"'")
            if candidate:
                norm_abs = os.path.normpath(resolve_path(candidate, filelist_dir))
                mapped = rewritten_sources.get(norm_abs)
                if mapped is not None:
                    line = line.replace(candidate, mapped, 1)
        rewritten.append(line)

    with open(filelist_path, "w", encoding="utf-8") as f:
        f.writelines(rewritten)
    if logger:
        logger.info(
            f"Rewrote {len(rewritten_sources)} external source entries "
            f"and {len(incdirs)} include dirs to frozen sources"
        )


def _copy_file_safely(
    src: str,
    dst: str,
    origin_root: Path,
    logger,
    context: str,
) -> bool:
    """Copy *src* to *dst*, rejecting any destination outside *origin_root*."""
    resolved_dst = Path(dst).resolve()
    if not resolved_dst.is_relative_to(origin_root):
        raise ValueError(f"Refusing to copy filelist entry outside workspace origin: {context}")
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        if logger:
            logger.debug(f"Copied: {src} -> {dst}")
        return True
    except OSError as e:
        if logger:
            logger.error(f"Error copying {context}: {e}")
        return False
