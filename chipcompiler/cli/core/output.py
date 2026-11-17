import shlex
from typing import Final

from chipcompiler.data.types import SkippableStepEnum, StepEnum


def disclosure_cmd(command: str, project: str | None = None, workspace: str | None = None) -> str:
    parts = [command]
    if project:
        parts.append(f"--project {shlex.quote(project)}")
    if workspace is not None:
        parts.append(f"--workspace {shlex.quote(workspace)}")
    return " ".join(parts)


# CLI step tokens that differ from the lowercased flow step name.
_STEP_TOKEN_OVERRIDES: Final[dict[str, str]] = {
    StepEnum.PRE_FLOORPLAN.value: "pre_floorplan",
    StepEnum.MACRO_PLACEMENT.value: "macro_placement",
    StepEnum.POST_FLOORPLAN.value: "post_floorplan",
    StepEnum.PLACEMENT.value: "placement",
    SkippableStepEnum.TIMING_OPT.value: "timing_optimization",
    # The lowercase spelling users type on the command line (`ecc config`).
    SkippableStepEnum.TIMING_OPT.value.lower(): "timing_optimization",
    StepEnum.ROUTING.value: "routing",
}


def flow_step_token(step_name: str) -> str:
    """The CLI token of a flow step name, e.g. ``place`` -> ``placement``."""
    return _STEP_TOKEN_OVERRIDES.get(step_name, step_name.lower())


def flow_step_status(state: str) -> str:
    """The CLI status of a flow step run state, e.g. ``Success`` -> ``success``."""
    return state.lower()
