#!/usr/bin/env python

"""Effective configuration for manifest-backed projects.

The single owner of manifest preparation: load the manifest once, resolve
the selected workspace entry, assemble the manifest's design identity and sources,
map ``origin_verilog`` as the RTL fallback, overlay only explicitly
supplied ecc.toml values, validate the effective config, and compute
divergence warnings on one canonical projection. Both ``ecc check`` and
``ecc run`` route through this module.

Imported lazily by the command handlers, so module-level imports must stay
cheap (no chipcompiler.data imports here).
"""

import os
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeGuard

from chipcompiler.cli.core.records import error_record, warning_record
from chipcompiler.cli.core.types import CommandResult
from chipcompiler.cli.project.manifest_flow import (
    attach_insert_steps,
    declared_insert_steps,
    entry_flow_config,
    manifest_synthesis_lec,
)
from chipcompiler.project.manifest import (
    PRESET_MANIFEST_RANGE,
    ManifestError,
    assemble_config,
    load_manifest,
)

if TYPE_CHECKING:
    from chipcompiler.cli.core.types import CommandContext
    from chipcompiler.cli.project.config import ProjectConfig


def _resolve_entry(manifest, run_name: str | None):
    """The declared workspace for a run id; auto-selects a single active one."""
    if run_name is not None:
        return manifest.find_workspace(run_name)
    active = manifest.active_workspaces()
    return active[0] if len(active) == 1 else None


def declared_skip_steps(entry, cfg) -> list | None:
    """The declared skip policy: ecc.toml wins over the project.json entry.

    Same precedence direction as every other key — the manifest entry is
    the base layer and an explicit ecc.toml value overrides it. None means
    neither surface declared a policy (the code default applies downstream);
    [] is an explicit run-everything.
    """
    if "flow.skip_steps" in getattr(cfg, "_explicit_keys", frozenset()):
        return list(getattr(cfg, "flow_skip_steps", None) or [])
    if entry is not None and getattr(entry, "skip_steps", None) is not None:
        return list(entry.skip_steps)
    return None


def skip_steps_shadow_warning(entry, cfg) -> dict | None:
    """The skip_steps_shadowed warning when both surfaces declare the policy
    with different effective values.

    Only an explicit ecc.toml declaration can shadow the manifest entry (the
    base layer), and only a genuinely different policy: alias spellings and
    list order normalize away before comparison.
    """
    if entry is None or "flow.skip_steps" not in getattr(cfg, "_explicit_keys", frozenset()):
        return None
    manifest_value = getattr(entry, "skip_steps", None)
    if manifest_value is None:
        return None
    from chipcompiler.rtl2gds.builder import resolve_skip_steps

    try:
        toml_effective = resolve_skip_steps({"skip_steps": cfg.flow_skip_steps})
    except ValueError:
        # An invalid list shadows nothing; config validation reports it.
        return None
    manifest_effective = resolve_skip_steps({"skip_steps": list(manifest_value)})
    if toml_effective == manifest_effective:
        return None
    return warning_record(
        "skip_steps_shadowed",
        effective_source="ecc.toml",
        shadowed_source="project.json",
        reason="ecc.toml [flow] skip_steps overrides the project.json workspace entry; "
        "remove the ecc.toml key to let the project.json entry apply",
    )


def _attach_skip_steps(flow_config: dict | None, skip_steps: list | None) -> dict | None:
    """Carry a declared skip policy on the flow config (policy-only when
    the config selects no steps)."""
    return _attach_flow_key(flow_config, "skip_steps", skip_steps)


def _attach_lec_engine(flow_config: dict | None, lec_engine: str | None) -> dict | None:
    """Carry a declared LEC engine on the flow config (policy-only when the
    config selects no steps)."""
    return _attach_flow_key(flow_config, "lec_engine", lec_engine)


def _attach_flow_key(flow_config: dict | None, key: str, value) -> dict | None:
    if value is None:
        return flow_config
    flow_config = dict(flow_config or {})
    flow_config[key] = value
    return flow_config


def declared_lec_engine(cfg) -> str | None:
    """The declared [flow] lec_engine spelling; None when the key is absent."""
    if "flow.lec_engine" in getattr(cfg, "_explicit_keys", frozenset()):
        return cfg.flow_lec_engine
    return None


