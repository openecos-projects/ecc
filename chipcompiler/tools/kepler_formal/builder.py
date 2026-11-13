#!/usr/bin/env python
from collections.abc import Sequence
from pathlib import Path

import yaml

from chipcompiler.data import (
    AnalysisPaths,
    ChecklistState,
    KeplerFormalData,
    KeplerFormalInput,
    KeplerFormalReport,
    KeplerFormalStep,
    LogPaths,
    OutputPaths,
    ScriptPaths,
    SubflowState,
    Workspace,
)
from chipcompiler.data.step import new_step_directory
from chipcompiler.data.types import StepEnum
from chipcompiler.tools.lec_result import build_lec_step_space, derive_golden_path, optional_path
from chipcompiler.utility.path import require_path


def checks_rtl(step: KeplerFormalStep) -> bool:
    """Whether *step* is ``lec@Synthesis``: its golden is the RTL Synthesis read.

    Every other LEC compares two netlists.
    """
    from chipcompiler.rtl2gds import inserted_step_name

    return step.name == inserted_step_name(StepEnum.LEC.value, StepEnum.SYNTHESIS.value)


def golden_kind(workspace: Workspace, step: KeplerFormalStep) -> str:
    """What *step*'s golden is (``lec_result.GOLDEN_KINDS``).

    ``lec@Synthesis`` reads the RTL Synthesis read: its filelist (``rtl_filelist``)
    or its RTL file (``rtl``); every other LEC a netlist.
    """
    if not checks_rtl(step):
        return "netlist"
    from chipcompiler.tools.yosys.builder import synthesis_reads_filelist

    golden = step.input.golden_verilog
    return "rtl_filelist" if golden and synthesis_reads_filelist(workspace, golden) else "rtl"


def sec_rtl_filelist(step: KeplerFormalStep) -> Path:
    """The filelist kepler-formal reads the ``lec@Synthesis`` RTL from."""
    return require_path(step.data.dir, "kepler-formal data directory") / "rtl.f"


def sec_rtl_filelist_text(rtl: Path | str, defines: Sequence[str], *, filelist: bool) -> str:
    """The :func:`sec_rtl_filelist` content for the RTL Synthesis read.

    It defines the macros Synthesis's frontend defines (*defines*, see
    ``tools.yosys.builder.synthesis_defines``): an ``ifdef SYNTHESIS`` or
    ``ifdef YOSYS`` design must not prove another branch than the one
    synthesized. A filelist is nested with ``-F``, so its relative sources and
    ``+incdir+`` resolve against its own directory as in Synthesis, not
    against the step directory kepler-formal runs in.
    """
    entry = f'"{Path(rtl).absolute()}"'
    if filelist:
        entry = f"-F {entry}"
    return "".join(f"+define+{macro}\n" for macro in defines) + f"{entry}\n"


def build_step(
    workspace: Workspace,
    step_name: str,
    input_def: Path | None,
    input_verilog: Path | None,
    input_db: Path | str | None = None,
    output_def: Path | None = None,
    output_verilog: Path | None = None,
    output_gds: Path | None = None,
    *,
    step_directory: Path | None = None,
) -> KeplerFormalStep:
    directory = step_directory or Path(workspace.directory) / new_step_directory(
        step_name, "kepler_formal"
    )
    output_dir = directory / "output"
    data_dir = directory / "data"
    report_dir = directory / "report"
    gate_verilog = optional_path(input_verilog)
    golden_verilog = optional_path(input_db) or derive_golden_path(gate_verilog)

    return KeplerFormalStep(
        name=step_name,
        tool="kepler_formal",
        version="0.1",
        directory=directory,
        input=KeplerFormalInput(
            gate_verilog=gate_verilog,
            golden_verilog=golden_verilog,
            db=optional_path(input_db),
        ),
        output=OutputPaths(
            dir=output_dir,
            json=output_dir / f"{workspace.design.name}_{step_name}_result.json",
        ),
        data=KeplerFormalData(dir=data_dir, config=data_dir / "lec_config.yaml"),
        report=KeplerFormalReport(
            dir=report_dir,
            status=report_dir / "run_lec_status.rpt",
            equiv_status=report_dir / "equiv_status.rpt",
            miter_log=report_dir / "miter_log.txt",
        ),
        log=LogPaths(
            dir=directory / "log",
            file=directory / "log" / f"{step_name}.log",
        ),
        script=ScriptPaths(
            dir=directory / "script",
            main=directory / "script" / "run_lec.yaml",
        ),
        analysis=AnalysisPaths(
            dir=directory / "analysis",
            metrics=directory / "analysis" / f"{step_name}_metrics.json",
        ),
        subflow=SubflowState(path=directory / "subflow.json", steps=[]),
        checklist=ChecklistState(path=directory / "checklist.json", checklist=[]),
    )


