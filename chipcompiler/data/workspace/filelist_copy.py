#!/usr/bin/env python

"""Filelist freezing for workspace creation.

``copy_filelist_with_sources`` copies a filelist plus every referenced
source file and include directory into ``workspace/origin/``, preserving
the layout relative to the filelist, disambiguating duplicate basenames
instead of silently dropping sources, and rewriting absolute entries to
point at the frozen copies so a later run never depends on the original
project tree.
"""

import os
import shutil

from chipcompiler.utility.filelist import (
    _remove_inline_comment,
    parse_filelist,
    parse_incdir_directives,
    resolve_path,
)


def copy_filelist_with_sources(input_filelist: str, workspace_dir: str, logger=None) -> str:
    """
    Copy filelist and all referenced source files + include directories to workspace/origin/.

    Maintains the original directory structure of source files relative to the filelist location.
    Supports +incdir directives with smart deduplication.

    Args:
        input_filelist: Path to the filelist file
        workspace_dir: Target workspace directory
        logger: Optional logger instance for logging operations

    Returns:
        Path to the copied filelist in workspace/origin/

    Raises:
        FileNotFoundError: If filelist file doesn't exist
        IOError: If file copy operations fail

    Example:
        >>> new_filelist_path = copy_filelist_with_sources(
        ...     "/project/design.f",
        ...     "/workspace/gcd"
        ... )
        >>> print(new_filelist_path)
        '/workspace/gcd/origin/design.f'
    """
    origin_dir = os.path.join(workspace_dir, "origin")
    os.makedirs(origin_dir, exist_ok=True)

    filelist_dir = os.path.dirname(os.path.abspath(input_filelist))
    copied_files = set()
    copied_abs_sources: dict[str, str] = {}
    stats = {"copied": 0, "missing": 0, "incdir_copied": 0, "incdir_skipped": 0}

    # Copy files listed in filelist
    try:
        source_files = parse_filelist(input_filelist)
    except Exception as e:
        if logger:
            logger.error(f"Failed to parse filelist {input_filelist}: {e}")
        raise

    for src_path in source_files:
        abs_src = resolve_path(src_path, filelist_dir)

        if not os.path.exists(abs_src):
            if logger:
                logger.warning(f"File not found (skipping): {abs_src}")
            stats["missing"] += 1
            continue

        rel_path = os.path.basename(src_path) if os.path.isabs(src_path) else src_path

        if rel_path in copied_files:
            same_source = os.path.normpath(abs_src) in copied_abs_sources
            if not os.path.isabs(src_path) or same_source:
                if logger:
                    logger.debug(f"Skipping duplicate: {rel_path}")
                continue
            # Two different absolute sources sharing a basename: keep both
            # by anchoring the destination with the immediate parent
            # directory, walking up until the name is unique. A filelist
            # that still collides after that is rejected rather than
            # silently frozen with a dangling external reference.
            parent = os.path.basename(os.path.dirname(abs_src))
            disambiguated = f"{parent}_{rel_path}" if parent else rel_path
            suffix = 2
            while disambiguated in copied_files:
                disambiguated = (
                    f"{parent}_{suffix}_{rel_path}" if parent else f"_{suffix}_{rel_path}"
                )
                suffix += 1
                if suffix > 99:
                    raise ValueError(f"filelist sources collide on basename {rel_path}: {abs_src}")
            if logger:
                logger.info(f"Disambiguating duplicate basename: {abs_src} -> {disambiguated}")
            rel_path = disambiguated

        if _copy_file_safely(abs_src, os.path.join(origin_dir, rel_path), logger, src_path):
            copied_files.add(rel_path)
            if os.path.isabs(src_path):
                copied_abs_sources[os.path.normpath(abs_src)] = rel_path
            stats["copied"] += 1

    # Copy +incdir directories
    try:
        incdir_paths = parse_incdir_directives(input_filelist)
    except Exception as e:
        if logger:
            logger.warning(f"Failed to parse +incdir directives: {e}")
        incdir_paths = []

    for incdir_path in incdir_paths:
        abs_incdir = resolve_path(incdir_path, filelist_dir)

        if not os.path.exists(abs_incdir):
            if logger:
                logger.warning(f"Include directory not found: {abs_incdir}")
            continue

        if not os.path.isdir(abs_incdir):
            if logger:
                logger.warning(f"Include path is not a directory: {abs_incdir}")
            continue

        for root, _dirs, files in os.walk(abs_incdir):
            for filename in files:
                src_file = os.path.join(root, filename)
                rel_from_filelist = os.path.relpath(src_file, filelist_dir)

                if rel_from_filelist in copied_files:
                    stats["incdir_skipped"] += 1
                    if logger:
                        logger.debug(f"Skipping duplicate from +incdir: {rel_from_filelist}")
                    continue

                dst_file = os.path.join(origin_dir, rel_from_filelist)
                if _copy_file_safely(src_file, dst_file, logger, f"+incdir/{src_file}"):
                    copied_files.add(rel_from_filelist)
                    stats["incdir_copied"] += 1

    # Copy filelist file itself
    new_filelist = os.path.join(origin_dir, os.path.basename(input_filelist))
    try:
        shutil.copy2(input_filelist, new_filelist)
    except Exception as e:
        if logger:
            logger.error(f"Failed to copy filelist: {e}")
        raise

    if copied_abs_sources:
        _rewrite_filelist_absolute_sources(new_filelist, copied_abs_sources, logger)

    if logger:
        logger.info(
            f"Copied filelist and sources: "
            f"{stats['copied']} files from filelist, "
            f"{stats['incdir_copied']} files from +incdir, "
            f"{stats['missing']} missing, "
            f"{stats['incdir_skipped']} duplicates skipped"
        )

    return new_filelist


def _rewrite_filelist_absolute_sources(
    filelist_path: str, copied_abs_sources: dict, logger=None
) -> None:
    """Point absolute filelist entries at the copied origin sources.

    The verbatim filelist copy keeps absolute paths referencing the original
    files, so a later run would read (and depend on) the project sources
    instead of the frozen workspace copies. Rewrites each copied absolute
    entry to its origin-relative path, preserving comments, directives,
    quoting, and relative entries. Entry extraction mirrors the canonical
    filelist parser: quoted entries and inline comments are stripped before
    matching, and only the path token itself is replaced.
    """
    with open(filelist_path, encoding="utf-8") as f:
        lines = f.read().splitlines(keepends=True)

    rewritten = []
    for line in lines:
        stripped = line.strip()
        candidate = ""
        if stripped and not stripped.startswith(("+", "-", "#", "//", "`")):
            candidate = _remove_inline_comment(stripped).strip("\"'")
        if candidate and os.path.isabs(candidate):
            mapped = copied_abs_sources.get(os.path.normpath(candidate))
            if mapped is not None:
                line = line.replace(candidate, mapped)
        rewritten.append(line)

    with open(filelist_path, "w", encoding="utf-8") as f:
        f.writelines(rewritten)
    if logger:
        logger.info(
            f"Rewrote {len(copied_abs_sources)} absolute filelist entries to frozen sources"
        )


def _copy_file_safely(src: str, dst: str, logger, context: str) -> bool:
    """Copy a file with error handling and logging."""
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        if logger:
            logger.debug(f"Copied: {src} -> {dst}")
        return True
    except Exception as e:
        if logger:
            logger.error(f"Error copying {context}: {e}")
        return False
