"""CLI-specific PDK path validation for ``[pdk.overrides]`` parameters."""

from dataclasses import replace


def validate_pdk_target(schema, value, cfg) -> str | None:
    if schema.pdk_target is None:
        return None
    from chipcompiler.cli.project.config import (
        _validate_pdk_contents,
        resolve_pdk_overrides,
        resolve_pdk_root,
    )

    overrides = dict(cfg.pdk_overrides)
    overrides[schema.pdk_target] = value
    candidate = replace(cfg, pdk_overrides=overrides)
    return _validate_pdk_contents(
        candidate.pdk_name,
        resolve_pdk_root(candidate),
        resolve_pdk_overrides(candidate),
    )
