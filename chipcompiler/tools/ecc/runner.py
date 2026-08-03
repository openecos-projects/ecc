#!/usr/bin/env python
import os
import shutil
from pathlib import Path

from chipcompiler.data import EccStep, StateEnum, StepEnum, Workspace, WorkspaceStep
from chipcompiler.tools.ecc.checklist import EccChecklist
from chipcompiler.tools.ecc.metrics import (
    build_step_metrics,
    save_cts_timing_feature_facts,
    save_rcx_spef_feature_facts,
)
from chipcompiler.tools.ecc.module import ECCToolsModule
from chipcompiler.tools.ecc.plot import ECCToolsPlot
from chipcompiler.tools.ecc.sta_qor import sta_artifact_directory
from chipcompiler.tools.ecc.subflow import EccSubFlow, EccSubFlowEnum
from chipcompiler.tools.ecc.utility import is_eda_exist
from chipcompiler.utility import json_read

_GEOMETRY_SNAPSHOT_STEPS = frozenset(
    {
        StepEnum.FLOORPLAN.value,
        StepEnum.NETLIST_OPT.value,
        StepEnum.PLACEMENT.value,
        StepEnum.CTS.value,
        StepEnum.PNP.value,
        StepEnum.TIMING_OPT.value,
        StepEnum.TIMING_OPT_DRV.value,
        StepEnum.TIMING_OPT_HOLD.value,
        StepEnum.TIMING_OPT_SETUP.value,
        StepEnum.LEGALIZATION.value,
        StepEnum.ROUTING.value,
        StepEnum.DRC.value,
        StepEnum.FILLER.value,
        StepEnum.RCX.value,
        StepEnum.STA.value,
    }
)


def temperature_token(temperature) -> str:
    try:
        numeric = float(temperature)
        if numeric.is_integer():
            temperature = int(numeric)
    except (TypeError, ValueError):
        pass
    return str(temperature).replace("-", "m").replace(".", "p")


def copy_rcx_spef_outputs(workspace: Workspace, step: EccStep):
    data_dir_text = os.fspath(step.data.dir or "")
    output_dir_text = os.fspath(step.output.dir or "")
    workspace_dir = workspace.directory
    if not data_dir_text or not output_dir_text or workspace_dir is None:
        return

    data_dir = Path(data_dir_text)
    if data_dir_text.startswith("/"):
        relative_data_dir = data_dir_text[1:]
        if relative_data_dir.split("/", 1)[0] in ("RCX_ecc", "rcx_ecc"):
            data_dir = workspace_dir / relative_data_dir

    output_dir = Path(output_dir_text)
    if output_dir_text.startswith("/"):
        relative_output_dir = output_dir_text[1:]
        if relative_output_dir.split("/", 1)[0] in ("RCX_ecc", "rcx_ecc"):
            output_dir = workspace_dir / relative_output_dir

    spef_writer_dir = data_dir / "spef_writer"
    if not spef_writer_dir.is_dir():
        return

    output_paths = [output_dir / spef_path.name for spef_path in step.output.spef if spef_path]

    if not output_paths:
        output_paths = [
            output_dir / spef_path.name for spef_path in sorted(spef_writer_dir.glob("*.spef"))
        ]

    for output_path in output_paths:
        source_path = spef_writer_dir / output_path.name
        if not source_path.is_file():
            continue

        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, output_path)
        workspace.logger.info("Copied RCX SPEF %s to %s", source_path, output_path)

    if isinstance(step.output.spef, list):
        step.output.spef[:] = output_paths


def collect_sta_signoff_items(workspace: Workspace) -> list[dict]:
    sta_config = workspace.config.get(StepEnum.STA.value, "")
    sta_data = json_read(sta_config)
    workspace_dir = workspace.directory
    if workspace_dir is None:
        return []
    rcx_output_dir = workspace_dir / f"{StepEnum.RCX.value}_ecc" / "output"

    liberty_by_corner = {liberty.get("corner"): liberty for liberty in sta_data.get("liberty", [])}
    spef_design_name = workspace.design.top_module or workspace.design.name
    items = []

    for signoff_group in sta_data.get("signoff", []):
        for corner_name, rcx_corner_names in signoff_group.items():
            liberty = liberty_by_corner.get(corner_name)
            if liberty is None:
                workspace.logger.error(
                    "No liberty corner '%s' found in %s", corner_name, sta_config
                )
                return []

            temperature = liberty.get("temperature")
            liberty_files = liberty.get("path", [])

            for rcx_corner_name in rcx_corner_names:
                spef_name = (
                    f"{spef_design_name}_{rcx_corner_name}_{temperature_token(temperature)}C.spef"
                )
                items.append(
                    {
                        "corner": corner_name,
                        "temperature": temperature,
                        "rcx_corner": rcx_corner_name,
                        "liberty_files": liberty_files,
                        "spef_file": str(rcx_output_dir / spef_name),
                    }
                )

    return items