def flow_config_selects_steps(flow_config: object) -> TypeGuard[dict]:
    """Whether a flow config names steps (a range or explicit selection).

    A policy-only config (just ``skip_steps``) selects nothing: it must
    not satisfy a flow-target requirement nor trigger range preflight.
    """
    if not isinstance(flow_config, dict):
        return False
    return bool(flow_config.get("start_step")) or bool(flow_config.get("steps"))


def resolve_effective_config(
    ctx: "CommandContext", run_name: str | None, cfg: "ProjectConfig | None"
) -> "CommandResult | tuple[ProjectConfig, dict[str, Any] | None, list[dict[str, Any]]]":
    """Build the effective config for a manifest-backed project.

    Returns (cfg, flow_config, warnings) or a CommandResult error. The
    manifest's design identity layers beneath ecc.toml; the workspace entry's
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
        if entry is not None and "flow.preset" not in cfg._explicit_keys:
            flow_config = entry_flow_config(entry)

    # skip_steps follows the common precedence: an explicit ecc.toml
    # declaration outranks the manifest entry (the base layer).
    declared = declared_skip_steps(entry, cfg)
    flow_config = _attach_skip_steps(flow_config, declared)
    flow_config = _attach_lec_engine(flow_config, declared_lec_engine(cfg))
    flow_config = attach_insert_steps(flow_config, manifest_synthesis_lec(entry, cfg))
    flow_config = attach_insert_steps(flow_config, declared_insert_steps(cfg))
    # Provenance for inspection surfaces: the winning layer's name.
    if declared is not None:
        cfg._skip_steps_source = (
            "ecc.toml" if "flow.skip_steps" in cfg._explicit_keys else "project.json"
        )

    warnings = []
    shadowed = skip_steps_shadow_warning(entry, cfg)
    if shadowed is not None:
        warnings.append(shadowed)
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

    cfg = ProjectConfig(
        design_name=assembled["design_name"],
        design_top=assembled["top_module"],
        design_rtl=_source_rtl(assembled),
        design_netlist=_source_path(assembled, "netlist", ctx.project_dir),
        design_golden_netlist=_source_path(assembled, "golden_netlist", ctx.project_dir),
        design_def=_source_origin_def(assembled, ctx.project_dir),
        design_sdc=_source_path(assembled, "sdc", ctx.project_dir),
        design_spef=_source_path(assembled, "spef", ctx.project_dir),
        design_clock_port=assembled["clock"],
        design_frequency_mhz=_assembled_frequency(assembled),
        pdk_name=assembled["pdk"],
        pdk_root=assembled["pdk_root"],
        flow_preset="rtl2gds",  # inert: the entry range drives the created range
        project_dir=ctx.project_dir,
    )
    cfg.params_overrides = {}
    cfg.manifest_driven = True
    cfg.manifest_origin_def = _source_origin_def(assembled, ctx.project_dir)

    from .timing_inputs import resolve_timing_input_metadata

    resolve_timing_input_metadata(cfg)

    flow_config = None if entry is None else entry_flow_config(entry)
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


def _source_path(assembled: dict, key: str, project_dir: str) -> str:
    value = assembled.get(key) or ""
    if not value or os.path.isabs(value):
        return value
    return os.path.normpath(os.path.join(project_dir, value))


def _assembled_frequency(assembled: Mapping[str, object]) -> float:
    """The manifest layer's frequency_mhz as a float (0.0 when absent/invalid)."""
    declared = assembled.get("frequency_mhz")
    if not isinstance(declared, int | float | str):
        return 0.0
    try:
        return float(declared or 0)
    except (ValueError, OverflowError):
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
    for dotted, field_name, source_key in (
        ("design.netlist", "design_netlist", "netlist"),
        ("design.golden_netlist", "design_golden_netlist", "golden_netlist"),
        ("design.def", "design_def", "origin_def"),
        ("design.sdc", "design_sdc", "sdc"),
        ("design.spef", "design_spef", "spef"),
    ):
        if dotted not in explicit:
            setattr(cfg, field_name, _source_path(assembled, source_key, project_dir))
    if "pdk.name" not in explicit:
        cfg.pdk_name = assembled["pdk"]
    if "pdk.root" not in explicit:
        cfg.pdk_root = assembled["pdk_root"]
    if "design.frequency_mhz" not in explicit:
        cfg.design_frequency_mhz = _assembled_frequency(assembled)
    # origin_def exists only in the manifest layer (no ecc.toml key), so it
    # always comes from the base — resolved against the project root.
    cfg.manifest_origin_def = _source_origin_def(assembled, project_dir)
    from .timing_inputs import resolve_timing_input_metadata

    resolve_timing_input_metadata(cfg)


