"""CLI-specific PDK path validation for ``[pdk.overrides]`` parameters."""

from dataclasses import replace

from chipcompiler.cli.project.config import ProjectConfig, resolve_pdk_overrides, resolve_pdk_root
from chipcompiler.data.pdk import PDK, get_pdk


def project_parameter_pdk(cfg: ProjectConfig | None) -> PDK | None:
    """Resolve parameter defaults against the same PDK root as the project's workspace."""
    if cfg is None:
        return None
    return get_pdk(
        cfg.pdk_name,
        resolve_pdk_root(cfg),
        overrides=resolve_pdk_overrides(cfg),
        validate=False,
    )


def validate_pdk_target(schema, value, cfg) -> str | None:
    if schema.pdk_target is None:
        return None
    from chipcompiler.cli.project.config import _validate_pdk_contents

    overrides = dict(cfg.pdk_overrides)
    overrides[schema.pdk_target] = value
    candidate = replace(cfg, pdk_overrides=overrides)
    return _validate_pdk_contents(
        candidate.pdk_name,
        resolve_pdk_root(candidate),
        resolve_pdk_overrides(candidate),
    )