def create_db_engine(workspace: Workspace, step: WorkspaceStep) -> ECCToolsModule:
    """"""

    def input_path_exists(path: Path | None) -> str | None:
        if not path:
            return None

        path = os.fspath(path)

        gzip_path = path if path.endswith(".gz") else f"{path}.gz"
        plain_path = path[:-3] if path.endswith(".gz") else path

        if os.path.exists(gzip_path):
            return gzip_path
        if os.path.exists(plain_path):
            return plain_path

        return None

    def load_data():
        ecc_module = ECCToolsModule()

        ecc_module.init_config(
            flow_config=workspace.config.get("flow"),
            db_config=workspace.config.get("db"),
            output_dir=step.data.dir,
            feature_dir=step.feature.dir,
        )

        db_path = step.input.db or ""
        if ecc_module.is_db_data_exists(db_path):
            try:
                loaded = ecc_module.load_data(path=db_path)
            except Exception as e:
                workspace.logger.warning(
                    f"Failed to load ECC data from {db_path}; falling back to design input: {e}"
                )
                return None

            if not loaded:
                workspace.logger.warning(
                    f"Failed to load ECC data from {db_path}; falling back to design input."
                )
                return None

            workspace.logger.info(f"Successfully loaded data from {db_path}")
            return ecc_module
        else:
            return None

    def load_design():
        def def_exist() -> str | None:
            return input_path_exists(step.input.def_)

        def verilog_exist() -> str | None:
            return input_path_exists(step.input.verilog)

        ecc_module = ECCToolsModule()

        ecc_module.init_config(
            flow_config=workspace.config.get("flow"),
            db_config=workspace.config.get("db"),
            output_dir=step.data.dir,
            feature_dir=step.feature.dir,
        )

        ecc_module.init_techlef(workspace.pdk.tech)
        ecc_module.init_lefs(workspace.pdk.lefs)

        # if db def exist, read db def
        def_path = def_exist()

        if def_path is not None:
            ecc_module.read_def(def_path)
        else:
            # else, read step output verilog
            verilog_path = verilog_exist()
            if verilog_path:
                ecc_module.read_verilog(
                    verilog=verilog_path, top_module=workspace.design.top_module
                )
            else:
                return None

        return ecc_module

    def is_enable_setup():
        # skip synthesis step
        if step.name == StepEnum.SYNTHESIS.value:
            return False

        return (
            input_path_exists(step.input.def_) is not None
            or input_path_exists(step.input.verilog) is not None
        )

    if not is_eda_exist() or not is_enable_setup():
        return None
    try:
        ecc_module = load_data()
        if ecc_module is None:
            ecc_module = load_design()
    except Exception:
        ecc_module = load_design()

    return ecc_module


def get_eda_instance(
    workspace: Workspace, step: EccStep, ecc_module: ECCToolsModule | None = None
) -> ECCToolsModule | None:
    """
    ecc_module is ecc module from db engine,
    eda instacnce may initialize data from this module if ecc_module has been set
    """
    if ecc_module is None:
        try:
            ecc_module = create_db_engine(workspace=workspace, step=step)
        except Exception as e:
            ecc_module = None
            workspace.logger.error(f"Failed to create ECC engine for step {step.name}: {e}")

    # release sta for some memory leakage issue
    if ecc_module is not None:
        ecc_module.update_step_paths(
            output_dir=step.data.dir or "",
            feature_dir=step.feature.dir or "",
        )

    return ecc_module


