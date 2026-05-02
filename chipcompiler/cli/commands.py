from chipcompiler.cli.config import resolve_project_dir
from chipcompiler.cli.inspect import resolve_run_dir
from chipcompiler.cli.types import CommandContext, CommandResult, OutputMode


def build_context(args) -> CommandContext:
    project = getattr(args, "project", None)
    project_dir = resolve_project_dir(project)

    run_id = getattr(args, "run_id", None)
    run_dir, run_id = resolve_run_dir(project_dir, run_id)

    if getattr(args, "jsonl", False):
        mode = OutputMode.JSONL
    elif getattr(args, "json", False):
        mode = OutputMode.JSON
    else:
        mode = OutputMode.TEXT

    return CommandContext(
        project_dir=project_dir,
        project=project,
        run_dir=run_dir,
        run_id=run_id,
        output_mode=mode,
    )


def dispatch(args, ctx: CommandContext) -> CommandResult:
    from chipcompiler.cli import handlers
    handler = getattr(handlers, args.command, None)
    if handler is None:
        return CommandResult.err([], exit_code=1)
    return handler(args, ctx)
