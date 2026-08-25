#!/usr/bin/env python

"""Effective configuration for manifest-backed projects.

The single owner of manifest preparation: load the manifest once, resolve
the selected workspace entry, assemble ``base_design + parameter_patch``,
map ``origin_verilog`` as the RTL fallback, overlay only explicitly
supplied ecc.toml values, validate the effective config, and compute
divergence warnings on one canonical projection. Both ``ecc check`` and
``ecc run`` route through this module.

Imported lazily by the command handlers, so module-level imports must stay
cheap (no chipcompiler.data imports here).
"""

import os
from typing import TYPE_CHECKING

from chipcompiler.cli.core.records import error_record, warning_record
from chipcompiler.cli.core.types import CommandResult
from chipcompiler.cli.project.manifest import (
    ManifestError,
    assemble_config,
    load_manifest,
)

if TYPE_CHECKING:
    from chipcompiler.cli.project.config import ProjectConfig


def _resolve_entry(manifest, run_name: str | None):
    """The declared workspace for a run id; auto-selects a single active one."""
    if run_name is not None:
        return manifest.find_workspace(run_name)
    active = manifest.active_workspaces()
    return active[0] if len(active) == 1 else None


def _find_entry(manifest, run_name: str | None):
    if run_name is None:
        return None
    return manifest.find_workspace(run_name)


def resolve_effective_config(
    ctx, run_name: str | None, cfg: "ProjectConfig | None"
) -> "CommandResult | tuple[ProjectConfig, dict | None, list[dict]]":
    """Build the effective config for a manifest-backed project.

    Returns (cfg, flow_config, warnings) or a CommandResult error. The
    workspace entry's parameter_patch layers beneath ecc.toml; its
    start/end range seeds creation only when the project ecc.toml has no
    flow target. Divergence warnings compare the complete lower layer on
    one canonical projection.
    """
    try:
        manifest = load_manifest(ctx.project_dir)
    except (ManifestError, OSError) as exc:
        return CommandResult.err([error_record("manifest_invalid", reason=str(exc))])

    entry = (
        _resolve_entry(manifest, run_name) if run_name is None else _find_entry(manifest, run_name)
    )
    assembled = assemble_config(manifest, entry)

    flow_config = None
    if cfg is None:
        cfg, flow_config = _manifest_only_config(ctx, manifest, assembled, entry)
    else:
        _fill_missing_from_base(cfg, assembled, ctx.project_dir)
        if entry is not None:
            cfg.manifest_parameters = assembled["parameters"]
            if not cfg.flow_preset:
                flow_config = {"start_step": entry.start_step, "end_step": entry.end_step}

    warnings = []
    diverging = layer_divergences(cfg, assembled)
    if diverging:
        warnings.append(
            warning_record(
                "config_layer_diverged",
                keys=diverging,
                reason="ecc.toml values override different project.json base values",
            )
        )
    return (cfg, flow_config, warnings)


def _manifest_only_config(ctx, manifest, assembled, entry):
    """Build a ProjectConfig from the manifest alone (no ecc.toml)."""
    from chipcompiler.cli.project.config import ProjectConfig

    parameters = assembled["parameters"]
    cfg = ProjectConfig(
        design_name=assembled["design_name"],
        design_top=assembled["top_module"],
        design_rtl=_source_rtl(assembled),
        design_clock_port=assembled["clock"],
        design_frequency_mhz=_assembled_frequency(parameters),
        pdk_name=assembled["pdk"],
        pdk_root=assembled["pdk_root"],
        flow_preset="rtl2gds",  # inert: the entry range drives the created range
        project_dir=ctx.project_dir,
    )
    cfg.params_overrides = {}
    cfg.manifest_parameters = parameters
    cfg.manifest_driven = True
    cfg.manifest_origin_def = str(manifest.base_design.get("origin_def") or "")

    flow_config = None
    if entry is not None:
        flow_config = {"start_step": entry.start_step, "end_step": entry.end_step}
    return (cfg, flow_config)


def _source_rtl(assembled: dict) -> list[str]:
    """The RTL sources for the effective config (rtl_list, else origin_verilog)."""
    rtl = list(assembled["rtl_list"])
    if not rtl and assembled["origin_verilog"]:
        rtl = [assembled["origin_verilog"]]
    return rtl


def _assembled_frequency(parameters: dict) -> float:
    """The manifest layer's frequency_max as a float (0.0 when absent/invalid)."""
    try:
        return float(parameters.get("frequency_max") or 0)
    except (TypeError, ValueError):
        return 0.0


def _fill_missing_from_base(cfg, assembled: dict, project_dir: str) -> None:
    """Fill a hybrid config's missing fields; explicit ecc.toml values win."""
    cfg.design_name = cfg.design_name or assembled["design_name"]
    cfg.design_top = cfg.design_top or assembled["top_module"]
    cfg.design_clock_port = cfg.design_clock_port or assembled["clock"]
    if not cfg.design_rtl:
        cfg.design_rtl = _source_rtl(assembled)
    cfg.pdk_name = cfg.pdk_name or assembled["pdk"]
    cfg.pdk_root = cfg.pdk_root or assembled["pdk_root"]
    if not cfg.manifest_parameters:
        cfg.manifest_parameters = dict(assembled["parameters"] or {})
    if not cfg._frequency_explicit:
        # Presence, not truthiness: an explicit frequency_mhz = 0 stays
        # explicit and fails validation instead of being silently replaced.
        cfg.design_frequency_mhz = _assembled_frequency(assembled["parameters"])


