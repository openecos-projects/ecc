"""Launch the native Chip Viewer for a saved workspace geometry snapshot."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from chipcompiler.cli.core.output import normalize_step_name
from chipcompiler.cli.core.records import error_record
from chipcompiler.cli.core.types import CommandContext, CommandResult
from chipcompiler.cli.inspection.discovery import resolve_workspace_path
from chipcompiler.data.step import step_directory_for_tool

_GEOMETRY_SCHEMA_VERSION = 1
_REQUIRED_FILES = (
    "meta",
    "shapes",
    "owners",
    "payload",
    "names",
    "name_index",
    "sidmap",
    "view",
)
_OPTIONAL_FILES = (
    "delta",
    "layers",
    "sites",
    "masters",
    "vias",
    "grids",
    "connectivity",
    "nets",
    "buses",
    "groups",
    "drc",
)
_REQUIRED_NUMBERS = ("shape_count", "owner_count", "payload_size")
_OPTIONAL_NUMBERS = (
    "dirty_lod_tile_count",
    "dirty_lod_rebuild_candidate_count",
    "written_side_file_count",
    "reused_side_file_count",
)
_STARTUP_CHECK_SECONDS = 0.8


def _read_flow_steps(workspace_dir: Path) -> tuple[list[dict] | None, str | None]:
    flow_path = workspace_dir / "home" / "flow.json"
    if not flow_path.is_file():
        return None, f"flow ledger is missing: {flow_path}"
    try:
        payload = json.loads(flow_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"flow ledger cannot be read: {exc}"
    steps = payload.get("steps") if isinstance(payload, dict) else None
    if not isinstance(steps, list):
        return None, f"flow ledger has no steps list: {flow_path}"
    return [step for step in steps if isinstance(step, dict)], None


def _step_matches(requested: str, name: str, tool: str, directory: str) -> bool:
    requested_lower = requested.strip().lower()
    if not requested_lower:
        return False
    normalized = normalize_step_name(name)
    candidates = {
        name.lower(),
        normalized.lower(),
        directory.lower(),
        f"{name}_{tool}".lower(),
        f"{normalized}_{tool}".lower(),
    }
    return requested_lower in candidates


def _resolve_step_geometry(workspace_dir: Path, requested: str):
    steps, error = _read_flow_steps(workspace_dir)
    if error:
        return None, error_record("chipview_flow_unavailable", reason=error)

    for flow_step in steps or []:
        name = str(flow_step.get("name", "")).strip()
        tool = str(flow_step.get("tool", "")).strip()
        if not name or not tool:
            continue
        directory = step_directory_for_tool(name, tool)
        if not _step_matches(requested, name, tool, directory):
            continue
        step_dir = workspace_dir / directory
        output_dir = step_dir / "output"
        return {
            "name": name,
            "tool": tool,
            "directory": step_dir,
            "output": output_dir,
            "manifest": output_dir / "geometry" / "geometry.manifest",
            "drc_statis": step_dir / "analysis" / "drc_statis.csv",
            "map_root": step_dir / "feature",
        }, None

    available = [
        f"{step.get('name')} ({step.get('tool')})" for step in steps or [] if step.get("name")
    ]
    return None, error_record(
        "chipview_step_not_found",
        step=requested,
        available=", ".join(available) or "(none)",
        reason="the requested step is not present in the workspace flow ledger",
    )


def _parse_manifest(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip():
            values[key.strip()] = value.strip()
    return values


def _manifest_failure(manifest: Path, reason: str) -> CommandResult:
    return CommandResult.err(
        [
            error_record(
                "chipview_geometry_invalid",
                manifest=str(manifest),
                reason=reason,
                remediation="rerun the selected flow step to regenerate its geometry snapshot",
            )
        ]
    )


def _validate_manifest(manifest: Path, *, require_drc: bool = False) -> CommandResult | None:
    if not manifest.is_file():
        return _manifest_failure(manifest, "geometry manifest is missing")
    try:
        values = _parse_manifest(manifest)
    except (OSError, UnicodeDecodeError) as exc:
        return _manifest_failure(manifest, f"manifest cannot be read: {exc}")
    if not values:
        return _manifest_failure(manifest, "manifest has no key/value entries")
    schema = values.get("schema_version")
    if schema != str(_GEOMETRY_SCHEMA_VERSION):
        return _manifest_failure(
            manifest,
            f"unsupported schema_version {schema!r}; expected {_GEOMETRY_SCHEMA_VERSION}",
        )
    if require_drc and not values.get("drc"):
        return _manifest_failure(manifest, "manifest is missing drc")
    for key in (*_REQUIRED_NUMBERS, *_OPTIONAL_NUMBERS):
        value = values.get(key)
        if value is None and key in _REQUIRED_NUMBERS:
            return _manifest_failure(manifest, f"manifest is missing {key}")
        if value is not None and (not value.isdigit()):
            return _manifest_failure(manifest, f"manifest {key} is not a non-negative integer")

    geometry_dir = manifest.parent.resolve()
    for key in (*_REQUIRED_FILES, *_OPTIONAL_FILES):
        value = values.get(key)
        if not value:
            if key in _REQUIRED_FILES:
                return _manifest_failure(manifest, f"manifest is missing {key}")
            continue
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = manifest.parent / candidate
        candidate = candidate.resolve()
        try:
            candidate.relative_to(geometry_dir)
        except ValueError:
            return _manifest_failure(manifest, f"manifest {key} points outside geometry directory")
        if not candidate.is_file():
            return _manifest_failure(manifest, f"manifest {key} file does not exist: {candidate}")
    return None


def _viewer_candidates(env: dict[str, str]) -> list[tuple[Path, str]]:
    candidates: list[tuple[Path, str]] = []
    explicit = env.get("ECOS_CHIP_VIEWER_BIN", "").strip()
    if explicit:
        candidates.append((Path(explicit).expanduser(), "ECOS_CHIP_VIEWER_BIN"))

    resources = env.get("ECOS_ELECTRON_RESOURCES_PATH", "").strip()
    if resources:
        candidates.append((Path(resources) / "binaries" / "chip-viewer-native", "AppImage"))

    path_viewer = shutil.which("chip-viewer-native", path=env.get("PATH"))
    if path_viewer:
        candidates.append((Path(path_viewer), "PATH"))
    return candidates


def _resolve_viewer(env: dict[str, str]):
    candidates = _viewer_candidates(env)
    for path, source in candidates:
        if path.is_file() and os.access(path, os.X_OK):
            return path, source
    expected = (
        str(candidates[0][0]) if candidates else "<AppImage resources>/binaries/chip-viewer-native"
    )
    appimage = env.get("APPIMAGE", "").strip()
    appimage_detail = f" detected AppImage: {appimage}" if appimage else ""
    return None, (
        "chip-viewer-native was not found or is not executable."
        f"{appimage_detail} Expected: {expected}."
        " Run this command from ECOS Studio's built-in terminal,"
        " or set ECOS_CHIP_VIEWER_BIN to an executable chip-viewer-native path."
    )


def _display_failure() -> CommandResult | None:
    if sys.platform != "linux" or any(
        os.environ.get(key) for key in ("DISPLAY", "WAYLAND_DISPLAY", "WAYLAND_SOCKET")
    ):
        return None
    return CommandResult.err(
        [
            error_record(
                "chipview_display_unavailable",
                reason="no Linux display environment was detected",
                remediation=(
                    "run ECOS Studio in a desktop session with DISPLAY or WAYLAND_DISPLAY set"
                ),
            )
        ]
    )


def _tail(path: Path, limit: int = 4000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-limit:]
    except OSError:
        return ""


def _launch_viewer(viewer: Path, args: list[str], workspace_dir: Path):
    log_dir = workspace_dir / ".chip-viewer" / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = log_dir / f"chipview-{os.getpid()}-{int(time.time())}.stdout.log"
        stderr_path = log_dir / f"chipview-{os.getpid()}-{int(time.time())}.stderr.log"
        stdout = stdout_path.open("ab")
        stderr = stderr_path.open("ab")
    except OSError as exc:
        return None, error_record("chipview_log_unavailable", reason=str(exc))

    viewer_env = dict(os.environ)
    for key in ("ELECTRON_NO_ATTACH_CONSOLE", "ELECTRON_RUN_AS_NODE", "NODE_OPTIONS"):
        viewer_env.pop(key, None)
    try:
        process = subprocess.Popen(
            [str(viewer), *args],
            cwd=str(workspace_dir),
            env=viewer_env,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
        )
    except OSError as exc:
        stdout.close()
        stderr.close()
        return None, error_record(
            "chipview_launch_failed",
            reason=str(exc),
            viewer=str(viewer),
            stderr_log=str(stderr_path),
        )
    finally:
        stdout.close()
        stderr.close()

    deadline = time.monotonic() + _STARTUP_CHECK_SECONDS
    while time.monotonic() < deadline:
        code = process.poll()
        if code is not None:
            detail = _tail(stderr_path)
            return None, error_record(
                "chipview_launch_failed",
                reason=f"Viewer exited during startup with code {code}",
                viewer=str(viewer),
                stderr_log=str(stderr_path),
                stderr_tail=detail,
            )
        time.sleep(0.05)
    return {
        "pid": process.pid,
        "stdout_log": str(stdout_path),
        "stderr_log": str(stderr_path),
    }, None


def chipview(command_input, ctx: CommandContext) -> CommandResult:
    if sys.platform != "linux":
        return CommandResult.err(
            [
                error_record(
                    "chipview_platform_unsupported",
                    reason="Chip Viewer launching through ecc chipview currently requires Linux",
                )
            ]
        )
    if ctx.manifest_error:
        from chipcompiler.cli.core.records import manifest_error_record

        return CommandResult.err([manifest_error_record(ctx.manifest_error)])
    workspace_dir, error = resolve_workspace_path(
        command_input.workspace, ctx.project, ctx.run_id, ctx.run_dir
    )
    if error is not None:
        return CommandResult.err([error])

    workspace = Path(workspace_dir)
    resolved, step_error = _resolve_step_geometry(workspace, command_input.step)
    if step_error is not None:
        return CommandResult.err([step_error])
    manifest = resolved["manifest"]
    manifest_failure = _validate_manifest(
        manifest,
        require_drc=resolved["name"].lower().startswith("drc"),
    )
    if manifest_failure is not None:
        return manifest_failure

    env = dict(os.environ)
    viewer, viewer_source = _resolve_viewer(env)
    if viewer is None:
        return CommandResult.err(
            [
                error_record(
                    "chipview_viewer_unavailable",
                    reason=viewer_source,
                    remediation=(
                        "open the AppImage first and use its built-in terminal, or set "
                        "ECOS_CHIP_VIEWER_BIN"
                    ),
                )
            ]
        )

    display_failure = _display_failure()
    if display_failure is not None:
        return display_failure

    args = ["--manifest", str(manifest), "--mode", "view"]
    if resolved["drc_statis"].is_file() and resolved["name"].lower().startswith("drc"):
        args.extend(["--drc-statis", str(resolved["drc_statis"])])
    if resolved["map_root"].is_dir():
        args.extend(["--map-root", str(resolved["map_root"])])

    launch, launch_error = _launch_viewer(viewer, args, workspace)
    if launch_error is not None:
        return CommandResult.err([launch_error])
    return CommandResult.ok(
        [
            {
                "chipview": "started",
                "status": "started",
                "workspace": str(workspace),
                "step": resolved["name"],
                "manifest": str(manifest),
                "viewer": str(viewer),
                "viewer_source": viewer_source,
                **launch,
            }
        ]
    )
