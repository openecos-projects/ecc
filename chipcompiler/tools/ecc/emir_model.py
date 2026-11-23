"""Resolve EMIR inputs without treating a synthetic fixture as process signoff data."""

from dataclasses import dataclass
from pathlib import Path

from chipcompiler.pdk.manifest import Descriptor, DescriptorError, resource_path
from chipcompiler.utility import json_read, json_write

SYNTHETIC_NOTICE = (
    "SYNTHETIC TEST DATA ONLY: electrical values are invented. "
    "For flow validation only; NOT FOR SIGNOFF."
)


@dataclass(frozen=True)
class EmirModel:
    path: str
    synthetic: bool = False


def model_config(pdk, parameters: dict | None = None) -> dict:
    profile = pdk.description.get("tools", {}).get("configs", {}).get("emir", {})
    overrides = (parameters or {}).get("config_overrides", {}).get("emir", {})
    return {**profile, **overrides}


def inspect_model(path: str) -> EmirModel:
    synthetic = False
    if path and Path(path).is_file():
        with Path(path).open("rb") as stream:
            synthetic = b"SYNTHETIC TEST DATA ONLY" in stream.read(512)
    return EmirModel(path, synthetic)


def resolve_model(pdk, config: dict) -> EmirModel:
    """Prefer a declared process model; use a fixture only when explicitly selected."""
    if pdk.description:
        descriptor = Descriptor.model_validate(pdk.description)
        models = [
            resource_path(pdk.require_root(), resource)
            for resource in descriptor.resources.values()
            if resource.role == "em"
        ]
        if len(models) > 1:
            raise DescriptorError("mapping_conflict", "select exactly one EM technology model")
        if models:
            return inspect_model(str(models[0]))
    configured = config.get("technology_file_path", "")
    if configured:
        return inspect_model(str(Path(configured).expanduser()))
    synthetic = config.get("synthetic_model", "")
    if synthetic:
        if synthetic != "ics55" or pdk.name.casefold() != "ics55":
            raise DescriptorError("invalid_emir_model", "the ICS55 fixture requires an ICS55 PDK")
        return EmirModel(
            str(Path(__file__).parent / "configs" / "defaults" / "ics55_synthetic.tech"),
            synthetic=True,
        )
    return EmirModel("")


def refresh_emir_config(workspace) -> None:
    path = workspace.config.get("emir")
    if path is None:
        return
    config = json_read(path)
    if not isinstance(config, dict):
        raise FileNotFoundError(f"EMIR config missing or corrupt: {path}")
    # Resolve from source policy, never from a stale generated absolute path.
    selection = model_config(workspace.pdk, workspace.parameters.data)
    if not workspace.pdk.description:
        selection = {**config, **selection}
    model = resolve_model(workspace.pdk, selection)
    config.update(
        technology_file_path=model.path,
        synthetic_model=selection.get("synthetic_model", ""),
        model_kind="synthetic" if model.synthetic else "provided" if model.path else "missing",
        qualification="not_for_signoff" if model.synthetic else "not_assessed",
    )
    if not json_write(path, config):
        raise OSError(f"Failed to write EMIR config: {path}")


def model_notice(workspace) -> str:
    path = workspace.config.get("emir")
    config = json_read(path) if path else {}
    return SYNTHETIC_NOTICE if config.get("model_kind") == "synthetic" else ""
