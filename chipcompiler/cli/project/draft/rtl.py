"""Staged RTL hardlink planning, digest verification, and partial-import cleanup."""

from collections.abc import Sequence
from pathlib import Path

from chipcompiler.cli.project.config import ProjectConfig
from chipcompiler.cli.project.design_inputs import resolve_design_inputs
from chipcompiler.cli.project.rtl_import import require_rtl_target_parents
from chipcompiler.utility.file import file_digest
from chipcompiler.utility.filelist import FILELIST_SUFFIXES


def rtl_paths(project: Path, staging: Path, targets: Sequence[str]) -> list[tuple[Path, Path]]:
    paths = []
    for target in targets:
        relative = Path(target)
        if relative.is_absolute() or relative.parts[:1] != ("rtl",) or ".." in relative.parts:
            raise OSError("Invalid RTL path in Workspace draft")
        source = staging / relative
        if len(relative.parts) < 2 or source.resolve() != source or not source.is_file():
            raise OSError("Invalid staged RTL in Workspace draft")
        paths.append((source, project / relative))
    return paths


def rtl_digests(project: Path, paths: list[tuple[Path, Path]]) -> dict[str, str]:
    digests = {}
    for source, destination in paths:
        digest = file_digest(source)
        if digest is None:
            raise OSError(f"Could not read staged RTL: {source}")
        digests[destination.relative_to(project).as_posix()] = digest[0]
    return digests


def rtl_links(paths: list[tuple[Path, Path]], digests: dict[Path, str]) -> list[tuple[Path, Path]]:
    links = []
    for source, destination in paths:
        if destination.resolve() != destination:
            raise FileExistsError(f"RTL target is a symbolic link: {destination}")
        require_rtl_target_parents(destination)
        if destination.exists():
            if destination.is_file() and destination.samefile(source):
                expected = digests.get(destination)
                if expected is None or _matches_digest(source, expected):
                    continue
            raise FileExistsError(f"RTL target already exists: {destination}")
        links.append((source, destination))
    return links


def discard_partial_rtl(
    cfg: ProjectConfig,
    paths: list[tuple[Path, Path]],
    digests: dict[Path, str],
) -> None:
    inputs = resolve_design_inputs(cfg)
    selected = {Path(path).resolve() for path in inputs.paths()}
    # A selected filelist can refer to other files in the same import.
    filelists = [
        Path(path) for path in inputs.rtl if Path(path).suffix.lower() in FILELIST_SUFFIXES
    ]
    if filelists:
        from chipcompiler.utility.filelist import parse_filelist, parse_incdir_directives

        include_dirs = set()
        for path in filelists:
            try:
                selected.update(
                    (path.parent / item).resolve() for item in parse_filelist(str(path))
                )
                include_dirs.update(
                    (path.parent / item).resolve() for item in parse_incdir_directives(str(path))
                )
            except (OSError, ValueError):
                return
        selected.update(
            destination
            for _, destination in paths
            if any(destination.is_relative_to(directory) for directory in include_dirs)
        )
    for source, destination in paths:
        expected = digests.get(destination)
        if (
            expected is not None
            and destination not in selected
            and destination.resolve() == destination
            and destination.is_file()
            and destination.samefile(source)
            and _matches_digest(source, expected)
        ):
            destination.unlink()


def _matches_digest(source: Path, expected: str) -> bool:
    digest = file_digest(source)
    return digest is not None and digest[0] == expected
