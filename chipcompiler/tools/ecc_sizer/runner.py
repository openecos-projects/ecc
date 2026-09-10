import logging
import os
import shutil
import subprocess
from pathlib import Path

from chipcompiler.data import EccOutput, EccStep, StateEnum, Workspace
from chipcompiler.tools.ecc import runner as ecc_runner
from chipcompiler.tools.ecc_dreamplace.runner import legalize_layout
from chipcompiler.tools.ecc_dreamplace.utility import is_eda_exist as is_dreamplace_exist

from .builder import sizer_staging_def, sizer_staging_verilog
from .subflow import SizerSubFlow, SizerSubFlowEnum
from .utility import get_sizer_command, is_eda_exist, is_sizer_runtime_exist

logger = logging.getLogger(__name__)


def _has_staging_outputs(step: EccStep) -> bool:
    return os.path.exists(sizer_staging_def(step)) and os.path.exists(sizer_staging_verilog(step))


def _published_paths(step: EccStep) -> list[Path]:
    output = step.output
    if not isinstance(output, EccOutput):
        return []

    candidates = [
        output.def_,
        output.verilog,
        output.gds,
        output.db,
        output.geometry,
        output.geometry_manifest,
        output.image,
        output.json,
        output.view_json,
        output.view_json_edits,
        output.lef,
        output.lib,
        step.feature.db,
        step.feature.step,
        step.feature.map,
        step.report.db,
        step.report.step,
    ]
    return [Path(value) for value in candidates if value]


def _delete_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def _delete_published_outputs(step: EccStep) -> None:
    errors: list[OSError] = []
    for path in _published_paths(step):
        try:
            _delete_path(path)
        except OSError as exc:
            logger.warning("Failed to delete Timing Opt artifact %s", path, exc_info=True)
            errors.append(exc)
    if errors:
        raise errors[0]


def _delete_staging_outputs(step: EccStep) -> None:
    _delete_path(sizer_staging_def(step))
    _delete_path(sizer_staging_verilog(step))


def _publish_passthrough_outputs(step: EccStep) -> bool:
    """Copy input DEF/Verilog to step outputs (no-clock timing-opt degrade)."""
    input_def = step.input.def_ or ""
    input_verilog = step.input.verilog or ""
    output_def = step.output.def_ or ""
    output_verilog = step.output.verilog or ""
    if not input_def or not os.path.isfile(input_def):
        logger.error("Timing Opt passthrough missing input DEF: %s", input_def)
        return False
    if not input_verilog or not os.path.isfile(input_verilog):
        logger.error("Timing Opt passthrough missing input Verilog: %s", input_verilog)
        return False
    if not output_def or not output_verilog:
        logger.error("Timing Opt passthrough missing output paths")
        return False
    os.makedirs(os.path.dirname(output_def), exist_ok=True)
    shutil.copy2(input_def, output_def)
    shutil.copy2(input_verilog, output_verilog)
    # Engine success contract for Timing Opt includes a geometry manifest when
    # the step declares one; passthrough does not run ecc geometry export.
    geometry_manifest = getattr(step.output, "geometry_manifest", None)
    if geometry_manifest is not None:
        geometry_dir = getattr(step.output, "geometry", None)
        if geometry_dir:
            Path(geometry_dir).mkdir(parents=True, exist_ok=True)
        Path(geometry_manifest).parent.mkdir(parents=True, exist_ok=True)
        Path(geometry_manifest).write_text("schema=ecc.geometry.v1\n", encoding="utf-8")
    return True


