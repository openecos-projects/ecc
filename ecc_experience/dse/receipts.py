"""Recover completed commands without rerunning a potentially active EDA process."""

from pathlib import Path

from chipcompiler.project.runtime_processes import _boot_id, _host_id
from ecc_experience.command_receipts import load_request, read_receipt
from ecc_experience.models import ExperienceError


def recover_command(command: dict, expected: list[str], output: Path) -> None:
    requested = command.get("request")
    if not isinstance(requested, str) or Path(requested).parent != output:
        raise ExperienceError(
            "Interrupted command has no bound receipt", code="experience_workspace_busy"
        )
    request = load_request(Path(requested))
    if request.arguments != expected or str(request.receipt) != command.get("receipt"):
        raise ExperienceError("DSE command request changed", code="experience_source_changed")
    receipt = read_receipt(request, command.get("request_fingerprint", ""))
    if not receipt or receipt["status"] != "complete" or not receipt["process_tree_quiescent"]:
        raise ExperienceError(
            "DSE command or descendants have not completed", code="experience_workspace_busy"
        )
    worker = receipt.get("worker", {})
    if worker.get("host_id") != _host_id() or worker.get("boot_id") != _boot_id():
        raise ExperienceError(
            "DSE receipt belongs to a different host or boot", code="experience_workspace_busy"
        )
    command.update(status="complete", exit_code=receipt["exit_code"])
