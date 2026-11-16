"""Resolved evidence consumed by clients without reinterpreting process files."""

import json
import re
from pathlib import Path

from .documents import document_digest, process_identity, split_descriptor
from .managed import legacy_identity
from .manifest import Descriptor, content_identity, resource_path


def database_units(root: Path, descriptor: Descriptor) -> int | None:
    units = {
        int(value)
        for resource in descriptor.resources.values()
        if resource.role in {"tech", "lef"}
        for value in re.findall(
            r"DATABASE\s+MICRONS\s+(\d+)", resource_path(root, resource).read_text(), re.IGNORECASE
        )
    }
    return next(iter(units)) if len(units) == 1 else None


def site_width_dbu(root: Path, descriptor: Descriptor) -> int | None:
    if not descriptor.cells.site_core:
        return None
    texts = [
        resource_path(root, resource).read_text()
        for resource in descriptor.resources.values()
        if resource.role in {"tech", "lef"}
    ]
    units = {
        int(value)
        for text in texts
        for value in re.findall(r"DATABASE\s+MICRONS\s+(\d+)", text, re.IGNORECASE)
    }
    site = re.escape(descriptor.cells.site_core)
    sizes = {
        float(match[1])
        for text in texts
        for body in re.findall(
            rf"\bSITE\s+{site}\b\s+(?=(?:CLASS|SIZE|SYMMETRY|ROWPATTERN)\b)"
            rf"(.*?)\bEND\s+{site}\b",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if (match := re.search(r"SIZE\s+([0-9.]+)\s+BY", body, re.IGNORECASE))
    }
    if len(units) != 1 or len(sizes) != 1:
        return None
    width = next(iter(units)) * next(iter(sizes))
    return round(width) if width > 0 and abs(width - round(width)) < 1e-6 else None


def resolved_context(root: Path, descriptor: Descriptor) -> dict:
    digest, hashes = content_identity(root, descriptor)
    return {
        "schema_version": 1,
        "content_digest": digest,
        "legacy_content_digest": legacy_identity(root, descriptor, hashes),
        "pdk_digest": process_identity(descriptor, hashes),
        "adaptation_digest": document_digest(split_descriptor(descriptor).adaptation),
        "resource_root": str(root.resolve()),
        "resources": {
            name: {"path": resource.path, "sha256": hashes[name]}
            for name, resource in descriptor.resources.items()
        },
        "site_width_dbu": site_width_dbu(root, descriptor),
        "database_units_per_micron": database_units(root, descriptor),
    }


def write_context(root: Path, descriptor: Descriptor, path: Path) -> None:
    path.write_text(
        json.dumps(resolved_context(root, descriptor), indent=2) + "\n", encoding="utf-8"
    )


def verify_workspace_context(workspace) -> None:
    path = workspace.directory / "home" / "ecc-pdk-context.json"
    if not workspace.pdk.description:
        return
    from dataclasses import fields

    from .manifest import DescriptorError
    from .resolver import resolve_descriptor

    expected = resolve_descriptor(
        workspace.pdk.root, Descriptor.model_validate(workspace.pdk.description)
    )
    for field in fields(expected):
        if field.name not in {"sdc", "spef"} and getattr(workspace.pdk, field.name) != getattr(
            expected, field.name
        ):
            raise DescriptorError(
                "project_pdk_immutable", f"resolved PDK {field.name} differs from its description"
            )
    if not path.exists():
        if (workspace.directory / "home/flow.json").exists():
            raise DescriptorError(
                "pdk_context_missing", "workspace PDK context is missing; recreate the workspace"
            )
        return
    context = json.loads(path.read_text())
    digest, _ = content_identity(
        workspace.pdk.root, Descriptor.model_validate(workspace.pdk.description)
    )
    if context.get("content_digest") != digest:
        raise DescriptorError(
            "project_pdk_immutable",
            "workspace PDK differs from its frozen context; create a new project",
        )
