"""Design-input contracts declared by a project's ``ecc.toml``.

The workspace owns copied inputs after creation. This module is deliberately
limited to resolving the project declarations and validating the files needed
by the first requested flow step; it never writes step configuration files.
"""

import os
from dataclasses import dataclass

from chipcompiler.utility.filelist import FILELIST_SUFFIXES, RTL_SUFFIXES


@dataclass(frozen=True)
class ResolvedDesignInputs:
    rtl: tuple[str, ...] = ()
    netlist: str = ""
    golden_netlist: str = ""
    def_: str = ""
    sdc: str = ""
    spef: str = ""


_PHYSICAL_STEPS = frozenset(
    {
        "place",
        "CTS",
        "legalization",
        "Timing optimization",
        "route",
        "filler",
        "RCX",
        "drc",
        "lvs",
        "Harden",
    }
)


def required_inputs_for_step(step: str) -> tuple[str, ...]:
    """Return the declared ``[design]`` fields required to enter *step*."""
    from chipcompiler.rtl2gds import normalize_flow_step

    canonical = normalize_flow_step(step)
    if canonical == "Synthesis":
        return ("rtl",)
    if canonical in {"lec", "postRouteLec"}:
        return ("netlist", "golden_netlist")
    if canonical == "Floorplan":
        return ("netlist",)
    if canonical == "sta":
        return ("def", "netlist", "spef")
    if canonical in _PHYSICAL_STEPS:
        return ("def", "netlist")
    return ()


def resolve_design_inputs(cfg) -> ResolvedDesignInputs:
    """Resolve declared input paths against the project root."""
    from chipcompiler.cli.project.config import _resolve_path

    def resolve(value: str) -> str:
        return _resolve_path(cfg.project_dir, value) if value else ""

    return ResolvedDesignInputs(
        rtl=tuple(resolve(value) for value in cfg.design_rtl),
        netlist=resolve(getattr(cfg, "design_netlist", "")),
        golden_netlist=resolve(getattr(cfg, "design_golden_netlist", "")),
        def_=resolve(getattr(cfg, "design_def", "")),
        sdc=resolve(getattr(cfg, "design_sdc", "")),
        spef=resolve(getattr(cfg, "design_spef", "")),
    )


def validate_entry_inputs(cfg, entry_step: str | None) -> list[str]:
    """Validate only files needed by the requested entry step.

    Optional SDC is checked when explicitly declared because it is copied into
    the workspace instead of generating a default constraint file.
    """
    if not entry_step:
        return []
    resolved = resolve_design_inputs(cfg)
    values = {
        "rtl": resolved.rtl,
        "netlist": resolved.netlist,
        "golden_netlist": resolved.golden_netlist,
        "def": resolved.def_,
        "sdc": resolved.sdc,
        "spef": resolved.spef,
    }
    errors: list[str] = []
    for field_name in required_inputs_for_step(entry_step):
        value = values[field_name]
        if field_name == "rtl":
            if not value:
                errors.append("step_input_missing: Synthesis requires design.rtl")
                continue
            errors.extend(_validate_rtl_sources(value))
            continue
        if not value:
            errors.append(f"step_input_missing: {entry_step} requires design.{field_name}")
            continue
        errors.extend(_validate_file(field_name, value))

    if getattr(cfg, "design_sdc", ""):
        errors.extend(_validate_file("sdc", resolved.sdc))
    return errors


def _validate_rtl_sources(paths: tuple[str, ...]) -> list[str]:
    errors: list[str] = []
    for path in paths:
        errors.extend(_validate_file("rtl", path))
        if errors:
            continue
        suffix = os.path.splitext(path)[1].lower()
        if suffix in FILELIST_SUFFIXES:
            from chipcompiler.utility.filelist import validate_filelist

            try:
                _, missing = validate_filelist(path)
            except (OSError, ValueError) as exc:
                errors.append(f"invalid filelist {path}: {exc}")
            else:
                if missing:
                    errors.append(f"filelist references missing files: {', '.join(missing)}")
        elif suffix not in RTL_SUFFIXES:
            errors.append(f"unsupported rtl source suffix: {path}")
    return errors


def _validate_file(field_name: str, path: str) -> list[str]:
    if not os.path.exists(path):
        return [f"step_input_missing: design.{field_name} does not exist: {path}"]
    if os.path.isdir(path):
        return [f"step_input_missing: design.{field_name} must be a file: {path}"]
    return []
