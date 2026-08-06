"""Runtime checks shared by candidate config and checkpoint receipts."""

from __future__ import annotations

from typing import Any

from .candidate_input_binding import input_binding_candidate_id
from .candidate_materialization import validate_materialized_candidate_config
from .candidate_registry import candidate_target_backend


class CandidateStepContractError(ValueError):
    """Candidate receipts cannot safely be used together for one step."""


def validate_candidate_step_contract(workspace: Any, target_step: str) -> str | None:
    """Reject an unbound or mismatched config/checkpoint receipt pair."""
    try:
        config_candidate_id = validate_materialized_candidate_config(workspace, target_step)
    except ValueError as error:
        raise CandidateStepContractError(str(error)) from error
    input_candidate_id = input_binding_candidate_id(workspace, target_step)
    if config_candidate_id is not None and input_candidate_id is None:
        raise CandidateStepContractError(
            f"candidate config for {target_step} requires a bound upstream checkpoint"
        )
    if (
        config_candidate_id is not None
        and input_candidate_id is not None
        and config_candidate_id != input_candidate_id
    ):
        raise CandidateStepContractError(
            f"candidate receipt mismatch for {target_step}: "
            f"config={config_candidate_id}, input={input_candidate_id}"
        )
    if config_candidate_id is not None or input_candidate_id is not None:
        backend = candidate_target_backend(workspace, target_step)
        if backend["available"] is not True:
            reason = backend.get("reason", "backend is unavailable")
            raise CandidateStepContractError(
                f"candidate backend is unavailable for {target_step}: {reason}"
            )
    return config_candidate_id or input_candidate_id