def validate_effective(
    ctx, cfg, *, fresh: bool, flow_config, cli_overrides=None, validate_timing_input: bool = True
) -> list[str]:
    """Validate the effective config for a manifest-backed project.

    Relaxations vs legacy projects: [flow] is optional when a target can be
    derived (workspace config for existing runs, entry range for declared
    creation); a multi-entry rtl list is allowed (materialized at
    creation) with every source validated. A fresh run without any
    derivable flow target is an error — before any mutation.

    Existing runs disable project timing-input validation because they use
    frozen workspace inputs. Inspection and fresh creation still validate it.
    """
    from chipcompiler.cli.project import flow_selection
    from chipcompiler.cli.project.config import validate_project_config

    errors = validate_project_config(cfg, validate_timing_input=validate_timing_input)
    # validate_project_config checks the ecc.toml policy on the preset; the
    # run's own flow config (a range or a project.json policy) is checked here.
    if isinstance(flow_config, dict):
        errors.extend(
            error
            for error in flow_selection.selection_errors(cfg, flow_config)
            if error not in errors
        )
    if fresh:
        from chipcompiler.cli.project.design_inputs import validate_entry_inputs

        errors.extend(validate_entry_inputs(cfg, flow_selection.entry_step(cfg, flow_config)))
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
        if fresh and not cfg.flow_preset and not flow_config_selects_steps(flow_config):
            errors.append(
                "no flow target: set flow.preset in ecc.toml or declare the workspace's "
                "start/end range in project.json"
            )
        errors.extend(_manifest_frequency_errors(cfg, cli_overrides))
    return errors


def _manifest_frequency_errors(
    cfg: "ProjectConfig", cli_overrides: Mapping[str, object] | None
) -> list[str]:
    """Registry range errors for a clock frequency that came from the manifest.

    The frequency is the one registry-validated value the manifest still
    supplies; an ecc.toml ``[design]``/``[params]`` value, a ``--set`` value
    or a validated timing-input file takes over the key and is validated there.
    """
    from chipcompiler.params import lookup_schema, validate_value

    key = "design.frequency_mhz"
    overridden = (
        key in cfg._explicit_keys
        or key in (cfg.params_overrides or {})
        or key in (cli_overrides or {})
        or (cfg.design_sdc and not cfg._timing_input_error)
    )
    schema = lookup_schema(key)
    if overridden or schema is None or not cfg.design_frequency_mhz:
        return []
    return [f"project.json: {error}" for error in validate_value(cfg.design_frequency_mhz, schema)]


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

    Paths are normalized against the project root before comparison.
    Presence-keyed like the fill: only keys
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
        # An explicit empty root takes effect through the env fallback (the
        # same resolution a run uses); only a genuinely different effective
        # root diverges from the manifest base.
        effective_root = toml_root or _env_resolved_pdk_root(cfg)
        if effective_root != base_root:
            keys.append("pdk_root")

    # Ordered comparison: source order is execution-significant (filelist
    # compilation order), so a reordered list diverges; duplicates survive.
    base_sources = _normalized_sources(cfg.project_dir, _source_rtl(assembled))
    toml_sources = _normalized_sources(cfg.project_dir, cfg.design_rtl)
    if "design.rtl" in explicit and base_sources != toml_sources:
        keys.append("rtl")

    from chipcompiler.params import lookup_schema, validate_schema_type

    # A [params.design] key supersedes the [design] frequency — the
    # standalone value is inert and must not warn on its own.
    manifest_frequency = assembled.get("frequency_mhz")
    if (
        "design.frequency_mhz" in explicit
        and "design.frequency_mhz" not in cfg.params_overrides
        and manifest_frequency is not None
    ):
        schema = lookup_schema("design.frequency_mhz")
        if schema is None:
            keys.append("frequency_max")
        else:
            coerced, type_err = validate_schema_type(manifest_frequency, schema)
            if type_err or coerced != cfg.design_frequency_mhz:
                keys.append("frequency_max")

    # An explicit valid preset overrides the entry's declared range (GUI
    # range vocabulary on both sides); an unknown preset is left to
    # validation instead of being projected here.
    if "flow.preset" in explicit and entry is not None:
        preset_range = PRESET_MANIFEST_RANGE.get(cfg.flow_preset)
        if preset_range is not None and preset_range != (entry.start_step, entry.end_step):
            keys.append("flow")

    return keys


