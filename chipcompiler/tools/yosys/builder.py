#!/usr/bin/env python
import os
import stat
from contextlib import suppress
from pathlib import Path

from rosettakit import tcl

from chipcompiler.data import (
    AnalysisPaths,
    ChecklistState,
    LogPaths,
    ScriptPaths,
    StepInput,
    SubflowState,
    Workspace,
    WorkspaceStep,
    YosysData,
    YosysFeature,
    YosysOutput,
    YosysReport,
    YosysStep,
)
from chipcompiler.utility import json_read


def _abspath(path: Path | str | None) -> str:
    """Convert path to absolute path, handling empty strings."""
    if not path:
        return ""
    return os.path.abspath(path)


def _existing_unique_paths(paths: list[Path]) -> list[str]:
    """Return existing paths in input order without duplicates."""
    unique_paths = []
    seen = set()

    for path in paths:
        if not path or not path.is_file():
            continue
        abs_path = os.path.abspath(path)
        if abs_path in seen:
            continue
        unique_paths.append(abs_path)
        seen.add(abs_path)

    return unique_paths


def _workspace_libs(workspace: Workspace) -> list[Path]:
    """Read extra liberty files from the workspace DB config."""
    db_config = json_read(workspace.config.get("db", ""))
    lib_paths = db_config.get("INPUT", {}).get("lib_path", [])
    if isinstance(lib_paths, str):
        lib_paths = [lib_paths]
    if not isinstance(lib_paths, list):
        return []

    return [Path(path) for path in lib_paths if path]


def _plain_verilog_filelist_paths(filelist: str) -> list[str] | None:
    """Return plain Verilog sources when a filelist needs no Slang features."""
    try:
        lines = Path(filelist).read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    sources = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        if line.startswith(("+", "-", "@")):
            return None
        source = Path(line.strip('"'))
        if not source.is_absolute():
            source = Path(filelist).parent / source
        if source.suffix.lower() != ".v" or not source.is_file():
            return None
        sources.append(str(source.resolve()))

    return sources or None


def _yosys_source_config(workspace: Workspace, step: WorkspaceStep) -> tuple[bool, list[str], str]:
    """Classify RTL input as native-Verilog or Slang-required."""
    filelist = workspace.design.input_filelist or workspace.parameters.data.get("File list", "")
    if filelist and os.path.exists(filelist):
        plain_sources = _plain_verilog_filelist_paths(filelist)
        if plain_sources is not None:
            return False, plain_sources, ""
        return True, [], filelist

    rtl_file = step.input.verilog or ""
    if rtl_file and os.path.exists(rtl_file) and Path(rtl_file).suffix.lower() == ".v":
        return False, [os.path.abspath(rtl_file)], ""
    return True, [], ""


