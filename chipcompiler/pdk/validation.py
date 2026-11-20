"""Resource readiness is separate from backend support and qualification."""

from pathlib import Path

from .manifest import Descriptor, DescriptorError, check_release, file_digest, resource_path

_STAGE_RESOURCES = {
    "synthesis": {"liberty"},
    "floorplan": {"tech", "lef"},
    "placement": {"tech", "lef"},
    "cts": {"tech", "lef", "liberty"},
    "routing": {"tech", "lef"},
    "sta": {"liberty"},
    "extraction": {"tech", "lef"},
    "sizing": {"tech", "lef", "liberty"},
    "emir": {"tech", "lef", "em"},
    "gds": {"tech", "lef", "gds", "mapping"},
}


def validate_resources(root: Path, descriptor: Descriptor) -> dict:
    version = check_release(root, descriptor.release)
    diagnostics = []
    available = set()
    failed_roles = set()
    for name, resource in descriptor.resources.items():
        try:
            path = resource_path(root, resource)
            if not path.is_file():
                raise DescriptorError("resource_missing", f"resource does not exist: {path}")
            if (
                version is None
                and resource.sha256 is not None
                and file_digest(path) != resource.sha256
            ):
                raise DescriptorError("content_mismatch", f"resource checksum differs: {name}")
            available.add(resource.role)
        except (DescriptorError, OSError) as exc:
            failed_roles.add(resource.role)
            diagnostics.append(
                {
                    "code": exc.code if isinstance(exc, DescriptorError) else "resource_unreadable",
                    "resource": name,
                    "message": str(exc),
                }
            )
    stages = {}
    for stage, roles in _STAGE_RESOURCES.items():
        missing = sorted(roles - available)
        stages[stage] = {
            "resources_ready": not missing and not (roles & failed_roles),
            "missing_roles": missing,
            "backend_support": "unchecked",
            "qualification": "unverified",
        }
    return {"diagnostics": diagnostics, "stages": stages}
