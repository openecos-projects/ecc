"""Publication policy for RCX extraction artifacts.

iRCX writes extraction results to ``<data_dir>/spef_writer``. This module
resolves the RCX step directories, clears stale extraction artifacts before a
run, and publishes the fresh SPEF set to the step output directory
all-or-nothing: a failed pass restores the previously published SPEFs instead
of destroying them, and a successful pass leaves no backups behind.
"""

import os
import shutil
from pathlib import Path

from chipcompiler.data import EccStep, Workspace


def _workspace_rcx_dir(path_text: str, workspace_dir: Path) -> Path:
    if path_text.startswith("/"):
        relative_path = path_text[1:]
        if relative_path.split("/", 1)[0] in ("RCX_ecc", "rcx_ecc"):
            return workspace_dir / relative_path
    return Path(path_text)


def resolve_rcx_dirs(workspace: Workspace, step: EccStep) -> tuple[Path | None, Path | None]:
    """Resolve the RCX extraction data and output directories for a step."""
    workspace_dir = workspace.directory
    if workspace_dir is None:
        return None, None

    data_dir_text = os.fspath(step.data.dir or "")
    output_dir_text = os.fspath(step.output.dir or "")
    if not data_dir_text or not output_dir_text:
        return None, None

    return (
        _workspace_rcx_dir(data_dir_text, workspace_dir),
        _workspace_rcx_dir(output_dir_text, workspace_dir),
    )


def wipe_stale_spef_artifacts(data_dir: Path) -> None:
    for stale_path in (data_dir / "spef_writer").glob("*.spef"):
        stale_path.unlink(missing_ok=True)


def copy_rcx_spef_outputs(workspace: Workspace, step: EccStep) -> bool:
    data_dir, output_dir = resolve_rcx_dirs(workspace, step)
    if data_dir is None or output_dir is None:
        workspace.logger.error("RCX data or output directory is not configured")
        return False

    spef_writer_dir = data_dir / "spef_writer"
    if not spef_writer_dir.is_dir():
        workspace.logger.error("RCX extraction artifacts are missing: %s", spef_writer_dir)
        return False

    declared_paths = [spef_path for spef_path in step.output.spef if spef_path]
    output_paths = [
        output_dir / spef_path.name
        for spef_path in (declared_paths or sorted(spef_writer_dir.glob("*.spef")))
    ]

    if not output_paths:
        workspace.logger.error("RCX extraction produced no SPEF artifacts to publish")
        return False

    # Validate the whole source set before touching any destination, so a
    # partially copied set or a stale destination left by an earlier run can
    # never pass for fresh extraction output.
    for output_path in output_paths:
        source_path = spef_writer_dir / output_path.name
        if not (source_path.is_file() and os.path.getsize(source_path) > 0):
            workspace.logger.error("RCX extraction artifact is missing or empty: %s", source_path)
            return False

    processed: list[tuple[Path, Path | None]] = []
    temp_paths: list[Path] = []
    try:
        for output_path in output_paths:
            source_path = spef_writer_dir / output_path.name
            output_path.parent.mkdir(parents=True, exist_ok=True)
            backup_path = (
                output_path.with_name(f".{output_path.name}.prev") if output_path.exists() else None
            )
            if backup_path is not None:
                # Preserve the previously published SPEF so a failure later
                # in this pass can restore the last known-good artifact.
                output_path.replace(backup_path)
            temp_path = output_path.with_name(f".{output_path.name}.tmp")
            processed.append((output_path, backup_path))
            temp_paths.append(temp_path)
            shutil.copy2(source_path, temp_path)
            temp_path.replace(output_path)
            workspace.logger.info("Copied RCX SPEF %s to %s", source_path, output_path)

        for output_path in output_paths:
            if not (os.path.isfile(output_path) and os.path.getsize(output_path) > 0):
                raise OSError(f"Published RCX SPEF is missing or empty: {output_path}")
    except Exception as exc:
        # Publication is all-or-nothing: a failed pass restores the SPEFs it
        # replaced, removes the destinations it created, and drops partial
        # temporary copies, leaving the step outputs exactly as before.
        for output_path, backup_path in processed:
            if backup_path is not None:
                backup_path.replace(output_path)
            else:
                output_path.unlink(missing_ok=True)
        for temp_path in temp_paths:
            temp_path.unlink(missing_ok=True)
        workspace.logger.error("Failed to publish RCX SPEF artifacts: %s", exc)
        return False

    # The pass is committed: drop the preserved copies so a successful rerun
    # does not accumulate a second SPEF set on disk. A removal failure must
    # not fail the already-published step, so it is only reported.
    for _output_path, backup_path in processed:
        if backup_path is not None:
            try:
                backup_path.unlink(missing_ok=True)
            except OSError as exc:
                workspace.logger.warning("Failed to remove RCX SPEF backup: %s", exc)

    if isinstance(step.output.spef, list):
        step.output.spef[:] = output_paths
    return True
