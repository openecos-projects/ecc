"""Handlers for the `ecc pdk` command group (PDK path configuration)."""

import os

from chipcompiler.cli.core.records import error_record
from chipcompiler.cli.core.types import CommandContext, CommandResult
from chipcompiler.cli.project.toml_edit import set_pdk_root
from chipcompiler.utility.file import write_text_atomic


def _write_pdk_root(config_path: str, value: str) -> None:
    """Set `root = "<value>"` under the existing [pdk] table, preserving layout.

    Raises OSError when the config cannot be read or replaced; handlers map
    that to a structured config_error at the command boundary.
    """
    with open(config_path) as f:
        original = f.read()

    write_text_atomic(config_path, set_pdk_root(original, value))


def _write_root_or_error(config_path: str, value: str, project: str | None) -> CommandResult | None:
    """Persist the PDK root; maps I/O failures to a structured config_error."""
    from chipcompiler.cli.core.output import disclosure_cmd

    try:
        _write_pdk_root(config_path, value)
    except OSError as exc:
        return CommandResult.err(
            [
                error_record(
                    "config_error",
                    path=config_path,
                    reason=str(exc),
                    inspect=disclosure_cmd("ecc check", project),
                )
            ]
        )
    return None


def _resolve_root_source(cfg, project_dir: str) -> tuple[str, str]:
    """Return (resolved_root, source) where source names the winning resolver."""
    if cfg is not None and cfg.pdk_root:
        from chipcompiler.cli.project.config import _resolve_path

        return _resolve_path(cfg.project_dir or project_dir, cfg.pdk_root), "ecc.toml"
    for var in ("CHIPCOMPILER_ICS55_PDK_ROOT", "ICS55_PDK_ROOT"):
        value = os.environ.get(var, "").strip()
        if value and os.path.isdir(os.path.abspath(value)):
            return os.path.abspath(value), var
    repo_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )
    return os.path.join(os.path.dirname(repo_root), "pdk", "icsprout55-pdk"), "repo-default"


def set_root(command_input, ctx: CommandContext) -> CommandResult:
    from chipcompiler.cli.project.config import find_config_path

    raw = command_input.path.strip()
    if not raw:
        return CommandResult.err(
            [error_record("invalid_pdk_path", path=raw, reason="path is empty")]
        )
    path = os.path.abspath(os.path.expanduser(raw))
    if not os.path.isdir(path):
        return CommandResult.err(
            [
                error_record(
                    "invalid_pdk_path",
                    path=path,
                    reason=(
                        "not a directory (clone icsprout55-pdk first, "
                        "then run make unzip inside it)"
                    ),
                )
            ]
        )

    config_path = find_config_path(ctx.project_dir)
    if config_path is None:
        return CommandResult.err(
            [
                error_record(
                    "missing_config",
                    path=os.path.join(ctx.project_dir, "ecc.toml"),
                )
            ]
        )
    error = _write_root_or_error(config_path, path, ctx.project)
    if error is not None:
        return error

    records = [
        {
            "pdk": "set-root",
            "status": "set",
            "path": path,
            "config": os.path.relpath(config_path, os.path.dirname(config_path) or "."),
            "check": "ecc check",
        }
    ]
    # Content problems are advisory here: a freshly cloned PDK without
    # `make unzip` still passes set-root, with a pointer to the fix.
    from chipcompiler.cli.project.config import load_project_config

    cfg = load_project_config(config_path)
    if cfg is not None:
        from chipcompiler.cli.project.config import _validate_pdk_contents, resolve_pdk_overrides

        problem = _validate_pdk_contents(cfg.pdk_name, path, resolve_pdk_overrides(cfg))
        if problem:
            records.append(
                {
                    "pdk": "contents",
                    "status": "incomplete",
                    "reason": problem.replace("\n", " "),
                    "hint": (
                        "run `make unzip` inside the PDK checkout, then verify with `ecc doctor`"
                    ),
                }
            )
    return CommandResult.ok(records)


def show(command_input, ctx: CommandContext) -> CommandResult:
    from chipcompiler.cli.project.config import load_run_config

    if ctx.config_error:
        from chipcompiler.cli.core.output import disclosure_cmd

        return CommandResult.err(
            [
                error_record(
                    "config_error",
                    reason=ctx.config_error,
                    inspect=disclosure_cmd("ecc check", ctx.project),
                )
            ]
        )
    cfg = ctx.config if ctx.config is not None else load_run_config(ctx.project_dir)
    root, source = _resolve_root_source(cfg, ctx.project_dir)

    pdk_name = cfg.pdk_name if cfg is not None and cfg.pdk_name else "ics55"
    records = [
        {
            "pdk": "show",
            "name": pdk_name,
            "root": root,
            "source": source,
            "doctor": "ecc doctor",
            "set_root": "ecc pdk set-root <path>",
        }
    ]
    if os.path.isdir(root):
        from chipcompiler.cli.project.config import _validate_pdk_contents, resolve_pdk_overrides

        problem = _validate_pdk_contents(
            pdk_name, root, resolve_pdk_overrides(cfg) if cfg else None
        )
        records.append(
            {
                "pdk": "contents",
                "status": "pass" if problem is None else "incomplete",
                "reason": problem.replace("\n", " ") if problem else None,
            }
        )
    else:
        records.append(
            {
                "pdk": "contents",
                "status": "missing",
                "reason": f"{root} does not exist",
                "set_root": "ecc pdk set-root <path>",
            }
        )
    return CommandResult.ok(records)


def unset(command_input, ctx: CommandContext) -> CommandResult:
    from chipcompiler.cli.project.config import find_config_path

    config_path = find_config_path(ctx.project_dir)
    if config_path is None:
        return CommandResult.err([error_record("missing_config")])
    error = _write_root_or_error(config_path, "", ctx.project)
    if error is not None:
        return error
    return CommandResult.ok(
        [
            {
                "pdk": "unset",
                "status": "unset",
                "source": "env CHIPCOMPILER_ICS55_PDK_ROOT / ICS55_PDK_ROOT / repo default",
            }
        ]
    )
