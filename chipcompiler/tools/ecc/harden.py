"""Physical abstracts and timing models for every selected signoff scenario."""

import shutil
from pathlib import Path

from chipcompiler.data import EccStep, StepEnum, Workspace
from chipcompiler.tools.ecc.module import ECCToolsModule
from chipcompiler.tools.ecc.sta_qor import sta_artifact_directory
from chipcompiler.tools.ecc.timing_constraints import step_tcl_path
from chipcompiler.utility import json_write


def export_harden_views(
    workspace: Workspace,
    step: EccStep,
    ecc_module: ECCToolsModule,
    items: list[dict],
    sta_config: str,
) -> None:
    if step.output.lib is None:
        raise ValueError("Harden Liberty output is not configured")
    if not workspace.pdk.mapping_file:
        raise ValueError("Cannot harden without a PDK GDS layer map")

    default_lib = Path(step.output.lib)
    model_root = default_lib.parent / "timing_models"
    # These are this step's generated models, never input macro libraries.
    # A failed or narrowed rerun must not leave a stale delivery catalog.
    default_lib.unlink(missing_ok=True)
    if model_root.exists():
        shutil.rmtree(model_root)
    model_root.mkdir(parents=True)
    models = []
    typical_model = None
    for item in items:
        corner, temperature, rc = item["corner"], item["temperature"], item["rcx_corner"]
        model_dir = sta_artifact_directory(model_root, corner, temperature, rc)
        work_dir = sta_artifact_directory(
            step.data.steps[StepEnum.STA.value], corner, temperature, rc
        )
        assert model_dir is not None and work_dir is not None
        if work_dir.exists():
            shutil.rmtree(work_dir)
        model_path = model_dir / f"{workspace.design.top_module or workspace.design.name}.lib"
        min_model_path = model_path.with_name(f"{model_path.stem}_min.lib")
        sdc = step_tcl_path(workspace, step, corner=corner, rc=rc)
        assert sdc is not None
        ecc_module.write_timing_model(
            output_lib_path=model_path,
            output_min_lib_path=min_model_path,
            config=sta_config,
            output_dir=work_dir,
            lib_paths=item["liberty_files"],
            min_lib_paths=item.get("min_liberty_files", []),
            sdc_path=sdc,
            spef_path=item["spef_file"],
            design_name=workspace.design.top_module or workspace.design.name,
        )
        for path in (model_path, min_model_path):
            if not path.is_file() or path.stat().st_size == 0:
                raise RuntimeError(f"Harden did not produce a timing model: {path}")
        models.append(
            {
                "corner": corner,
                "temperature": temperature,
                "rc_corner": rc,
                "analysis_mode": "max",
                "path": str(model_path.relative_to(model_root)),
                "min_path": str(min_model_path.relative_to(model_root)),
                "source_libraries": item["liberty_files"],
                "source_min_libraries": item.get("min_liberty_files", []),
                "sdc": str(sdc),
                "spef": item["spef_file"],
            }
        )
        if corner == "TYP" and rc == "TYPICAL":
            typical_model = model_path

    ecc_module.write_abstract_lef(output_lef_path=step.output.lef or "")
    ecc_module.gds_save(
        output_path=step.output.gds or "", layer_map_path=workspace.pdk.mapping_file
    )
    assert typical_model is not None
    shutil.copyfile(typical_model, default_lib)
    if not json_write(model_root / "manifest.json", {"schema_version": 2, "models": models}):
        raise RuntimeError("Failed to publish Harden timing-model manifest")
