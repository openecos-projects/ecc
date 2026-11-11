import math
import shutil
from collections.abc import Sequence
from pathlib import Path

from chipcompiler.data import EccStep, SkippableStepEnum, StepEnum, Workspace, step_storage_name
from chipcompiler.tools.ecc import builder as ecc_builder
from chipcompiler.tools.ecc.timing_constraints import step_tcl_path
from chipcompiler.utility import json_read

from .utility import find_sizer_root

SIZER_STAGING_DEF_NAME = "sizer.def.gz"
SIZER_STAGING_VERILOG_NAME = "sizer.v.gz"
SIZER_SETUP_STAGING_DEF_NAME = "sizer_setup.def.gz"
SIZER_SETUP_STAGING_VERILOG_NAME = "sizer_setup.v.gz"
SIZER_HOLD_ENV_NAME = "hold.env_file"
SIZER_HOLD_CMD_NAME = "hold.cmd_file"
SIZER_HOLD_RC_NAME = "hold.rc_file"


def step_shape(
    workspace: Workspace,
    step_name: str,
    output_def: Path | None = None,
    output_verilog: Path | None = None,
) -> tuple[Path, Path, Path]:
    """Canonical sizer step directory and default outputs.

    Dependency-free (no rosettakit import at module scope of this module's
    callers) so deferred creation and selected creation share one shape.
    """
    safe_step_name = step_storage_name(step_name, "sizer")
    step_directory = Path(workspace.directory) / f"{safe_step_name}_sizer"
    if output_def is None:
        output_def = step_directory / "output" / f"{workspace.design.name}_{safe_step_name}.def.gz"
    if output_verilog is None:
        output_verilog = (
            step_directory / "output" / f"{workspace.design.name}_{safe_step_name}.v.gz"
        )
    return step_directory, output_def, output_verilog


def deferred_step(
    workspace: Workspace,
    step_name: str,
    input_def: Path | None,
    input_verilog: Path | None,
    input_db: Path | str | None,
    output_def: Path | None = None,
    output_verilog: Path | None = None,
) -> EccStep:
    """Path-only sizer step for deferred creation (no config files)."""
    step_directory, output_def, output_verilog = step_shape(
        workspace, step_name, output_def, output_verilog
    )
    return ecc_builder.build_step(
        workspace=workspace,
        step_name=step_name,
        input_def=input_def,
        input_verilog=input_verilog,
        input_db=input_db,
        output_def=output_def,
        output_verilog=output_verilog,
        tool="sizer",
        step_directory=step_directory,
    )


def build_step(
    workspace: Workspace,
    step_name: str,
    input_def: Path | None,
    input_verilog: Path | None,
    input_db: Path | str | None = None,
    output_def: Path | None = None,
    output_verilog: Path | None = None,
    output_gds: Path | None = None,
) -> EccStep:
    step_directory, output_def, output_verilog = step_shape(
        workspace, step_name, output_def, output_verilog
    )

    step = ecc_builder.build_step(
        workspace=workspace,
        step_name=step_name,
        input_def=input_def,
        input_verilog=input_verilog,
        input_db=input_db,
        output_def=output_def,
        output_verilog=output_verilog,
        output_gds=output_gds,
        tool="sizer",
        step_directory=step_directory,
    )
    script_dir = step.script.dir or step_directory / "script"
    step.script.sizer_env = script_dir / f"{workspace.design.name}.env_file"
    step.script.sizer_cmd = script_dir / f"{workspace.design.name}.cmd_file"
    if step_name == StepEnum.PREPLACE.value:
        step.output.db = None
    step.script.sizer_hold_env = script_dir / SIZER_HOLD_ENV_NAME
    step.script.sizer_hold_cmd = script_dir / SIZER_HOLD_CMD_NAME
    return step


def build_step_space(step: EccStep) -> None:
    ecc_builder.build_step_space(step)


def build_sub_flow(workspace: Workspace, workspace_step: EccStep) -> None:
    from .subflow import SizerSubFlow

    subflow = SizerSubFlow(workspace=workspace, workspace_step=workspace_step)
    subflow.build_sub_flow()


def build_checklist(workspace: Workspace, workspace_step: EccStep) -> None:
    from .checklist import SizerChecklist

    checklist = SizerChecklist(workspace=workspace, workspace_step=workspace_step)
    checklist.build_checklist()