def run_sta_without_spef(
    workspace: Workspace, step: WorkspaceStep, ecc_module: ECCToolsModule | None = None
) -> bool:
    """Generate a netlist-level STA report after synthesis.

    STA is supplemental to synthesis, so callers can retain a successful
    synthesis result when this function returns ``False``.
    """
    try:
        netlist_path = step.output.verilog or ""
        liberty_paths = workspace.pdk.libs
        sdc_path = workspace.pdk.sdc
        data_dir = step.data.dir or ""
        report_root = step.report.dir or ""
        feature_root = step.feature.dir or ""

        if not netlist_path or not os.path.isfile(netlist_path):
            raise FileNotFoundError(f"synthesis netlist does not exist: {netlist_path}")

        missing_liberty_paths = [
            liberty_path for liberty_path in liberty_paths if not os.path.isfile(liberty_path)
        ]
        if not liberty_paths or missing_liberty_paths:
            raise FileNotFoundError(
                f"STA liberty files are missing: {missing_liberty_paths or liberty_paths}"
            )

        if not sdc_path or not os.path.isfile(sdc_path):
            raise FileNotFoundError(f"STA SDC does not exist: {sdc_path}")
        if not data_dir or not report_root or not feature_root:
            raise ValueError("synthesis STA data, report, or feature directory is not configured")

        work_dir = Path(data_dir) / "sta"
        work_dir.mkdir(parents=True, exist_ok=True)
        corner = "post_synthesis"
        report_dir = Path(report_root) / corner
        feature_dir = Path(feature_root) / corner

        if ecc_module is None:
            ecc_module = ECCToolsModule()
            ecc_module.init_config(
                flow_config=workspace.config.get("flow", ""),
                db_config=workspace.config.get("db", ""),
                output_dir=step.data.dir or "",
                feature_dir=step.feature.dir or "",
            )
        else:
            ecc_module.update_step_paths(
                output_dir=step.data.dir or "",
                feature_dir=step.feature.dir or "",
            )

        ecc_module.init_techlef(workspace.pdk.tech)
        ecc_module.init_lefs(workspace.pdk.lefs)
        ecc_module.read_verilog(
            verilog=netlist_path,
            top_module=workspace.design.top_module,
        )
        ecc_module.run_timing(
            config=workspace.config.get(StepEnum.STA.value, ""),
            work_dir=work_dir,
            report_dir=report_dir,
            feature_dir=feature_dir,
            lib_paths=liberty_paths,
            sdc_path=sdc_path,
            corner=corner,
        )
    except Exception as exc:
        workspace.logger.warning("Post-synthesis STA failed; synthesis result is kept: %s", exc)
        return False

        workspace.logger.info(
            "Post-synthesis STA artifacts saved to report=%s feature=%s",
            report_dir,
            feature_dir,
        )
    return True


def save_data(
    workspace: Workspace,
    step: EccStep,
    ecc_module: ECCToolsModule,
    *,
    feature_step: bool = True,
    report_timing: bool = False,
) -> bool:
    """
    module is ecc module from db engine,
    eda instacnce may initialize data from this module if module has been set
    """
    if ecc_module is None:
        return False
    ecc_module.def_save(def_path=step.output.def_ or "")
    ecc_module.verilog_save(output_verilog=step.output.verilog or "")
    ecc_module.gds_save(output_path=step.output.gds or "")
    ecc_module.save_data(path=step.output.db or "")
    if step.name in _GEOMETRY_SNAPSHOT_STEPS:
        geometry_dir = step.output.geometry or ""
        geometry_manifest = step.output.geometry_manifest
        if not ecc_module.geometry_snapshot_save(output_dir=geometry_dir):
            workspace.logger.error("Failed to write geometry snapshot for %s", step.name)
            return False
        if geometry_manifest is None or not geometry_manifest.is_file():
            workspace.logger.error(
                "Geometry snapshot manifest is missing for %s: %s",
                step.name,
                geometry_manifest,
            )
            return False
    # View JSON serialization is intentionally skipped. The GUI reads the
    # geometry snapshot generated above instead.
    ecc_module.feature_sammry(json_path=step.feature.db or "")
    if feature_step:
        ecc_module.feature_step(step=step.name, json_path=step.feature.step or "")

    ecc_module.report_summary(path=step.report.db or "")

    if report_timing:
        ecc_module.release_sta()
        ecc_module.init_sta(
            output_dir=(step.data.steps or {}).get("sta", ""),
            top_module=workspace.design.top_module,
            lib_paths=workspace.pdk.libs,
            sdc_path=workspace.pdk.sdc,
        )
        ecc_module.report_timing()
        ecc_module.release_sta()

    # update parameters
    db_json = json_read(step.feature.db or "")
    if len(db_json) > 0:
        from chipcompiler.data.parameter import save_parameter, update_parameters

        die_bounding_width = db_json.get("Design Layout", {}).get("die_bounding_width", 0)
        die_bounding_height = db_json.get("Design Layout", {}).get("die_bounding_height", 0)
        die_area = db_json.get("Design Layout", {}).get("die_area", 0)

        core_bounding_width = db_json.get("Design Layout", {}).get("core_bounding_width", 0)
        core_bounding_height = db_json.get("Design Layout", {}).get("core_bounding_height", 0)
        core_area = db_json.get("Design Layout", {}).get("core_area", 0)

        margin = workspace.parameters.data.get("Core", {}).get("Margin", [0, 0])

        core_usage = db_json.get("Design Layout", {}).get("core_usage", 0)

        aspect_ratio = die_bounding_width / die_bounding_height if die_bounding_height > 0 else 1

        update_param = {
            "Die": {"Size": [die_bounding_width, die_bounding_height], "Area": die_area},
            "Core": {
                "Size": [core_bounding_width, core_bounding_height],
                "Area": core_area,
                "Bounding box": (
                    f"({margin[0]} , {margin[1]}) "
                    f"({core_bounding_width + margin[0]} , {core_bounding_height + margin[1]})"
                ),
                "Utilitization": core_usage,
                "Aspect ratio": aspect_ratio,
            },
        }

        update_parameters(parameters_src=update_param, parameters_target=workspace.parameters.data)
        save_parameter(workspace.parameters)

    return True


