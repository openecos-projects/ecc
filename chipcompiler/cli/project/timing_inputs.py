"""Resolve external timing inputs before building the effective flow parameters."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import ProjectConfig


def resolve_timing_input_metadata(cfg: "ProjectConfig") -> None:
    from chipcompiler.data.workspace.sdc_inputs import SdcInputs

    from .config import _resolve_path

    cfg._timing_input_error = None
    if not cfg.design_sdc:
        return
    try:
        inputs = SdcInputs.from_file(_resolve_path(cfg.project_dir, cfg.design_sdc))
    except (OSError, ValueError) as exc:
        cfg._timing_input_error = str(exc)
        return
    clock = inputs.primary_clock()
    cfg.design_clock_port = clock.target
    cfg.design_frequency_mhz = clock.frequency_mhz
    # The valid external primary clock supersedes the raw [design] material.
    cfg._clock_material = clock.target