def generate_global_var_tcl(workspace: Workspace, step: YosysStep) -> str:
    """Generate global_var.tcl content dynamically from workspace configuration."""
    if not workspace.design.top_module:
        raise ValueError("TOP_NAME (workspace.design.top_module) not set")

    freq_mhz = workspace.parameters.data.get("Frequency max [MHz]")
    if freq_mhz is None:
        raise ValueError("CLK_FREQ_MHZ (Frequency max [MHz]) not set")
    if not isinstance(freq_mhz, (int, float)) or freq_mhz <= 0:
        raise ValueError(f"CLK_FREQ_MHZ must be positive number, got {freq_mhz}")

    rtl_file = step.input.verilog or ""
    filelist = (
        workspace.design.input_filelist
        if workspace.design.input_filelist
        else workspace.parameters.data.get("File list", "")
    )

    # Prefer filelist if available, otherwise use rtl_file --- IGNORE ---
    has_valid_filelist = filelist and os.path.exists(filelist)
    has_valid_rtl = rtl_file and os.path.exists(rtl_file)

    if not has_valid_filelist and not has_valid_rtl:
        raise ValueError(f"Neither RTL_FILE ({rtl_file}) nor filelist ({filelist}) exists")

    top_design = workspace.design.top_module
    clk_freq_mhz = (
        int(freq_mhz) if isinstance(freq_mhz, float) and freq_mhz.is_integer() else freq_mhz
    )

    # Convert all paths to absolute since Yosys runs in script/ subdirectory
    netlist_file = _abspath(step.output.verilog or "")
    netlist_sim_file = _abspath(step.output.sim_verilog or "")
    timing_cell_stat_rpt = _abspath(step.report.stat)
    timing_cell_count_rpt = _abspath(step.report.check)
    generic_stat_json = _abspath(step.report.stat)
    synth_stat_json = _abspath(step.feature.stat)
    synth_check_rpt = _abspath(step.report.check)
    data_dir = _abspath(step.data.dir)

    keep_hierarchy = "false"

    pdk = workspace.pdk
    dont_use_cells = pdk.dont_use if pdk.dont_use else []

    tie_low_cell = pdk.tie_low_cell if pdk.tie_low_cell else ""
    tie_low_port = pdk.tie_low_port if pdk.tie_low_port else ""
    tie_high_cell = pdk.tie_high_cell if pdk.tie_high_cell else ""
    tie_high_port = pdk.tie_high_port if pdk.tie_high_port else ""
    abc_driver_cell = pdk.abc_driver_cell if pdk.abc_driver_cell else "BUFX4H7L"
    abc_load = pdk.abc_load if pdk.abc_load else 0.015

    lib_stdcell_paths = workspace.pdk.libs if workspace.pdk.libs else []
    workspace_lib_paths = _workspace_libs(workspace)
    lib_stdcell = _existing_unique_paths(lib_stdcell_paths)
    lib_files = _existing_unique_paths(lib_stdcell_paths + workspace_lib_paths)

    script = tcl.Script()
    script.comment("Auto-generated by builder.py - DO NOT EDIT MANUALLY")
    script.comment("Generated configuration for Yosys synthesis")
    script.comment(f"Timestamp: {os.popen('date').read().strip()}")
    script.blank_line()
    script.set("top_design", tcl.word(top_design))
    script.set("clk_freq_mhz", clk_freq_mhz)
    script.blank_line()

    use_slang, native_rtl_files, slang_filelist = _yosys_source_config(workspace, step)
    step.data.requires_slang = use_slang

    script.set("use_slang", "true" if use_slang else "false")
    if use_slang and slang_filelist:
        script.comment("RTL source files (from filelist)")
        script.set_path("filelist", _abspath(slang_filelist))
    else:
        script.comment("RTL source files")
        script.set_list("rtl_file", native_rtl_files or [_abspath(rtl_file)])
    script.blank_line()

    script.comment("Output files")
    script.set_path("final_netlist_file", netlist_file)
    script.set_path("final_netlist_sim_file", netlist_sim_file)
    script.set_path("timing_cell_stat_rpt", timing_cell_stat_rpt)
    script.set_path("timing_cell_count_rpt", timing_cell_count_rpt)
    script.set_path("generic_stat_json", generic_stat_json)
    script.set_path("synth_stat_json", synth_stat_json)
    script.set_path("synth_check_rpt", synth_check_rpt)
    script.blank_line()

    script.comment("Synthesis options")
    script.set("keep_hierarchy", keep_hierarchy)
    script.blank_line()

    script.comment("Cell configurations")
    script.set_list("dont_use_cells", dont_use_cells)
    script.set("tie_low_cell", tcl.word(tie_low_cell))
    script.set("tie_low_port", tcl.word(tie_low_port))
    script.set("tie_high_cell", tcl.word(tie_high_cell))
    script.set("tie_high_port", tcl.word(tie_high_port))
    script.set("abc_driver_cell", tcl.word(abc_driver_cell))
    script.set("abc_load", abc_load)
    script.blank_line()

    script.comment("Library files")
    script.set_list("lib_stdcell_list", lib_stdcell)
    script.set_list("lib_list", lib_files)
    script.blank_line()

    script.comment("Working directories")
    script.set_path("tmp_dir", os.path.join(data_dir, "tmp"))
    script.blank_line()
    script.comment("##############")
    script.blank_line()

    script.comment("Calculate clock period in picoseconds")
    script.set_expr("clk_period_ps", "1000000.0 / $clk_freq_mhz")
    script.blank_line()

    script.comment("Create directories")
    script.file_mkdir(tcl.var("tmp_dir"))
    script.set("stat_dir", tcl.call("file", "dirname", tcl.var("synth_stat_json")))
    with script.if_not(tcl.file_isdirectory(tcl.var("stat_dir"))):
        script.file_mkdir(tcl.var("stat_dir"))

    return script.build()


