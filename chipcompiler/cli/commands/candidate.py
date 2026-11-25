"""Expose the ECC candidate library as bounded, one-shot CLI commands."""

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

import typer

from chipcompiler.cli.core.apps import create_app
from chipcompiler.cli.core.options import ProjectOption

candidate_app = create_app(help="Inspect and execute isolated optimization candidates")
WorkspaceArgument = Annotated[str, typer.Argument(help="Managed source Workspace ID")]


def _resolve_project(project: str | None, workspace: str) -> Path:
    from chipcompiler.cli.project.current_location import resolve_current_location

    location = resolve_current_location(project, workspace, workspace_supported=True)
    return Path(location.project or ".").resolve()


def _read_stdin_request() -> dict[str, Any]:
    raw = sys.stdin.buffer.read(64 * 1024 + 1)
    if len(raw) > 64 * 1024:
        raise ValueError("Candidate request exceeds 64 KiB")
    data = json.loads(raw)
    if not isinstance(data, dict) or "workspace_id" in data:
        raise ValueError("Invalid candidate request")
    return data


def _run_checked(action: Callable[[], None]) -> None:
    try:
        action()
    except (OSError, ValueError, RuntimeError) as exc:
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
    from agent.cli import run_capabilities

    _run_checked(lambda: run_capabilities(_resolve_project(project, workspace), workspace))


@candidate_app.command("status")
def status(
    workspace: WorkspaceArgument,
    candidate: Annotated[str, typer.Option("--candidate")],
    project: ProjectOption = None,
) -> None:
    """Read the durable operation ledger of an isolated candidate."""
    from agent.cli import run_status

    _run_checked(lambda: run_status(_resolve_project(project, workspace), workspace, candidate))


@candidate_app.command("cleanup")
def cleanup(
    workspace: WorkspaceArgument,
    prefix: Annotated[str, typer.Option("--prefix", help="Candidate group ID prefix")],
    project: ProjectOption = None,
) -> None:
    """Remove candidate directories in a group and keep their operation ledgers."""
    from agent.cli import run_cleanup

    _run_checked(lambda: run_cleanup(_resolve_project(project, workspace), workspace, prefix))


@candidate_app.command("retain")
def retain(
    workspace: WorkspaceArgument,
    candidate: Annotated[str, typer.Option("--candidate")],
    manifest_sha256: Annotated[str, typer.Option("--manifest-sha256")],
    target: Annotated[str, typer.Option("--target")],
    project: ProjectOption = None,
) -> None:
    """Keep a verified completed candidate as a new managed Workspace."""
    from agent.cli import run_retain

    _run_checked(
        lambda: run_retain(
            _resolve_project(project, workspace),
            workspace,
            candidate_id=candidate,
            digest=manifest_sha256,
            target_id=target,
        )
    )


@candidate_app.command("operation")
def operation(
    workspace: WorkspaceArgument,
    operation_id: Annotated[str, typer.Option("--id")],
    *,
    cancel: Annotated[bool, typer.Option("--cancel")] = False,
    project: ProjectOption = None,
) -> None:
    """Find or cancel a candidate operation in this source Workspace."""
    from agent.cli import run_operation

    _run_checked(
        lambda: run_operation(
            _resolve_project(project, workspace), workspace, operation_id, cancel=cancel
        )
    )


@candidate_app.command("rerun")
def rerun(workspace: WorkspaceArgument, project: ProjectOption = None) -> None:
    """Run a JSON request from stdin and emit accepted and terminal records."""
    from agent.cli import run_rerun

    _run_checked(
        lambda: run_rerun(_resolve_project(project, workspace), workspace, _read_stdin_request())
    )


@candidate_app.command("resume")
def resume(workspace: WorkspaceArgument, project: ProjectOption = None) -> None:
    """Resume a JSON request from stdin and emit accepted and terminal records."""
    from agent.cli import run_resume

    _run_checked(
        lambda: run_resume(_resolve_project(project, workspace), workspace, _read_stdin_request())
    )
