"""Verify a candidate rerun's executed DreamPlace steps resolved the candidate values.

Shared by candidate rerun (``workspace_api``) and resume (``candidate_resume``):
after the steps run, each executed DreamPlace step's own config must hold the
candidate seed and the step-scoped knob values the candidate materialized.
"""

from .data.candidate_materialization import candidate_written_patch
from .data.candidate_step_values import (
    expected_step_config_values,
    verify_executed_step_configs,
)
from .runtime_support import AgentApplicationError


def verify_candidate_step_configs(
    workspace, request, *, executed_steps: list, seed_step_names: list[str]
) -> None:
    """Check each executed DreamPlace step resolved the candidate seed and knob values."""
    try:
        written = (
            candidate_written_patch(workspace, request.target_step, request.patch)
            if request.patch
            else []
        )
        verify_executed_step_configs(
            executed_steps,
            expected_step_config_values(written, seed_step_names, request.seed),
        )
    except ValueError as exc:
        raise AgentApplicationError("command_failed", str(exc)) from exc