def build_step(
    workspace: Workspace,
    step_name: str,
    input_def: Path | None,
    input_verilog: Path | None,
    input_db: Path | str | None = None,
    output_def: Path | None = None,
    output_verilog: Path | None = None,
    output_gds: Path | None = None,
) -> YosysStep:
    """
    Build the synthesis step in the specified workspace.

    Note: input_def is not used for synthesis, only input_verilog (RTL).
    Synthesis doesn't produce DEF; output_def points to verilog for flow compatibility.
    """
    design = workspace.design.name
    directory = Path(workspace.directory) / f"{step_name}_yosys"
    output_dir = directory / "output"
    data_dir = directory / "data"

    return YosysStep(
        name=step_name,
        tool="yosys",
        version="0.1",
        directory=directory,
        input=StepInput(verilog=Path(input_verilog) if input_verilog else None),
        output=YosysOutput(
            dir=output_dir,
            def_=Path(output_def) if output_def else output_dir / f"{design}_{step_name}.def.gz",
            verilog=(
                Path(output_verilog)
                if output_verilog
                else output_dir / f"{design}_{step_name}.v.gz"
            ),
            sim_verilog=output_dir / f"{design}_{step_name}_sim.v.gz",
            json=output_dir / f"{design}_{step_name}.json",
            report=output_dir / f"{design}_{step_name}.rpt",
            image=output_dir / f"{design}_{step_name}.png",
        ),
        data=YosysData(dir=data_dir, tmp=data_dir / "tmp"),
        feature=YosysFeature(
            dir=directory / "feature",
            step=directory / "feature" / f"{step_name}.step.json",
            generic_stat=directory / "feature" / f"{step_name}_generic_stat.json",
            stat=directory / "feature" / f"{step_name}_stat.json",
        ),
        report=YosysReport(
            dir=directory / "report",
            stat=directory / "report" / f"{step_name}_stat.json",
            check=directory / "report" / f"{step_name}_check.rpt",
        ),
        log=LogPaths(
            dir=directory / "log",
            file=directory / "log" / f"{step_name}.log",
        ),
        script=ScriptPaths(
            dir=directory / "script",
            main=directory / "script" / f"{step_name}_main.tcl",
        ),
        analysis=AnalysisPaths(
            dir=directory / "analysis",
            metrics=directory / "analysis" / "qor_metrics.json",
            qor_metrics=directory / "analysis" / "qor_metrics.json",
            qor_summary=directory / "analysis" / "qor_summary.json",
            qor_hotspots=directory / "analysis" / "qor_hotspots.json",
        ),
        subflow=SubflowState(path=directory / "subflow.json", steps=[]),
        checklist=ChecklistState(path=directory / "checklist.json", checklist=[]),
    )


def build_step_space(step: YosysStep) -> None:
    """
    Create the workspace directories for the given step.
    """
    step_directory = Path(step.directory)
    step_directory.mkdir(parents=True, exist_ok=True)
    Path(step.output.dir or step_directory / "output").mkdir(parents=True, exist_ok=True)
    Path(step.data.dir or step_directory / "data").mkdir(parents=True, exist_ok=True)
    Path(step.data.tmp or step_directory / "data" / "tmp").mkdir(parents=True, exist_ok=True)
    Path(step.report.dir or step_directory / "report").mkdir(parents=True, exist_ok=True)
    Path(step.log.dir or step_directory / "log").mkdir(parents=True, exist_ok=True)
    Path(step.script.dir or step_directory / "script").mkdir(parents=True, exist_ok=True)
    Path(step.feature.dir or step_directory / "feature").mkdir(parents=True, exist_ok=True)
    Path(step.analysis.dir or step_directory / "analysis").mkdir(parents=True, exist_ok=True)


def build_step_config(workspace: Workspace, step: YosysStep):
    """
    Build the configuration files for the synthesis step.

    Creates the following directory structure:
    - script/ subdirectory with all prepared TCL scripts
    - data/ subdirectory with generated files
    """
    import shutil

    def _copy_writable(src: Path, dst: Path):
        """Copy file and ensure it's writable."""
        shutil.copy2(src, dst)
        with suppress(OSError):
            os.chmod(dst, os.stat(dst).st_mode | stat.S_IWUSR)

    current_dir = Path(__file__).resolve().parent
    scripts_dir = current_dir / "scripts"
    script_dir = Path(step.script.dir) if step.script.dir else Path(step.directory or "")

    for file in ["yosys_synthesis.tcl", "init_tech.tcl"]:
        src = scripts_dir / file
        if src.exists():
            _copy_writable(src, script_dir / file)

    abc_script = scripts_dir / "abc-opt.script"
    if abc_script.exists():
        _copy_writable(abc_script, script_dir / "abc-opt.script")

    configs_dir = current_dir / "configs"
    aig_file = configs_dir / "lazy_man_synth_library.aig"
    if aig_file.exists():
        _copy_writable(aig_file, script_dir / "lazy_man_synth_library.aig")

    try:
        tcl_content = generate_global_var_tcl(workspace, step)
        data_dir = step.data.dir or Path(step.directory or "") / "data"
        global_var_path = data_dir / "global_var.tcl"
        with global_var_path.open("w") as f:
            f.write(tcl_content)
    except (ValueError, OSError) as e:
        print(f"Error generating global_var.tcl: {e}")
        raise

    # build subflow json
    build_sub_flow(workspace=workspace, workspace_step=step)

    build_checklist(workspace=workspace, workspace_step=step)


def build_sub_flow(workspace: Workspace, workspace_step: YosysStep):
    from .subflow import YosysSubFlow

    subflow = YosysSubFlow(workspace=workspace, workspace_step=workspace_step)

    subflow.build_sub_flow()


def build_checklist(workspace: Workspace, workspace_step: YosysStep):
    from .checklist import YosysChecklist

    checklist = YosysChecklist(workspace=workspace, workspace_step=workspace_step)

    checklist.build_checklist()


def build_environment(workspace: Workspace, step: YosysStep):
    """
    Build the environment for the given step.
    """
    pass
