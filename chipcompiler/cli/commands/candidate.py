"""Expose the ECC candidate library as bounded, one-shot CLI commands."""

import json
import sys
from typing import Annotated

import typer

from chipcompiler.cli.core.apps import create_app
from chipcompiler.cli.core.options import ProjectOption

candidate_app = create_app(help="Inspect and execute isolated optimization candidates")
WorkspaceArgument = Annotated[str, typer.Argument(help="Managed source Workspace ID")]


def _invoke(action: str, workspace: str, project: str | None, **fields) -> None:
    from agent.cli import CandidateCommand, run_command

    try:
        data = fields
        if action in ("rerun", "resume"):
            raw = sys.stdin.buffer.read(64 * 1024 + 1)
            if len(raw) > 64 * 1024:
                raise ValueError("Candidate request exceeds 64 KiB")
            data = json.loads(raw)
            if not isinstance(data, dict) or "workspace_id" in data:
                raise ValueError("Invalid candidate request")
        run_command(CandidateCommand(action, project, workspace, data))
    except (OSError, ValueError, RuntimeError, TypeError) as exc:
        typer.echo(
            json.dumps(
                {
                    "record": "candidate_error",
                    "code": getattr(exc, "code", "candidate_error"),
                    "message": str(exc),
                }
            )
        )
        raise typer.Exit(1) from exc


@candidate_app.command("version")
def version() -> None:
    """Report the exact ECC revision used in candidate receipts."""
    from chipcompiler import __version__

    typer.echo(json.dumps({"eccVersion": __version__}))


@candidate_app.command("capabilities")
def capabilities(workspace: WorkspaceArgument, project: ProjectOption = None) -> None:
    """Report the knobs available in a managed Workspace as JSON."""
    _invoke("capabilities", workspace, project)


@candidate_app.command("status")
def status(
    workspace: WorkspaceArgument,
    candidate: Annotated[str, typer.Option("--candidate")],
    project: ProjectOption = None,
) -> None:
    """Read the durable operation ledger of an isolated candidate."""
    _invoke("status", workspace, project, candidate_id=candidate)


@candidate_app.command("cleanup")
def cleanup(
    workspace: WorkspaceArgument,
    prefix: Annotated[str, typer.Option("--prefix", help="Candidate group ID prefix")],
    project: ProjectOption = None,
) -> None:
    """Remove candidate directories in a group and keep their operation ledgers."""
    _invoke("cleanup", workspace, project, prefix=prefix)


@candidate_app.command("operation")
def operation(
    workspace: WorkspaceArgument,
    operation_id: Annotated[str, typer.Option("--id")],
    *,
    cancel: Annotated[bool, typer.Option("--cancel")] = False,
    project: ProjectOption = None,
) -> None:
    """Find or cancel a candidate operation in this source Workspace."""
    _invoke("operation", workspace, project, operation_id=operation_id, cancel=cancel)


@candidate_app.command("rerun")
def rerun(workspace: WorkspaceArgument, project: ProjectOption = None) -> None:
    """Run a JSON request from stdin and emit accepted and terminal records."""
    _invoke("rerun", workspace, project)


@candidate_app.command("resume")
def resume(workspace: WorkspaceArgument, project: ProjectOption = None) -> None:
    """Resume a JSON request from stdin and emit accepted and terminal records."""
    _invoke("resume", workspace, project)