def run_step(workspace: Workspace, step: EccStep, ecc_module: ECCToolsModule | None = None) -> bool:
    if not is_eda_exist():
        return StateEnum.Invalid

    state = False
    match step.name:
        case StepEnum.FLOORPLAN.value:
            state = run_floorplan(workspace=workspace, step=step, ecc_module=ecc_module)
        case StepEnum.NETLIST_OPT.value:
            state = run_net_opt(workspace=workspace, step=step, ecc_module=ecc_module)
        case StepEnum.PLACEMENT.value:
            state = run_placement(workspace=workspace, step=step, ecc_module=ecc_module)
        case StepEnum.CTS.value:
            state = run_cts(workspace=workspace, step=step, ecc_module=ecc_module)
        case StepEnum.TIMING_OPT_DRV.value:
            state = run_timing_opt_drv(workspace=workspace, step=step, ecc_module=ecc_module)
        case StepEnum.TIMING_OPT_HOLD.value:
            state = run_timing_opt_hold(workspace=workspace, step=step, ecc_module=ecc_module)
        case StepEnum.LEGALIZATION.value:
            state = run_legalization(workspace=workspace, step=step, ecc_module=ecc_module)
        case StepEnum.ROUTING.value:
            state = run_routing(workspace=workspace, step=step, ecc_module=ecc_module)
        case StepEnum.DRC.value:
            state = run_drc(workspace=workspace, step=step, ecc_module=ecc_module)
        case StepEnum.FILLER.value:
            state = run_filler(workspace=workspace, step=step, ecc_module=ecc_module)
        case StepEnum.HARDEN.value:
            state = run_harden(workspace=workspace, step=step, ecc_module=ecc_module)

        case StepEnum.RCX.value:
            state = run_rcx(workspace=workspace, step=step, ecc_module=ecc_module)
        case StepEnum.STA.value:
            state = run_sta(workspace=workspace, step=step, ecc_module=ecc_module)

    return state


def run_analysis(workspace: Workspace, step: EccStep, subflow: EccSubFlow):
    # save metrics
    build_step_metrics(workspace=workspace, step=step, subflow=subflow)

    # plot layout image
    ploter = ECCToolsPlot(workspace=workspace, step=step)
    ploter.plot()

    # do checklist
    checklist = EccChecklist(workspace=workspace, workspace_step=step)
    checklist.check()


def run_net_opt(
    workspace: Workspace, step: EccStep, ecc_module: ECCToolsModule | None = None
) -> bool:
    """
    run net optimization
    """
    reslut = False

    sub_flow = EccSubFlow(workspace=workspace, workspace_step=step)

    ecc_module = get_eda_instance(workspace=workspace, step=step, ecc_module=ecc_module)
    if ecc_module is not None:
        sub_flow.update_step(step_name=EccSubFlowEnum.load_data.value, state=StateEnum.Success)

        clock_name = workspace.parameters.data.get("Clock", "")
        if clock_name:
            ecc_module.set_net(net_name=clock_name, net_type="CLOCK")
            sub_flow.update_step(
                step_name=EccSubFlowEnum.set_clock_net.value, state=StateEnum.Success
            )

        ecc_module.run_net_opt(config=workspace.config.get(f"{StepEnum.NETLIST_OPT.value}"))

        sub_flow.update_step(
            step_name=EccSubFlowEnum.run_net_optimization.value, state=StateEnum.Success
        )

        reslut = save_data(workspace=workspace, step=step, ecc_module=ecc_module)

        sub_flow.update_step(step_name=EccSubFlowEnum.save_data.value, state=StateEnum.Success)

        run_analysis(workspace=workspace, step=step, subflow=sub_flow)

    return reslut


