"""Handlers for the `ecc pdk` command group (PDK path configuration)."""

import os
import re

from chipcompiler.cli.core.records import error_record
from chipcompiler.cli.core.types import CommandContext, CommandResult

_TABLE_HEADER_RE = re.compile(r"^[ \t]*\[([^\]]+)\][ \t]*(?:#.*)?$", re.MULTILINE)


def _find_table_span(text: str, table_name: str) -> tuple[int, int] | None:
    """Return (body_start, body_end) for a TOML table, or None."""
    for match in _TABLE_HEADER_RE.finditer(text):
        if match.group(1).strip() != table_name:
            continue
        header_end = match.end()
        newline = text.find("\n", header_end)
        body_start = len(text) if newline == -1 else newline + 1
        next_header = _TABLE_HEADER_RE.search(text, body_start)
        body_end = next_header.start() if next_header else len(text)
        return body_start, body_end
    return None


def _write_pdk_root(config_path: str, value: str) -> None:
    """Set `root = "<value>"` under the existing [pdk] table, preserving layout."""
    with open(config_path) as f:
        original = f.read()

    span = _find_table_span(original, "pdk")
    if span is None:
        new_text = original.rstrip("\n") + f'\n\n[pdk]\nroot = "{value}"\n'
    else:
        body_start, body_end = span
        section = original[body_start:body_end]
        key_pattern = re.compile(r"^(\s*)root\s*=[^\n]*$", re.MULTILINE)
        key_match = key_pattern.search(section)
        if key_match:
            new_section = (
                section[: key_match.start()]
                + f'{key_match.group(1)}root = "{value}"'
                + section[key_match.end() :]
            )
        else:
            new_section = f'root = "{value}"\n' + section
        new_text = original[:body_start] + new_section + original[body_end:]

    with open(config_path, "w") as f:
        f.write(new_text)


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
    _write_pdk_root(config_path, path)

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
    _write_pdk_root(config_path, "")
    return CommandResult.ok(
        [
            {
                "pdk": "unset",
                "status": "unset",
                "source": "env CHIPCOMPILER_ICS55_PDK_ROOT / ICS55_PDK_ROOT / repo default",
            }
        ]
    )


PDK_URL = "https://github.com/openecos-projects/icsprout55-pdk.git"
DEFAULT_PDK_DIR = "~/.local/icsprout55-pdk"
_UNZIP_ATTEMPTS = 3


def setup(command_input, ctx: CommandContext) -> CommandResult:
    """Clone + `make unzip` a PDK checkout, then set it as the project root.

    Only the missing parts run: an existing complete checkout is only
    wired in via set-root. Downloads honor `GH_PROXY` the same way
    ecc-cli-setup.sh does (proxy-prefixed clone URL, USE_PROXY=true).
    """
    import shutil
    import subprocess

    from chipcompiler.cli.project.config import (
        _validate_pdk_contents,
        find_config_path,
        load_project_config,
    )

    config_path = find_config_path(ctx.project_dir)
    if config_path is None:
        return CommandResult.err(
            [error_record("missing_config", path=os.path.join(ctx.project_dir, "ecc.toml"))]
        )
    cfg = load_project_config(config_path)
    pdk_name = cfg.pdk_name if cfg is not None and cfg.pdk_name else "ics55"

    raw = (command_input.path or DEFAULT_PDK_DIR).strip()
    path = os.path.abspath(os.path.expanduser(raw))
    action_records: list[dict] = []
    actions: list[str] = []

    def contents_problem() -> str | None:
        return _validate_pdk_contents(pdk_name, path, None)

    if not os.path.isdir(path):
        missing_tools = [tool for tool in ("git", "make") if shutil.which(tool) is None]
        if missing_tools:
            return CommandResult.err(
                [
                    error_record(
                        "missing_tool",
                        reason=f"required for setup: {', '.join(missing_tools)}",
                    )
                ]
            )
        clone_url = PDK_URL
        gh_proxy = os.environ.get("GH_PROXY", "").strip()
        if gh_proxy:
            clone_url = f"{gh_proxy}{PDK_URL}"
        result = subprocess.run(
            ["git", "clone", "--depth", "1", clone_url, path],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return CommandResult.err(
                [
                    error_record(
                        "clone_failed",
                        path=path,
                        reason=(result.stderr or result.stdout or "").strip()[-400:],
                    )
                ]
            )
        actions.append("clone")
        action_records.append({"pdk": "clone", "status": "cloned", "path": path})

    problem = contents_problem()
    if problem is not None:
        if shutil.which("make") is None:
            return CommandResult.err(
                [error_record("missing_tool", reason="required for setup: make")]
            )
        make_cmd = ["make", "unzip"]
        gh_proxy = os.environ.get("GH_PROXY", "").strip()
        if gh_proxy:
            make_cmd += ["USE_PROXY=true", f"GH_PROXY={gh_proxy}"]
        extracted = False
        for attempt in range(1, _UNZIP_ATTEMPTS + 1):
            result = subprocess.run(make_cmd, cwd=path, capture_output=True, text=True)
            if result.returncode == 0:
                extracted = True
                break
            action_records.append(
                {
                    "pdk": "unzip",
                    "status": "failed",
                    "attempt": attempt,
                    "reason": (result.stderr or result.stdout or "").strip()[-200:],
                }
            )
        if not extracted:
            return CommandResult.err([error_record("unzip_failed", path=path)] + action_records)
        still_incomplete = contents_problem()
        if still_incomplete is not None:
            return CommandResult.err(
                [error_record("unzip_failed", path=path, reason=still_incomplete)]
            )
        actions.append("unzip")
        action_records.append({"pdk": "unzip", "status": "extracted", "path": path})

    _write_pdk_root(config_path, path)
    summary = {
        "pdk": "setup",
        "status": "ready",
        "path": path,
        "actions": actions,
        "config": "ecc.toml",
        "check": "ecc check",
    }
    return CommandResult.ok([summary] + action_records)