def build_step_space(step: KeplerFormalStep) -> None:
    build_lec_step_space(step)


def build_lec_config_yaml(
    workspace: Workspace,
    step: KeplerFormalStep,
    *,
    golden_verilog: Path | str | None = None,
    gate_verilog: Path | str | None = None,
) -> str:
    """The kepler-formal YAML config for this step.

    design1 is the golden and design2 the gate netlist; kepler-formal reports
    equivalence of design2 against design1. Two netlists are compared
    combinationally (``lec``). For ``lec@Synthesis`` (:func:`checks_rtl`)
    design1 is the RTL, read through :func:`sec_rtl_filelist` by
    kepler-formal's SystemVerilog front end, which it supports only for
    sequential equivalence (``sv2v`` format, ``sec``). The explicit path
    arguments override the step inputs so the runner can point kepler-formal
    at prepared (decompressed / physical-cell-stripped) copies.
    """
    top_module = workspace.design.top_module
    liberty_files = [str(path) for path in (workspace.pdk.libs or []) if path]
    golden = str(golden_verilog or step.input.golden_verilog or "")
    gate = str(gate_verilog or step.input.gate_verilog or "")

    if checks_rtl(step):
        config = {
            "format": "sv2v",
            "verification": "sec",
            "input_paths": [[], [gate]],
            "sv_design1_flist": str(sec_rtl_filelist(step)),
            "sv_design1_top": top_module,
            "verilog_design2_top": top_module,
            "liberty_files": liberty_files,
            "log_file": str(step.report.miter_log or ""),
        }
    else:
        config = {
            "format": "verilog",
            "verification": "lec",
            "input_paths": [[golden], [gate]],
            "verilog_design1_top": top_module,
            "verilog_design2_top": top_module,
            "liberty_files": liberty_files,
            "log_file": str(step.report.miter_log or ""),
        }
    return yaml.safe_dump(config, default_flow_style=False, sort_keys=False)


def build_step_config(workspace: Workspace, step: KeplerFormalStep) -> None:
    write_step_config(workspace, step)
    from chipcompiler.tools.kepler_formal.subflow import KeplerFormalSubFlow

    subflow = KeplerFormalSubFlow(workspace=workspace, workspace_step=step)
    subflow.build_sub_flow()


def write_step_config(
    workspace: Workspace,
    step: KeplerFormalStep,
    *,
    golden_verilog: Path | str | None = None,
    gate_verilog: Path | str | None = None,
) -> None:
    if checks_rtl(step):
        from chipcompiler.tools.yosys.builder import synthesis_defines, synthesis_reads_filelist

        rtl = require_path(golden_verilog or step.input.golden_verilog, "RTL")
        sec_rtl_filelist(step).write_text(
            sec_rtl_filelist_text(
                rtl,
                synthesis_defines(workspace, rtl),
                filelist=synthesis_reads_filelist(workspace, rtl),
            ),
            encoding="utf-8",
        )
    config = (
        "# Auto-generated by kepler_formal.builder - DO NOT EDIT MANUALLY\n"
        + build_lec_config_yaml(
            workspace, step, golden_verilog=golden_verilog, gate_verilog=gate_verilog
        )
    )
    require_path(step.data.config, "kepler-formal config").write_text(config, encoding="utf-8")
