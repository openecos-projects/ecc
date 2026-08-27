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
    PRESET_MANIFEST_RANGE,
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

    entry = _resolve_entry(manifest, run_name)
    assembled = assemble_config(manifest, entry)

    flow_config = None
    if cfg is None:
        unreadable = getattr(ctx, "config_error", None)
        if unreadable:
            # An ecc.toml that exists but cannot be read must not be
            # silently demoted to the manifest layer: it is the
            # highest-precedence configuration, and running on defaults
            # would hide that it is being ignored.
            return CommandResult.err([error_record("config_error", reason=unreadable)])
        cfg, flow_config = _manifest_only_config(ctx, assembled, entry)
    else:
        _fill_missing_from_base(cfg, assembled, ctx.project_dir)
        if entry is not None:
            cfg.manifest_parameters = assembled["parameters"]
            if "flow.preset" not in cfg._explicit_keys:
                flow_config = {"start_step": entry.start_step, "end_step": entry.end_step}

    warnings = []
    diverging = layer_divergences(cfg, assembled, entry)
    if diverging:
        warnings.append(
            warning_record(
                "config_layer_diverged",
                keys=diverging,
                reason="ecc.toml values override different project.json base values",
            )
        )
    return (cfg, flow_config, warnings)


def _manifest_only_config(ctx, assembled, entry):
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
    cfg.manifest_origin_def = _source_origin_def(assembled, ctx.project_dir)

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


def _source_origin_def(assembled: dict, project_dir: str) -> str:
    """The base_design origin DEF; relative spellings resolve against the
    project root (create_workspace resolves paths against the process cwd),
    absolute spellings pass through unchanged."""
    value = assembled.get("origin_def") or ""
    if not value or os.path.isabs(value):
        return value
    return os.path.normpath(os.path.join(project_dir, value))


def _assembled_frequency(parameters: dict) -> float:
    """The manifest layer's frequency_max as a float (0.0 when absent/invalid)."""
    try:
        return float(parameters.get("frequency_max") or 0)
    except (TypeError, ValueError, OverflowError):
        # OverflowError: a huge JSON integer (10**400) cannot become a float;
        # it is invalid input, not a crash.
        return 0.0


def _fill_missing_from_base(cfg, assembled: dict, project_dir: str) -> None:
    """Fill a hybrid config's missing fields; explicit ecc.toml values win.

    Presence, not truthiness: a key present in ecc.toml — even with an
    empty value — stays explicit and faces validation instead of being
    silently replaced by the manifest layer.
    """
    explicit = cfg._explicit_keys
    if "design.name" not in explicit:
        cfg.design_name = assembled["design_name"]
    if "design.top" not in explicit:
        cfg.design_top = assembled["top_module"]
    if "design.clock_port" not in explicit:
        cfg.design_clock_port = assembled["clock"]
    if "design.rtl" not in explicit:
        cfg.design_rtl = _source_rtl(assembled)
    if "pdk.name" not in explicit:
        cfg.pdk_name = assembled["pdk"]
    if "pdk.root" not in explicit:
        cfg.pdk_root = assembled["pdk_root"]
    if not cfg.manifest_parameters:
        cfg.manifest_parameters = dict(assembled["parameters"] or {})
    if "design.frequency_mhz" not in explicit:
        cfg.design_frequency_mhz = _assembled_frequency(assembled["parameters"])
    # origin_def exists only in the manifest layer (no ecc.toml key), so it
    # always comes from the base — resolved against the project root.
    cfg.manifest_origin_def = _source_origin_def(assembled, project_dir)