def run_placement(
    workspace: Workspace, step: EccStep, ecc_module: ECCToolsModule | None = None
) -> bool:
    """
    run placement
    """
    reslut = False

    sub_flow = EccSubFlow(workspace=workspace, workspace_step=step)

    ecc_module = get_eda_instance(workspace=workspace, step=step, ecc_module=ecc_module)

    if ecc_module is not None:
        sub_flow.update_step(step_name=EccSubFlowEnum.load_data.value, state=StateEnum.Success)

        ecc_module.run_placement(config=workspace.config.get(f"{StepEnum.PLACEMENT.value}"))
        ecc_module.feature_placement_map(json_path=step.feature.map or "")

        sub_flow.update_step(step_name=EccSubFlowEnum.run_placement.value, state=StateEnum.Success)

        reslut = save_data(
            workspace=workspace, step=step, ecc_module=ecc_module, report_timing=False
        )

        sub_flow.update_step(step_name=EccSubFlowEnum.save_data.value, state=StateEnum.Success)

        run_analysis(workspace=workspace, step=step, subflow=sub_flow)

    return reslut


def run_cts(workspace: Workspace, step: EccStep, ecc_module: ECCToolsModule | None = None) -> bool:
    """
    run CTS
    """
    reslut = False

    sub_flow = EccSubFlow(workspace=workspace, workspace_step=step)

    ecc_module = get_eda_instance(workspace=workspace, step=step, ecc_module=ecc_module)

    if ecc_module is not None:
        sub_flow.update_step(step_name=EccSubFlowEnum.load_data.value, state=StateEnum.Success)

        ecc_module.run_cts(
            config=workspace.config.get(f"{StepEnum.CTS.value}", ""),
            output=(step.data.steps or {}).get(StepEnum.CTS.value, ""),
        )

        ecc_module.report_cts(output=(step.data.steps or {}).get(StepEnum.CTS.value, ""))

        ecc_module.feature_cts_map(json_path=step.feature.map or "")

        sub_flow.update_step(step_name=EccSubFlowEnum.run_CTS.value, state=StateEnum.Success)

        reslut = save_data(workspace=workspace, step=step, ecc_module=ecc_module)
        if not save_cts_timing_feature_facts(step, ecc_module.feature_cts_timing()):
            workspace.logger.error("Failed to persist CTS timing feature facts")
            return False

        sub_flow.update_step(step_name=EccSubFlowEnum.save_data.value, state=StateEnum.Success)

        run_analysis(workspace=workspace, step=step, subflow=sub_flow)

    return reslut


def run_timing_opt_drv(
    workspace: Workspace, step: EccStep, ecc_module: ECCToolsModule | None = None
) -> bool:
    """
    run timing optization drv
    """
    reslut = False

    sub_flow = EccSubFlow(workspace=workspace, workspace_step=step)

    ecc_module = get_eda_instance(workspace=workspace, step=step, ecc_module=ecc_module)

    ecc_module = get_eda_instance(workspace=workspace, step=step, ecc_module=ecc_module)

    if ecc_module is not None:
        sub_flow.update_step(step_name=EccSubFlowEnum.load_data.value, state=StateEnum.Success)

        ecc_module.run_timing_opt_drv(
            config=workspace.config.get(f"{StepEnum.TIMING_OPT_DRV.value}", "")
        )

        sub_flow.update_step(
            step_name=EccSubFlowEnum.run_timing_opt_drv.value, state=StateEnum.Success
        )

        reslut = save_data(workspace=workspace, step=step, ecc_module=ecc_module)

        sub_flow.update_step(step_name=EccSubFlowEnum.save_data.value, state=StateEnum.Success)

        run_analysis(workspace=workspace, step=step, subflow=sub_flow)

    return reslut


def run_timing_opt_hold(
    workspace: Workspace, step: EccStep, ecc_module: ECCToolsModule | None = None
) -> bool:
    """
    run timing optization hold
    """
    reslut = False

    sub_flow = EccSubFlow(workspace=workspace, workspace_step=step)

    ecc_module = get_eda_instance(workspace=workspace, step=step, ecc_module=ecc_module)

    if ecc_module is not None:
        sub_flow.update_step(step_name=EccSubFlowEnum.load_data.value, state=StateEnum.Success)

        ecc_module.run_timing_opt_hold(
            config=workspace.config.get(f"{StepEnum.TIMING_OPT_HOLD.value}", "")
        )

        sub_flow.update_step(
            step_name=EccSubFlowEnum.run_timing_opt_hold.value, state=StateEnum.Success
        )

        reslut = save_data(workspace=workspace, step=step, ecc_module=ecc_module)

        sub_flow.update_step(step_name=EccSubFlowEnum.save_data.value, state=StateEnum.Success)

        run_analysis(workspace=workspace, step=step, subflow=sub_flow)

    return reslut