def validate_effective(ctx, cfg, *, fresh: bool, flow_config) -> list[str]:
    """Validate the effective config for a manifest-backed project.

    Relaxations vs legacy projects: [flow] is optional when a target can be
    derived (workspace config for existing runs, entry range for declared
    creation); a multi-entry rtl list is allowed (materialized at
    creation) with every source validated. A fresh run without any
    derivable flow target is an error — before any mutation.
    """
    from chipcompiler.cli.project.config import validate_project_config

    errors = validate_project_config(cfg)
    if ctx.project_state == "manifest":
        errors = [
            err
            for err in errors
            if err != "flow.preset is required"
            and not err.startswith("design.rtl must have exactly one entry")
        ]
        # validate_project_config checks the first source only for a
        # single-entry list; the relaxed multi-source case checks every
        # declared source here.
        sources = cfg.design_rtl if len(cfg.design_rtl) > 1 else cfg.design_rtl[1:]
        for entry in sources:
            errors.extend(_validate_rtl_source(cfg.project_dir, entry))
        if fresh and not cfg.flow_preset and flow_config is None:
            errors.append(
                "no flow target: set flow.preset in ecc.toml or declare the workspace's "
                "start/end range in project.json"
            )
    return errors


def _validate_rtl_source(project_dir: str, entry: str) -> list[str]:
    """Existence/shape validation for one RTL source beyond the first."""
    from chipcompiler.cli.project.config import _resolve_path
    from chipcompiler.utility.filelist import FILELIST_SUFFIXES, RTL_SUFFIXES

    path = _resolve_path(project_dir, entry)
    if not os.path.exists(path):
        return [f"rtl path does not exist: {entry}"]
    if os.path.isdir(path):
        return [f"rtl path must be a file, not a directory: {entry}"]
    suffix = os.path.splitext(path)[1].lower()
    if suffix in FILELIST_SUFFIXES:
        from chipcompiler.utility.filelist import validate_filelist

        try:
            _, missing = validate_filelist(path)
            if missing:
                return [f"filelist references missing files: {', '.join(missing)}"]
        except (ValueError, OSError) as exc:
            return [f"invalid filelist {entry}: {exc}"]
    elif suffix not in RTL_SUFFIXES:
        return [f"unsupported rtl source suffix: {entry}"]
    return []


def layer_divergences(cfg, assembled: dict) -> list[str]:
    """Keys where the ecc.toml layer overrides a different manifest value.

    One canonical projection: manifest GUI-flat parameters are converted
    with geometry_to_parameters before comparison, paths are normalized
    against the project root, and the entry patch is already applied to
    *assembled* by the caller. Empty/absent values never diverge.
    """
    keys: list[str] = []
    for field_name, key in (
        ("design_name", "design_name"),
        ("design_top", "top_module"),
        ("design_clock_port", "clock"),
        ("pdk_name", "pdk"),
    ):
        base_value = assembled.get(key) or ""
        toml_value = getattr(cfg, field_name, "")
        if base_value and toml_value and str(base_value) != str(toml_value):
            keys.append(key)

    base_root = _normalize_path(cfg.project_dir, assembled.get("pdk_root"))
    toml_root = _normalize_path(cfg.project_dir, cfg.pdk_root)
    if base_root and toml_root and base_root != toml_root:
        keys.append("pdk_root")

    base_sources = {_normalize_path(cfg.project_dir, entry) for entry in _source_rtl(assembled)}
    toml_sources = {_normalize_path(cfg.project_dir, entry) for entry in cfg.design_rtl}
    base_sources.discard("")
    toml_sources.discard("")
    if base_sources and toml_sources and base_sources != toml_sources:
        keys.append("rtl")

    from chipcompiler.data.parameter_keys import geometry_to_parameters

    canonical_params = geometry_to_parameters(assembled.get("parameters") or {})
    base_frequency = canonical_params.get("frequency_max")
    if (
        base_frequency
        and cfg.design_frequency_mhz > 0
        and base_frequency != cfg.design_frequency_mhz
    ):
        keys.append("frequency_max")

    if cfg.params_overrides and canonical_params:
        from chipcompiler.cli.project.params import (
            build_backend_overrides,
            resolve_parameters,
        )

        resolved, _ = resolve_parameters(toml_overrides=cfg.params_overrides)
        backend = build_backend_overrides(resolved)
        flat_base = dict(_flatten(canonical_params))
        for key, value in _flatten(backend):
            if key in flat_base and flat_base[key] != value:
                keys.append(key)
    return keys


def _normalize_path(project_dir: str, value) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    if os.path.isabs(value):
        return os.path.normpath(value)
    return os.path.normpath(os.path.join(project_dir, value))


def _flatten(data, prefix=()):
    for key, value in (data or {}).items():
        if isinstance(value, dict):
            yield from _flatten(value, (*prefix, key))
        else:
            yield ".".join((*prefix, key)), value
