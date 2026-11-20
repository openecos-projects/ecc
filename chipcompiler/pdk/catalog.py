"""Build and verify the shared native STA table for a locked PDK description."""

import errno
import hashlib
import os
import re
from pathlib import Path

from chipcompiler.utility.file import write_text_atomic

from .documents import split_descriptor
from .manifest import CellVariant, Descriptor, DescriptorError, file_digest, resource_path
from .profiles import CatalogRule, matching_profile
from .registry import inventory_path

_MACRO = re.compile(rb"^[ \t]*MACRO[ \t]+([^\s#;]+)", re.MULTILINE)


def _generate(root: Path, descriptor: Descriptor, rule: CatalogRule) -> list[CellVariant]:
    rows = []
    pattern = re.compile(rule.master)
    for key in rule.lefs:
        resource = descriptor.resources[key]
        content = resource_path(root, resource).read_bytes()
        if resource.role != "lef" or hashlib.sha256(content).hexdigest() != resource.sha256:
            raise DescriptorError("content_mismatch", f"unexpected catalog LEF: {resource.path}")
        for name in sorted(_MACRO.findall(content)):
            master = name.decode("ascii")
            if match := pattern.fullmatch(master):
                rows.append(
                    CellVariant(
                        master=master,
                        family=match[1],
                        vt=rule.vt[match[3]],
                        drive_rank=float((match[2] or "1").replace("P", ".")),
                    )
                )
    if rule.sort_by_master:
        rows.sort(key=lambda row: row.master)
    return rows


def _render(rows: list[CellVariant], *, compact: bool) -> str:
    lines = []
    for row in rows:
        if row.drive_rank < 0 or any(
            not x or any(c.isspace() for c in x) for x in (row.master, row.family, row.vt)
        ):
            raise DescriptorError("invalid_cell_catalog", "invalid STA catalog row")
        rank = format(row.drive_rank, ".17g") if compact else str(row.drive_rank)
        lines.append(f"{row.master}\t{row.family}\t{row.vt}\t{rank}\n")
    return "".join(lines)


def shared_sta_catalog(root: Path, descriptor: Descriptor) -> Path | None:
    profile = matching_profile(split_descriptor(descriptor))
    rule = profile.sta_catalog if profile else None
    if rule:
        checksum = rule.sha256
        text = None
    elif descriptor.cell_catalog:
        text = _render(descriptor.cell_catalog, compact=True)
        checksum = hashlib.sha256(text.encode()).hexdigest()
    else:
        return None

    def ensure(path: Path) -> Path:
        nonlocal text
        if path.is_symlink():
            raise DescriptorError("unsafe_path", f"STA catalog must not be a symlink: {path}")
        if path.is_file() and file_digest(path) == checksum:
            return path
        if text is None and rule:
            text = _render(_generate(root, descriptor, rule), compact=rule.compact_drive)
        if not text or hashlib.sha256(text.encode()).hexdigest() != checksum:
            raise DescriptorError(
                "invalid_cell_catalog", "generated STA table differs from the pinned profile"
            )
        write_text_atomic(path, text)
        return path

    local = root.resolve() / "cell_catalog.tsv"
    if local.exists() or os.access(local.parent, os.W_OK):
        try:
            return ensure(local)
        except OSError as exc:
            if exc.errno not in {errno.EROFS, errno.EACCES, errno.EPERM}:
                raise
    cache = inventory_path().parent / "pdk-catalogs" / checksum / local.name
    cache.parent.mkdir(parents=True, exist_ok=True)
    return ensure(cache)