def run_routing(
    workspace: Workspace, step: EccStep, ecc_module: ECCToolsModule | None = None
) -> bool:
    """
    run routing
    """
    reslut = False

    sub_flow = EccSubFlow(workspace=workspace, workspace_step=step)

    ecc_module = get_eda_instance(workspace=workspace, step=step, ecc_module=ecc_module)

    if ecc_module is not None:
        sub_flow.update_step(step_name=EccSubFlowEnum.load_data.value, state=StateEnum.Success)

        if ecc_module.is_rt_timing_enable(
            config=workspace.config.get(f"{StepEnum.ROUTING.value}", "")
        ):
            ecc_module.release_sta()
            ecc_module.init_sta(
                output_dir=(step.data.steps or {}).get(StepEnum.ROUTING.value, ""),
                top_module=workspace.design.top_module,
                lib_paths=workspace.pdk.libs,
                sdc_path=workspace.pdk.sdc,
            )

        ecc_module.run_routing(config=workspace.config.get(f"{StepEnum.ROUTING.value}", ""))

        sub_flow.update_step(step_name=EccSubFlowEnum.run_routing.value, state=StateEnum.Success)

        reslut = save_data(
            workspace=workspace, step=step, ecc_module=ecc_module, report_timing=False
        )

        sub_flow.update_step(step_name=EccSubFlowEnum.save_data.value, state=StateEnum.Success)

        run_analysis(workspace=workspace, step=step, subflow=sub_flow)

    return reslut


def run_drc(workspace: Workspace, step: EccStep, ecc_module: ECCToolsModule | None = None) -> bool:
    """
    run chip drc
    """
    reslut = False

    sub_flow = EccSubFlow(workspace=workspace, workspace_step=step)

    ecc_module = get_eda_instance(workspace=workspace, step=step, ecc_module=ecc_module)

    if ecc_module is not None:
        sub_flow.update_step(step_name=EccSubFlowEnum.load_data.value, state=StateEnum.Success)

        ecc_module.init_drc(output_dir=(step.data.steps or {}).get(StepEnum.DRC.value, ""))
        ecc_module.run_drc(
            config=workspace.config.get(f"{StepEnum.DRC.value}", ""),
            report_path=step.report.step or "",
        )

        sub_flow.update_step(step_name=EccSubFlowEnum.run_DRC.value, state=StateEnum.Success)

        reslut = save_data(
            workspace=workspace, step=step, ecc_module=ecc_module, report_timing=False
        )

        ecc_module.save_drc(feature_path=step.feature.step or "")

        sub_flow.update_step(step_name=EccSubFlowEnum.save_data.value, state=StateEnum.Success)

        run_analysis(workspace=workspace, step=step, subflow=sub_flow)

        sub_flow.update_step(step_name=EccSubFlowEnum.save_data.value, state=StateEnum.Success)

    return reslut


def run_legalization(
    workspace: Workspace, step: EccStep, ecc_module: ECCToolsModule | None = None
) -> bool:
    """
    run placement legalization
    """
    reslut = False

    sub_flow = EccSubFlow(workspace=workspace, workspace_step=step)

    ecc_module = get_eda_instance(workspace=workspace, step=step, ecc_module=ecc_module)

    if ecc_module is not None:
        sub_flow.update_step(step_name=EccSubFlowEnum.load_data.value, state=StateEnum.Success)

        ecc_module.run_legalize(config=workspace.config.get(f"{StepEnum.LEGALIZATION.value}", ""))

        sub_flow.update_step(
            step_name=EccSubFlowEnum.run_legalization.value, state=StateEnum.Success
        )

        reslut = save_data(
            workspace=workspace, step=step, ecc_module=ecc_module, report_timing=False
        )

        sub_flow.update_step(step_name=EccSubFlowEnum.save_data.value, state=StateEnum.Success)

        run_analysis(workspace=workspace, step=step, subflow=sub_flow)

    return reslut