def run_step(
    workspace: Workspace,
    step: EccStep,
    ecc_module: object | None = None,
) -> StateEnum:
    del ecc_module

    from chipcompiler.data.workspace import workspace_no_clock

    sub_flow = SizerSubFlow(workspace=workspace, workspace_step=step)
    run_sizer_step = SizerSubFlowEnum.run_sizer.value
    run_legalization_step = SizerSubFlowEnum.run_legalization.value
    save_data_step = SizerSubFlowEnum.save_data.value

    sub_flow.reset_stages()
    _delete_published_outputs(step)

    if workspace_no_clock(workspace):
        logger.info(
            "No-clock workspace: skipping OpenSTA sizing for %s; copying DEF/Verilog through",
            step.name,
        )
        sub_flow.update_step(step_name=run_sizer_step, state=StateEnum.Ongoing)
        if not _publish_passthrough_outputs(step):
            sub_flow.update_step(step_name=run_sizer_step, state=StateEnum.Imcomplete)
            return StateEnum.Imcomplete
        sub_flow.update_step(step_name=run_sizer_step, state=StateEnum.Success)
        sub_flow.update_step(step_name=run_legalization_step, state=StateEnum.Success)
        sub_flow.update_step(step_name=save_data_step, state=StateEnum.Success)
        return StateEnum.Success

    if not is_eda_exist() or not is_sizer_runtime_exist():
        logger.error("Sizer tools not available for step %s", step.name)
        sub_flow.update_step(step_name=run_sizer_step, state=StateEnum.Invalid)
        return StateEnum.Invalid

    if not is_dreamplace_exist():
        logger.error("DreamPlace tools not available for inner legalization of %s", step.name)
        sub_flow.update_step(step_name=run_legalization_step, state=StateEnum.Invalid)
        return StateEnum.Invalid

    env_path = step.script.sizer_env or ""
    cmd_path = step.script.sizer_cmd or ""
    if not os.path.exists(env_path) or not os.path.exists(cmd_path):
        logger.error(
            "Sizer script paths missing for step %s: env=%s cmd=%s",
            step.name,
            env_path,
            cmd_path,
        )
        sub_flow.update_step(step_name=run_sizer_step, state=StateEnum.Invalid)
        return StateEnum.Invalid

    output_dir = step.data.workdir_for(step.name) or ""
    os.makedirs(output_dir, exist_ok=True)
    log_path = step.log.file or ""
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    os.makedirs(os.path.dirname(step.output.def_ or ""), exist_ok=True)
    _delete_staging_outputs(step)
    sub_flow.update_step(step_name=run_sizer_step, state=StateEnum.Ongoing)

    command = get_sizer_command() + ["-env", str(env_path), "-f", str(cmd_path)]
    result = subprocess.run(
        command,
        cwd=str(output_dir),
        stdout=None,
        stderr=subprocess.STDOUT,
        check=False,
    )

    if result.returncode != 0 or not _has_staging_outputs(step):
        logger.error(
            "Sizer failed for step %s: exit code=%d, staging present=%s",
            step.name,
            result.returncode,
            _has_staging_outputs(step),
        )
        sub_flow.update_step(step_name=run_sizer_step, state=StateEnum.Imcomplete)
        return StateEnum.Imcomplete

    sub_flow.update_step(step_name=run_sizer_step, state=StateEnum.Success)
    sub_flow.update_step(step_name=run_legalization_step, state=StateEnum.Ongoing)

    ecc = legalize_layout(
        workspace,
        step,
        sizer_staging_def(step),
        sizer_staging_verilog(step),
    )
    published = False
    try:
        if ecc is None:
            sub_flow.update_step(step_name=run_legalization_step, state=StateEnum.Imcomplete)
            return StateEnum.Imcomplete

        sub_flow.update_step(step_name=run_legalization_step, state=StateEnum.Success)
        sub_flow.update_step(step_name=save_data_step, state=StateEnum.Ongoing)
        try:
            saved = ecc_runner.save_data(
                workspace=workspace,
                step=step,
                ecc_module=ecc,
                feature_step=False,
            )
        except Exception:
            logger.exception("Failed to publish Timing Opt outputs for %s", step.name)
            saved = False
        if not saved:
            sub_flow.update_step(step_name=save_data_step, state=StateEnum.Imcomplete)
            return StateEnum.Imcomplete

        published = True
        sub_flow.update_step(step_name=save_data_step, state=StateEnum.Success)
        return StateEnum.Success
    finally:
        try:
            if not published:
                _delete_published_outputs(step)
        finally:
            if ecc is not None:
                ecc.close()
