"""Merge PDK cell layouts into the GDS written by ecc-tools.

The native GDS writer emits one abstract ``Master_<cell>`` cell per LEF master
(boundary plus pin/obstruction metal), so the device layers (active, n-well,
poly, contacts, ...) of standard cells, IO cells and macros are missing. This
module fills those cells from the PDK's own GDS libraries with KLayout.
"""

import logging
import os
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from chipcompiler.data import EccStep, Workspace
from chipcompiler.data.pdk import PDK
from chipcompiler.utility.log import Logger

MASTER_PREFIX = "Master_"
_LEF_SUFFIXES = ("_ecos", "_ant")


@dataclass
class GdsMergeResult:
    merged: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


def derive_gds_from_lefs(lefs: Iterable[Path]) -> list[Path]:
    """Guess GDS libraries from LEF paths laid out as ``<lib>/lef/<name>[_ecos][_ant].lef``."""
    found: list[Path] = []
    for lef in lefs:
        stem = Path(lef).stem
        while True:
            trimmed = stem
            for suffix in _LEF_SUFFIXES:
                trimmed = trimmed.removesuffix(suffix)
            if trimmed == stem:
                break
            stem = trimmed
        candidate = Path(lef).parent.parent / "gds" / f"{stem}.gds"
        if candidate.is_file() and candidate not in found:
            found.append(candidate)
    return found


def pdk_gds_files(pdk: PDK) -> list[Path]:
    """PDK GDS libraries: configured ``pdk.gds`` when set, else derived from ``pdk.lefs``."""
    if pdk.gds:
        return [Path(path) for path in pdk.gds if Path(path).is_file()]
    return derive_gds_from_lefs(pdk.lefs)


def merge_pdk_gds(
    gds_path: str | Path,
    library_paths: Iterable[str | Path],
    logger: Logger | logging.Logger | None = None,
) -> GdsMergeResult:
    """Replace every ``Master_<cell>`` in ``gds_path`` with the full layout from the libraries.

    The file is rewritten in place (atomically) only when at least one cell is merged.
    The abstract cell's own shapes are kept, so the LEF boundary marker survives; the
    PDK content is added on top.
    """
    import klayout.db as db

    log = logger or logging.getLogger(__name__)
    gds_path = Path(gds_path)
    result = GdsMergeResult()

    layout = db.Layout()
    layout.read(str(gds_path))
    masters = {
        cell.name[len(MASTER_PREFIX) :]: cell
        for cell in layout.each_cell()
        if cell.name.startswith(MASTER_PREFIX)
    }
    if not masters:
        return result

    pending = dict(masters)
    for library_path in library_paths:
        if not pending:
            break
        library = db.Layout()
        library.read(str(library_path))
        for name in [name for name in pending if library.has_cell(name)]:
            pending.pop(name)
            masters[name].copy_tree(library.cell(name))
            result.merged.append(name)

    result.missing = sorted(pending)
    if result.missing:
        log.warning(
            "GDS merge: no PDK layout for %d cell(s), left abstract: %s",
            len(result.missing),
            ", ".join(result.missing[:10]) + (" ..." if len(result.missing) > 10 else ""),
        )

    if not result.merged:
        return result

    options = db.SaveLayoutOptions()
    options.set_format_from_filename(str(gds_path))
    suffix = "".join(gds_path.suffixes) or ".gds"
    fd, tmp_name = tempfile.mkstemp(dir=gds_path.parent, prefix=f".{gds_path.name}.", suffix=suffix)
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        layout.write(str(tmp_path), options)
        os.replace(tmp_path, gds_path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    log.info("GDS merge: filled %d cell(s) from PDK GDS in %s", len(result.merged), gds_path)
    return result


def merge_pdk_cell_layouts(workspace: Workspace, step: EccStep) -> bool:
    """Fill the abstract cells of the step's GDS with the PDK std-cell/IO/macro layouts.

    Returns False only when a GDS exists and the merge itself failed.
    """
    gds_path = Path(step.output.gds) if step.output.gds else None
    if gds_path is None or not gds_path.is_file():
        return True
    libraries = pdk_gds_files(workspace.pdk)
    if not libraries:
        workspace.logger.warning(
            "No PDK GDS libraries configured (pdk.gds); %s keeps abstract cells", gds_path
        )
        return True
    try:
        merge_pdk_gds(gds_path, libraries, workspace.logger)
    except Exception as exc:
        workspace.logger.error("Failed to merge PDK GDS into %s: %s", gds_path, exc)
        return False
    return True