def run_filler(
    workspace: Workspace, step: EccStep, ecc_module: ECCToolsModule | None = None
) -> bool:
    """
    run placement filler
    """
    reslut = False

    sub_flow = EccSubFlow(workspace=workspace, workspace_step=step)

    ecc_module = get_eda_instance(workspace=workspace, step=step, ecc_module=ecc_module)

    if ecc_module is not None:
        sub_flow.update_step(step_name=EccSubFlowEnum.load_data.value, state=StateEnum.Success)

        ecc_module.run_filler(config=workspace.config.get(f"{StepEnum.FILLER.value}", ""))

        sub_flow.update_step(step_name=EccSubFlowEnum.run_filler.value, state=StateEnum.Success)

        reslut = save_data(
            workspace=workspace, step=step, ecc_module=ecc_module, report_timing=False
        )

        sub_flow.update_step(step_name=EccSubFlowEnum.save_data.value, state=StateEnum.Success)

        run_analysis(workspace=workspace, step=step, subflow=sub_flow)

    return reslut


def run_floorplan(
    workspace: Workspace, step: EccStep, ecc_module: ECCToolsModule | None = None
) -> bool:
    """
    run floorplan
    """
    reslut = False
    sub_flow = EccSubFlow(workspace=workspace, workspace_step=step)

    ecc_module = get_eda_instance(workspace=workspace, step=step, ecc_module=ecc_module)

    if ecc_module is not None:
        sub_flow.update_step(step_name=EccSubFlowEnum.load_data.value, state=StateEnum.Success)

        ecc_module.init_fp(config=workspace.config.get(StepEnum.FLOORPLAN.value, ""))
        sub_flow.update_step(step_name=EccSubFlowEnum.init_floorplan.value, state=StateEnum.Success)

        ecc_module.run_fp()
        sub_flow.update_step(step_name=EccSubFlowEnum.create_tracks.value, state=StateEnum.Success)
        sub_flow.update_step(step_name=EccSubFlowEnum.place_io_pins.value, state=StateEnum.Success)
        sub_flow.update_step(step_name=EccSubFlowEnum.tap_cell.value, state=StateEnum.Success)
        sub_flow.update_step(step_name=EccSubFlowEnum.PDN.value, state=StateEnum.Success)

        ecc_module.destroy_fp()
        sub_flow.update_step(step_name=EccSubFlowEnum.set_clock_net.value, state=StateEnum.Success)

        reslut = save_data(
            workspace=workspace,
            step=step,
            ecc_module=ecc_module,
            feature_step=False,
            report_timing=False,
        )

        sub_flow.update_step(step_name=EccSubFlowEnum.save_data.value, state=StateEnum.Success)

        run_analysis(workspace=workspace, step=step, subflow=sub_flow)

    return reslut


def run_harden(
    workspace: Workspace, step: EccStep, ecc_module: ECCToolsModule | None = None
) -> bool:
    """
    run harden, save design as Lef Macro and extract lib
    """
    reslut = False

    sub_flow = EccSubFlow(workspace=workspace, workspace_step=step)

    ecc_module = get_eda_instance(workspace=workspace, step=step, ecc_module=ecc_module)

    if ecc_module is not None:
        sub_flow.update_step(step_name=EccSubFlowEnum.load_data.value, state=StateEnum.Success)

        signoff_items = collect_sta_signoff_items(workspace)
        if not signoff_items:
            workspace.logger.error("No signoff STA items found")
            return False
        signoff_item = signoff_items[0]

        ecc_module.write_abstract_lef(output_lef_path=step.output.lef or "")
        ecc_module.write_timing_model(
            output_lib_path=step.output.lib or "",
            config=workspace.config.get(StepEnum.STA.value, ""),
            output_dir=(step.data.steps or {}).get(StepEnum.STA.value, ""),
            lib_paths=signoff_item["liberty_files"],
            sdc_path=workspace.pdk.sdc,
            spef_path=signoff_item["spef_file"],
            design_name=workspace.design.name,
        )
        ecc_module.gds_save(output_path=step.output.gds or "", is_harden=True)

        sub_flow.update_step(step_name=EccSubFlowEnum.run_harden.value, state=StateEnum.Success)

        run_analysis(workspace=workspace, step=step, subflow=sub_flow)
        reslut = True

    return reslut


def run_rcx(workspace: Workspace, step: EccStep, ecc_module: ECCToolsModule | None = None) -> bool:
    """
    run rcx
    """
    result = False

    sub_flow = EccSubFlow(workspace=workspace, workspace_step=step)

    ecc_module = get_eda_instance(workspace=workspace, step=step, ecc_module=ecc_module)

    if ecc_module is not None:
        sub_flow.update_step(step_name=EccSubFlowEnum.load_data.value, state=StateEnum.Success)

        ecc_module.init_rcx(
            config=workspace.config.get(StepEnum.RCX.value, ""), pdk=workspace.pdk.name
        )
        ecc_module.run_rcx()
        ecc_module.destroy_rcx()
        copy_rcx_spef_outputs(workspace, step)
        sub_flow.update_step(step_name=EccSubFlowEnum.run_rcx.value, state=StateEnum.Success)

        save_data(
            workspace=workspace,
            step=step,
            ecc_module=ecc_module,
            feature_step=False,
            report_timing=False,
        )
        if not save_rcx_spef_feature_facts(workspace=workspace, step=step):
            workspace.logger.error("Failed to persist RCX SPEF feature facts")
            return False

        sub_flow.update_step(step_name=EccSubFlowEnum.save_data.value, state=StateEnum.Success)

        run_analysis(workspace=workspace, step=step, subflow=sub_flow)
        result = True

    return result


