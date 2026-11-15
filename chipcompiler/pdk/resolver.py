"""Translate a description into the existing tool-facing PDK data contract."""

from pathlib import Path

from .manifest import Descriptor, DescriptorError, load_descriptor, resource_path


def resolve_pdk(root: Path, *, name: str = "", descriptor_path: Path | None = None):
    root = root.expanduser().resolve()
    descriptor = load_descriptor(root, descriptor_path)
    if name and descriptor.family_id.casefold() != name.casefold():
        raise DescriptorError(
            "family_mismatch", f"requested {name}, description declares {descriptor.family_id}"
        )
    return resolve_descriptor(root, descriptor)


def resolve_descriptor(root: Path, descriptor: Descriptor):
    from chipcompiler.data.pdk import PDK

    by_role: dict[str, list[Path]] = {}
    for resource in descriptor.resources.values():
        by_role.setdefault(resource.role, []).append(resource_path(root, resource))
    libraries = by_role.get("liberty", [])
    default_view = descriptor.tools.get("timing", {}).get("default_view")
    if default_view:
        if default_view not in descriptor.views:
            raise DescriptorError("view_missing", f"unknown default timing view: {default_view}")
        libraries = [
            resource_path(root, descriptor.resources[key])
            for key in descriptor.views[default_view].libraries
        ]
    return PDK(
        name=descriptor.family_id,
        version=descriptor.release,
        root=root,
        tech=next(iter(by_role.get("tech", [])), None),
        lefs=by_role.get("lef", []),
        libs=libraries,
        mapping_file=next(iter(by_role.get("mapping", [])), None),
        corners=descriptor.tools.get("extraction", {}).get("corners", []),
        **descriptor.cells.model_dump(),
        description=descriptor.model_dump(),
    )


def descriptor_for(pdk) -> Descriptor | None:
    return Descriptor.model_validate(pdk.description) if pdk.description else None