def _backend_leaf_keys(schema) -> tuple[str, ...]:
    """The flattened backend key names a schema's maps_to target produces."""
    maps_to = schema.maps_to
    # Direct config/PDK parameters are applied through their explicit target
    # and intentionally have no legacy backend projection.
    if maps_to is None:
        return ()
    if isinstance(maps_to, str):
        return (maps_to,)
    return tuple(".".join((subtree, leaf)) for subtree, leaf in maps_to.items())


def _diverging_lower_keys(overrides: dict, resolve_lower) -> tuple[list[str], set[str]]:
    """Per-schema divergences between *overrides* and the layer
    *resolve_lower* supplies.

    *resolve_lower(key)* returns ``(lower_value, present)`` for an override
    key (step-qualified for a step value, ``placement:place.x``): an absent
    lower value cannot diverge, a type-invalid one counts as divergent, and
    a coerced-equal one does not ("false" vs false). Returns (diverging
    backend leaf keys, leaf keys the per-schema pass covered).
    """
    from chipcompiler.data.step_parameters import split_step_key
    from chipcompiler.params import lookup_schema, validate_schema_type

    diverging: list[str] = []
    compared: set[str] = set()
    for dotted, override_value in overrides.items():
        schema = lookup_schema(split_step_key(dotted)[1])
        if schema is None:
            continue
        leaf_keys = _backend_leaf_keys(schema)
        compared.update(leaf_keys)
        lower_value, present = resolve_lower(dotted)
        if not present:
            continue
        coerced, type_err = validate_schema_type(lower_value, schema)
        if type_err or coerced != override_value:
            # Direct config/PDK parameters have no backend leaf key. Keep the
            # warning useful by identifying the canonical parameter instead
            # of silently dropping the divergence or inventing a key.
            diverging.extend(leaf_keys or [dotted])
    return diverging, compared


def cli_divergence_warning(cfg, cli_overrides: dict) -> dict | None:
    """The config_layer_diverged warning for --set values overriding a
    DIFFERENT lower-layer value (ecc.toml [params], then an explicit
    [design] frequency).

    Registry-backed keys compare per schema with type normalization: a
    same-valued differently-typed one ("false" vs false) does not warn.
    Non-registry keys keep the generic flatten comparison, skipping keys
    the per-schema pass covered.
    """
    if not cli_overrides:
        return None
    from chipcompiler.params import build_backend_overrides, resolve_parameters

    explicit = getattr(cfg, "_explicit_keys", frozenset())
    params_overrides = cfg.params_overrides or {}

    def resolve_lower(key):
        if key in params_overrides:
            return params_overrides[key], True
        if key == "design.frequency_mhz" and "design.frequency_mhz" in explicit:
            return cfg.design_frequency_mhz, True
        return None, False

    diverging, compared = _diverging_lower_keys(cli_overrides, resolve_lower)

    lower: dict = {}
    if params_overrides:
        resolved_toml, _ = resolve_parameters(
            toml_overrides=params_overrides, pdk=cfg.pdk_name or None
        )
        lower.update(_flatten(build_backend_overrides(resolved_toml)))
    resolved_cli, _ = resolve_parameters(cli_overrides=cli_overrides, pdk=cfg.pdk_name or None)
    for key, value in _flatten(build_backend_overrides(resolved_cli)):
        if key not in compared and key in lower and lower[key] != value:
            diverging.append(key)
    if not diverging:
        return None
    return warning_record(
        "config_layer_diverged",
        keys=diverging,
        reason="--set values override different lower-layer values",
    )


def _normalize_path(project_dir: str, value) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    if os.path.isabs(value):
        return os.path.normpath(value)
    return os.path.normpath(os.path.join(project_dir, value))


def _env_resolved_pdk_root(cfg) -> str:
    """The env-fallback root an explicit empty ``pdk.root`` actually uses."""
    from chipcompiler.cli.project.config import resolve_pdk_root

    return _normalize_path(cfg.project_dir, resolve_pdk_root(cfg))


def _normalized_sources(project_dir: str, sources: list[str]) -> tuple[str, ...]:
    """Normalized source paths in declaration order, blanks dropped."""
    return tuple(
        normalized for source in sources if (normalized := _normalize_path(project_dir, source))
    )


def _flatten(data, prefix=()):
    for key, value in (data or {}).items():
        if isinstance(value, dict):
            yield from _flatten(value, (*prefix, key))
        else:
            yield ".".join((*prefix, key)), value