def run_sta(workspace: Workspace, step: EccStep, ecc_module: ECCToolsModule | None = None) -> bool:
    """
    run sta
    """
    result = False

    sub_flow = EccSubFlow(workspace=workspace, workspace_step=step)

    ecc_module = get_eda_instance(workspace=workspace, step=step, ecc_module=ecc_module)

    if ecc_module is None:
        return result

    sub_flow.update_step(step_name=EccSubFlowEnum.load_data.value, state=StateEnum.Success)

    signoff_items = collect_sta_signoff_items(workspace)
    if not signoff_items:
        workspace.logger.error("No signoff STA items found")
        sub_flow.update_step(step_name=EccSubFlowEnum.run_sta.value, state=StateEnum.Imcomplete)
        return False

    if not os.path.exists(workspace.pdk.sdc):
        workspace.logger.error("STA SDC does not exist: %s", workspace.pdk.sdc)
        sub_flow.update_step(step_name=EccSubFlowEnum.run_sta.value, state=StateEnum.Imcomplete)
        return False

    for signoff_item in signoff_items:
        corner_name = signoff_item["corner"]
        temperature = signoff_item["temperature"]
        rcx_corner_name = signoff_item["rcx_corner"]
        liberty_files = signoff_item["liberty_files"]
        spef_file = signoff_item["spef_file"]

        if not os.path.exists(spef_file):
            workspace.logger.error(
                "STA SPEF does not exist for %s/%s at %sC: %s",
                corner_name,
                rcx_corner_name,
                temperature,
                spef_file,
            )
            sub_flow.update_step(step_name=EccSubFlowEnum.run_sta.value, state=StateEnum.Imcomplete)
            return False

        missing_liberty_files = [
            lib_path for lib_path in liberty_files if not os.path.exists(lib_path)
        ]
        if len(liberty_files) <= 0 or missing_liberty_files:
            workspace.logger.error(
                "STA liberty does not exist for %s: %s; missing: %s",
                corner_name,
                liberty_files,
                missing_liberty_files,
            )
            sub_flow.update_step(step_name=EccSubFlowEnum.run_sta.value, state=StateEnum.Imcomplete)
            return False

        report_dir = sta_artifact_directory(
            step.report.dir or "",
            corner_name,
            temperature,
            rcx_corner_name,
        )
        feature_dir = sta_artifact_directory(
            step.feature.dir or "",
            corner_name,
            temperature,
            rcx_corner_name,
        )
        if report_dir is None or feature_dir is None:
            workspace.logger.error(
                "STA report or feature directory is not configured for %s/%s",
                corner_name,
                rcx_corner_name,
            )
            sub_flow.update_step(step_name=EccSubFlowEnum.run_sta.value, state=StateEnum.Imcomplete)
            return False

        corner = f"{report_dir.parent.name}/{report_dir.name}"

        ecc_module.run_timing(
            config=workspace.config.get(StepEnum.STA.value, ""),
            work_dir=(step.data.steps or {}).get(StepEnum.STA.value, ""),
            report_dir=report_dir,
            feature_dir=feature_dir,
            lib_paths=liberty_files,
            sdc_path=workspace.pdk.sdc,
            spef_path=spef_file,
            output_modes=("report", "structured"),
            corner=corner,
        )

        workspace.logger.info(
            "STA artifacts for %s/%s at %sC saved to report=%s feature=%s",
            corner_name,
            rcx_corner_name,
            temperature,
            report_dir,
            feature_dir,
        )

    sub_flow.update_step(step_name=EccSubFlowEnum.run_sta.value, state=StateEnum.Success)

    result = save_data(
        workspace=workspace,
        step=step,
        ecc_module=ecc_module,
        feature_step=False,
        report_timing=False,
    )

    sub_flow.update_step(step_name=EccSubFlowEnum.save_data.value, state=StateEnum.Success)

    run_analysis(workspace=workspace, step=step, subflow=sub_flow)
    return result
