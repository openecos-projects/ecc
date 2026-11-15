"""Render the native STA catalog from the project-locked cell semantics."""

from pathlib import Path

from .manifest import Descriptor, DescriptorError


def write_sta_catalog(description: dict, path: Path) -> None:
    descriptor = Descriptor.model_validate(description)
    lines = []
    for cell in descriptor.cell_catalog:
        if any(
            not value or any(char.isspace() for char in value)
            for value in (cell.master, cell.family, cell.vt)
        ):
            raise DescriptorError(
                "invalid_cell_catalog", "STA catalog identifiers must be nonempty tokens"
            )
        lines.append(f"{cell.master}\t{cell.family}\t{cell.vt}\t{cell.drive_rank:.17g}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