def _copy_or_seed_template(template: Path | None, target: Path, fallback: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if template and template.exists():
        shutil.copy2(template, target)
        return

    with target.open("w", encoding="utf-8") as file:
        file.write(fallback)


def _append_text(path: Path, text: str) -> None:
    with path.open("a", encoding="utf-8") as file:
        file.write(text)


def _sizer_env_template() -> Path | None:
    sizer_root = find_sizer_root()
    if sizer_root is None:
        return None

    submit_dir = sizer_root / "submit"
    return submit_dir / "env_base_file"


def _tech_text(workspace: Workspace, libs: Sequence[Path] | None = None) -> str:
    sizer_root = find_sizer_root()
    from rosettakit import cmdfile

    env = cmdfile.CommandFile(prefix="-", dialect=cmdfile.PLAIN_DIALECT)
    env.option("lef", workspace.pdk.tech, value_type=cmdfile.ValueType.PATH, omit_empty=True)
    env.options("lef", workspace.pdk.lefs, value_type=cmdfile.ValueType.PATH)
    env.options(
        "lib",
        workspace.pdk.libs if libs is None else libs,
        value_type=cmdfile.ValueType.PATH,
    )

    if sizer_root is not None:
        tcl_path = sizer_root / "src" / "sizer_os.tcl"
        env.option("tclFile", str(tcl_path), value_type=cmdfile.ValueType.PATH)
    return env.build()


def _append_route_layer_options(command, workspace: Workspace) -> None:
    bottom = workspace.parameters.data.get("bottom_layer", "")
    top = workspace.parameters.data.get("top_layer", "")

    if bottom:
        command.option("min_route_layer", bottom)
    if top:
        command.option("max_route_layer", top)


def _placement_wire_rc(workspace: Workspace) -> tuple[str, float, float] | None:
    """Read the optional placement wire RC pair from the hold-stage config."""
    sizer_config = workspace.config.get("sizer")
    if not sizer_config or not Path(sizer_config).is_file():
        return None

    config = json_read(sizer_config)
    hold_stage = config.get("hold_stage", config)
    if not isinstance(hold_stage, dict):
        raise ValueError("sizer hold_stage must be an object")
    config = hold_stage
    placement_config = config.get("placement_wire_rc", config)
    if not isinstance(placement_config, dict):
        raise ValueError("sizer hold_stage placement_wire_rc must be an object")
    config = placement_config
    corner = str(
        config.get("corner", config.get("placement_wire_rc_corner", "MIN_m40/Cbest"))
    ).strip()
    if not corner:
        raise ValueError("sizer placement wire RC corner must be non-empty")
    resistance = config.get(
        "resistance_ohm_per_um", config.get("placement_wire_resistance_ohm_per_um")
    )
    capacitance = config.get(
        "capacitance_pf_per_um", config.get("placement_wire_capacitance_pf_per_um")
    )
    if resistance is None and capacitance is None:
        return None
    if resistance is None or capacitance is None:
        raise ValueError(
            "sizer placement wire resistance and capacitance must be configured together"
        )
    try:
        resistance = float(resistance)
        capacitance = float(capacitance)
    except (TypeError, ValueError) as error:
        raise ValueError("sizer placement wire RC values must be numeric") from error
    if not math.isfinite(resistance) or resistance <= 0:
        raise ValueError("sizer placement wire resistance must be positive and finite")
    if not math.isfinite(capacitance) or capacitance <= 0:
        raise ValueError("sizer placement wire capacitance must be positive and finite")
    return corner, resistance, capacitance


def _append_placement_wire_rc_options(command, workspace: Workspace) -> None:
    placement_wire_rc = _placement_wire_rc(workspace)
    if placement_wire_rc is None:
        return
    corner, resistance, capacitance = placement_wire_rc
    command.option("placement_wire_rc_corner", corner)
    command.option("placement_wire_resistance_ohm_per_um", resistance)
    command.option("placement_wire_capacitance_pf_per_um", capacitance)


def _hold_stage_config(workspace: Workspace) -> dict:
    sizer_config = workspace.config.get("sizer")
    if not sizer_config or not Path(sizer_config).is_file():
        return {}
    config = json_read(sizer_config)
    hold_stage = config.get("hold_stage", config)
    if not isinstance(hold_stage, dict):
        raise ValueError("sizer hold_stage must be an object")
    return hold_stage


def _hold_rc_mode(workspace: Workspace) -> str:
    config = _hold_stage_config(workspace)
    default_mode = "global_routing" if "global_routing_rc" in config else "placement"
    mode = str(config.get("rc_mode", default_mode)).strip()
    if mode not in ("global_routing", "placement"):
        raise ValueError("sizer hold_stage rc_mode must be global_routing or placement")
    return mode


def _global_routing_rc(workspace: Workspace) -> tuple[str, dict, dict]:
    config = _hold_stage_config(workspace)
    raw = config.get("global_routing_rc", {})
    if not isinstance(raw, dict):
        raise ValueError("sizer hold_stage global_routing_rc must be an object")
    corner = str(raw.get("corner", "MIN_m40/Cbest")).strip()
    layers = raw.get("layers", {})
    vias = raw.get("vias", {})
    if not corner or not isinstance(layers, dict) or not isinstance(vias, dict):
        raise ValueError("sizer global_routing_rc requires corner, layers and vias")
    if not layers:
        raise ValueError("sizer global_routing_rc.layers must not be empty")
    for name, value in layers.items():
        if not isinstance(name, str) or not isinstance(value, dict):
            raise ValueError("sizer global_routing_rc layer entries must be objects")
        try:
            resistance = float(value["resistance_ohm_per_um"])
            capacitance = float(value["capacitance_pf_per_um"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"invalid RC values for global routing layer {name}") from error
        if not math.isfinite(resistance) or resistance <= 0:
            raise ValueError(f"global routing layer {name} resistance must be positive")
        if not math.isfinite(capacitance) or capacitance <= 0:
            raise ValueError(f"global routing layer {name} capacitance must be positive")
    for name, value in vias.items():
        if not isinstance(name, str) or not isinstance(value, dict):
            raise ValueError("sizer global_routing_rc via entries must be objects")
        try:
            resistance = float(value["resistance_ohm"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"invalid RC value for global routing via {name}") from error
        if not math.isfinite(resistance) or resistance <= 0:
            raise ValueError(f"global routing via {name} resistance must be positive")
    return corner, layers, vias


def sizer_hold_rc(step: EccStep) -> Path:
    script_dir = step.script.dir
    if script_dir is None:
        raise ValueError("sizer step is missing script directory")
    return Path(script_dir) / SIZER_HOLD_RC_NAME


def _hold_rc_text(workspace: Workspace) -> str:
    corner, layers, vias = _global_routing_rc(workspace)
    lines = [f"# source corner: {corner}"]
    for name, value in layers.items():
        # CX55 Liberty declares pulling_resistance_unit as 1kohm and
        # capacitive_load_unit as 1pf. The config keeps physical RC units;
        # set_layer_rc consumes the Liberty UI units.
        resistance_command = float(value["resistance_ohm_per_um"]) / 1000.0
        capacitance_command = float(value["capacitance_pf_per_um"])
        lines.append(
            "set_layer_rc -layer "
            f"{name} -resistance {resistance_command:.12g} "
            f"-capacitance {capacitance_command:.12g}"
        )
    for name, value in vias.items():
        resistance_command = float(value["resistance_ohm"]) / 1000.0
        lines.append(f"set_layer_rc -via {name} -resistance {resistance_command:.12g}")
    return "\n".join(lines) + "\n"


def sizer_staging_def(step: EccStep) -> Path:
    workdir = step.data.workdir_for(step.name)
    if workdir is None:
        raise ValueError("sizer step is missing a Timing optimization workdir")
    return Path(workdir) / SIZER_STAGING_DEF_NAME


def sizer_staging_verilog(step: EccStep) -> Path:
    workdir = step.data.workdir_for(step.name)
    if workdir is None:
        raise ValueError("sizer step is missing a Timing optimization workdir")
    return Path(workdir) / SIZER_STAGING_VERILOG_NAME


def sizer_setup_staging_def(step: EccStep) -> Path:
    workdir = step.data.workdir_for(step.name)
    if workdir is None:
        raise ValueError("sizer step is missing a Timing optimization workdir")
    return Path(workdir) / SIZER_SETUP_STAGING_DEF_NAME


def sizer_setup_staging_verilog(step: EccStep) -> Path:
    workdir = step.data.workdir_for(step.name)
    if workdir is None:
        raise ValueError("sizer step is missing a Timing optimization workdir")
    return Path(workdir) / SIZER_SETUP_STAGING_VERILOG_NAME


def min_corner_libs(workspace: Workspace) -> list[Path]:
    """Return the MIN/FF Liberty set declared by the final STA contract.

    Paths are consumed verbatim: workspace configuration already anchors
    sta_ecc.json liberty paths under the PDK root, the same contract every
    other sta_ecc.json reader relies on.
    """
    config_path = workspace.config.get(StepEnum.STA.value)
    sta_config = json_read(config_path) if config_path else {}
    for liberty in sta_config.get("liberty", []):
        if str(liberty.get("corner", "")).upper() == "MIN":
            return [Path(raw_path) for raw_path in liberty.get("path", [])]
    return []


def _cmd_text(workspace: Workspace, step: EccStep) -> str:
    from rosettakit import cmdfile

    command = cmdfile.CommandFile(prefix="-", dialect=cmdfile.PLAIN_DIALECT)

    command.flag("useOpenSTA")
    command.option("use_gr_rc", int(step.name == SkippableStepEnum.TIMING_OPT.value))
    if step.name == StepEnum.PREPLACE.value:
        command.flag("preplace")
    command.option("top", workspace.design.top_module or workspace.design.name)
    command.option(
        "def",
        step.input.def_ or "",
        value_type=cmdfile.ValueType.PATH,
        omit_empty=True,
    )
    command.option(
        "v",
        step.input.verilog or "",
        value_type=cmdfile.ValueType.PATH,
        omit_empty=True,
    )
    command.option(
        "sdc",
        step_tcl_path(workspace, step),
        value_type=cmdfile.ValueType.PATH,
        omit_empty=True,
    )
    command.option("outputPath", ".")
    command.option(
        "def_out_path",
        sizer_staging_def(step).resolve(),
        value_type=cmdfile.ValueType.PATH,
    )
    command.option(
        "verilog_out_path",
        sizer_staging_verilog(step).resolve(),
        value_type=cmdfile.ValueType.PATH,
    )
    _append_route_layer_options(command, workspace)
    return command.build()


def _hold_cmd_text(workspace: Workspace, step: EccStep) -> str:
    from rosettakit import cmdfile

    command = cmdfile.CommandFile(prefix="-", dialect=cmdfile.PLAIN_DIALECT)
    command.flag("useOpenSTA")
    rc_mode = _hold_rc_mode(workspace)
    command.option("use_gr_rc", int(rc_mode == "global_routing"))
    command.option("top", workspace.design.top_module or workspace.design.name)
    command.option(
        "def",
        sizer_setup_staging_def(step),
        value_type=cmdfile.ValueType.PATH,
    )
    command.option(
        "v",
        sizer_setup_staging_verilog(step),
        value_type=cmdfile.ValueType.PATH,
    )
    command.option(
        "sdc",
        step_tcl_path(workspace, step),
        value_type=cmdfile.ValueType.PATH,
        omit_empty=True,
    )
    command.option("outputPath", ".")
    command.option(
        "def_out_path",
        sizer_staging_def(step).resolve(),
        value_type=cmdfile.ValueType.PATH,
    )
    command.option(
        "verilog_out_path",
        sizer_staging_verilog(step).resolve(),
        value_type=cmdfile.ValueType.PATH,
    )
    _append_route_layer_options(command, workspace)
    hold_margin = 0.04
    hold_stage = _hold_stage_config(workspace)
    if hold_stage:
        configured = hold_stage.get("hold_margin", hold_margin)
        hold_margin = float(configured)
    if hold_margin < 0:
        raise ValueError("sizer hold_margin must be non-negative")
    command.option("hold_margin", hold_margin)
    if rc_mode == "placement":
        _append_placement_wire_rc_options(command, workspace)
    command.flag("hold_only")
    return command.build()


def build_hold_config(workspace: Workspace, step: EccStep, libs: Sequence[Path]) -> None:
    """Write the FF/MIN hold-only Sizer scripts for *step*."""
    env_path = step.script.sizer_hold_env
    cmd_path = step.script.sizer_hold_cmd
    if env_path is None or cmd_path is None:
        raise ValueError("sizer step is missing script env/cmd paths")

    env_template = _sizer_env_template()
    _copy_or_seed_template(env_template, Path(env_path), "-num_vt 1\n")
    _append_text(Path(env_path), _tech_text(workspace, libs=libs))
    Path(cmd_path).parent.mkdir(parents=True, exist_ok=True)
    rc_path = sizer_hold_rc(step)
    if _hold_rc_mode(workspace) == "global_routing":
        rc_path.write_text(_hold_rc_text(workspace), encoding="utf-8")
        _append_text(Path(env_path), f"-setRCFile {rc_path.resolve()}\n")
    else:
        rc_path.unlink(missing_ok=True)
    Path(cmd_path).write_text(_hold_cmd_text(workspace, step), encoding="utf-8")


def clear_hold_config(step: EccStep) -> None:
    """Remove stale hold-pass scripts when no MIN corner is declared."""
    for path in (step.script.sizer_hold_env, step.script.sizer_hold_cmd):
        if path is not None:
            Path(path).unlink(missing_ok=True)
    if step.script.dir is not None:
        (Path(step.script.dir) / SIZER_HOLD_RC_NAME).unlink(missing_ok=True)


def build_step_config(workspace: Workspace, step: EccStep) -> None:
    env_template = _sizer_env_template()
    env_path = step.script.sizer_env
    cmd_path = step.script.sizer_cmd
    if env_path is None or cmd_path is None:
        raise ValueError("sizer step is missing script env/cmd paths")

    _copy_or_seed_template(env_template, env_path, "-num_vt 1\n")
    Path(cmd_path).parent.mkdir(parents=True, exist_ok=True)
    with Path(cmd_path).open("w", encoding="utf-8"):
        pass

    _append_text(env_path, _tech_text(workspace))
    _append_text(cmd_path, _cmd_text(workspace, step))

    hold_libs = min_corner_libs(workspace)
    if hold_libs:
        build_hold_config(workspace, step, hold_libs)
    else:
        clear_hold_config(step)

    build_sub_flow(workspace=workspace, workspace_step=step)
    build_checklist(workspace=workspace, workspace_step=step)
