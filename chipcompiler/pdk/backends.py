"""Resolve explicit backend selections independently of a PDK's display name."""

from .manifest import DescriptorError


def extraction_backend(pdk) -> str:
    extraction = pdk.description.get("tools", {}).get("extraction", {})
    backend = extraction.get("backend_id")
    if backend not in {"native", "ics55"}:
        raise DescriptorError(
            "backend_unsupported",
            "select a supported extraction.backend_id and its matching RC model",
        )
    # The current native Python ABI represents the generic backend with an
    # empty selector. This translation belongs at the adapter boundary only.
    return "" if backend == "native" else backend