def validate_effective(ctx, cfg, *, fresh: bool, flow_config, cli_overrides=None) -> list[str]:
    """Validate the effective config for a manifest-backed project.

    Relaxations vs legacy projects: [flow] is optional when a target can be
    derived (workspace config for existing runs, entry range for declared
    creation); a multi-entry rtl list is allowed (materialized at
    creation) with every source validated. A fresh run without any
    derivable flow target is an error — before any mutation. Manifest-layer
    parameter values face the same registry type/range rules as ecc.toml
    and --set values whenever they are EFFECTIVE: a value overridden by an
    explicit ecc.toml/--set key is inert and surfaces as a divergence
    warning instead of an error.
    """
    from chipcompiler.cli.project.config import validate_project_config

    errors = validate_project_config(cfg)
    if ctx.project_state == "manifest":
        # The [flow] relaxation covers an ABSENT preset only (the target is
        # derivable elsewhere); an explicitly empty preset stays an error.
        flow_relaxed = "flow.preset" not in cfg._explicit_keys
        errors = [
            err
            for err in errors
            if not (err == "flow.preset is required" and flow_relaxed)
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
        manifest_parameters = getattr(cfg, "manifest_parameters", None)
        if manifest_parameters:
            from chipcompiler.cli.project.params import PARAM_REGISTRY, validate_value
            from chipcompiler.data.parameter_keys import geometry_to_parameters

            overridden = (
                set(getattr(cfg, "_explicit_keys", frozenset()))
                | set(cfg.params_overrides or {})
                | set(cli_overrides or {})
            )
            # Generated manifests hoist geometry values to GUI-flat aliases
            # (utilitization, margin, ...); validate the canonical form so
            # the registry's nested maps_to targets actually resolve.
            canonical = geometry_to_parameters(manifest_parameters)
            errors.extend(
                f"project.json: {err}"
                for err in _invalid_manifest_parameters(
                    canonical, PARAM_REGISTRY, validate_value, overridden
                )
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


def layer_divergences(cfg, assembled: dict, entry) -> list[str]:
    """Keys where the ecc.toml layer overrides a different manifest value.

    One canonical projection: manifest GUI-flat parameters are converted
    with geometry_to_parameters before comparison, paths are normalized
    against the project root, and the entry patch is already applied to
    *assembled* by the caller. Presence-keyed like the fill: only keys
    present in ecc.toml are compared — an explicit empty value diverges
    from a non-empty base; an absent key never diverges. *entry* (the
    selected manifest workspace, possibly None) supplies the lower-layer
    flow range.
    """
    explicit = cfg._explicit_keys
    keys: list[str] = []
    for dotted, field_name, key in (
        ("design.name", "design_name", "design_name"),
        ("design.top", "design_top", "top_module"),
        ("design.clock_port", "design_clock_port", "clock"),
        ("pdk.name", "pdk_name", "pdk"),
    ):
        base_value = assembled.get(key) or ""
        if dotted in explicit and str(base_value) != str(getattr(cfg, field_name, "")):
            keys.append(key)

    base_root = _normalize_path(cfg.project_dir, assembled.get("pdk_root"))
    toml_root = _normalize_path(cfg.project_dir, cfg.pdk_root)
    if "pdk.root" in explicit and base_root != toml_root:
        keys.append("pdk_root")

    # Ordered comparison: source order is execution-significant (filelist
    # compilation order), so a reordered list diverges; duplicates survive.
    base_sources = _normalized_sources(cfg.project_dir, _source_rtl(assembled))
    toml_sources = _normalized_sources(cfg.project_dir, cfg.design_rtl)
    if "design.rtl" in explicit and base_sources != toml_sources:
        keys.append("rtl")

    from chipcompiler.data.parameter_keys import geometry_to_parameters

    canonical_params = geometry_to_parameters(assembled.get("parameters") or {})
    if (
        "design.frequency_mhz" in explicit
        and "frequency_max" in canonical_params
        and canonical_params["frequency_max"] != cfg.design_frequency_mhz
    ):
        keys.append("frequency_max")

    # An explicit valid preset overrides the entry's declared range (GUI
    # range vocabulary on both sides); an unknown preset is left to
    # validation instead of being projected here.
    if "flow.preset" in explicit and entry is not None:
        preset_range = PRESET_MANIFEST_RANGE.get(cfg.flow_preset)
        if preset_range is not None and preset_range != (entry.start_step, entry.end_step):
            keys.append("flow")

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


def _normalized_sources(project_dir: str, sources: list[str]) -> tuple[str, ...]:
    """Normalized source paths in declaration order, blanks dropped."""
    return tuple(
        normalized for source in sources if (normalized := _normalize_path(project_dir, source))
    )


def _invalid_manifest_parameters(
    manifest_parameters: dict,
    registry,
    validate_value,
    overridden_keys: frozenset | set = frozenset(),
) -> list[str]:
    """Validate manifest-layer parameter values against the registry.

    Maps each known registry target (maps_to) back to the manifest's flat
    keys and applies the schema's range/choice rules. Values whose dotted
    key has an explicit ecc.toml/--set override are skipped (they are inert
    and surface as divergence warnings instead). Unknown keys pass through
    untouched (forward-compatible additions).
    """
    errors: list[str] = []
    for schema in registry:
        if schema.param in overridden_keys:
            continue
        maps_to = schema.maps_to
        value = None
        present = False
        if isinstance(maps_to, str):
            if maps_to in manifest_parameters:
                value = manifest_parameters[maps_to]
                present = True
        elif isinstance(maps_to, dict):
            for subtree, leaf in maps_to.items():
                node = manifest_parameters.get(subtree)
                if isinstance(node, dict) and leaf in node:
                    value = node[leaf]
                    present = True
                    break
        if present:
            # A list value (e.g. core.margin's [x, y]) validates per element.
            values = value if isinstance(value, list) else [value]
            for item in values:
                errors.extend(validate_value(item, schema))
    return errors


def _flatten(data, prefix=()):
    for key, value in (data or {}).items():
        if isinstance(value, dict):
            yield from _flatten(value, (*prefix, key))
        else:
            yield ".".join((*prefix, key)), value
