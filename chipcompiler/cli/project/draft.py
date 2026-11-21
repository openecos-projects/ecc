"""Validate one Workspace creation draft and publish its Project changes."""

import json
import shutil
from contextlib import ExitStack, suppress
from dataclasses import dataclass, replace
from pathlib import Path

from chipcompiler.cli.core.records import error_record
from chipcompiler.cli.core.types import CommandResult
from chipcompiler.cli.project.config import parse_project_config, resolve_pdk_root
from chipcompiler.cli.project.flow_selection import (
    changed_insert_steps,
    effective_insert_steps,
    effective_skip_steps,
    toggled_skip_steps,
)
from chipcompiler.cli.project.project_application import (
    ProjectApplicationError,
    apply_settings_text,
)
from chipcompiler.cli.project.rtl_import import RtlImportError, RtlImportPlan, plan_project_rtl
from chipcompiler.cli.project.toml_edit import set_scoped_key
from chipcompiler.project.api import project_manifest_mutator
from chipcompiler.project.manifest import CONFIG_FILENAME, ManifestError, load_manifest
from chipcompiler.project.manifest_write import (
    base_design_from_config,
    manifest_lock,
    manifest_range_for_flow,
    update_manifest_locked,
)
from chipcompiler.utility.file import write_text_atomic

_JOURNAL = ".workspace-draft-publish.json"
_STAGING = ".workspace-draft-rtl"


@dataclass(frozen=True)
class CreationDraft:
    project: Path
    project_id: str
    original: str
    updated: str
    rtl: RtlImportPlan | None

    def publish(self, cfg, flow_config, run_name: str, run_dir: str, *, blocking: bool) -> None:
        path = self.project / CONFIG_FILENAME
        with manifest_lock(self.project, blocking=blocking):
            manifest = load_manifest(str(self.project))
            if manifest.project_id != self.project_id or path.read_text() != self.original:
                raise ValueError(
                    "Project configuration changed during Workspace creation. "
                    "Retry with the current settings."
                )
            journal = self.project / _JOURNAL
            if journal.exists() or journal.is_symlink():
                raise ValueError("An unfinished Workspace draft requires project reconcile.")
            workspace = Path(run_dir)
            if workspace != self.project / run_name or workspace.resolve() != workspace:
                raise ValueError("Draft Workspace is outside the Project.")
            staging = workspace / "home" / _STAGING
            targets: list[str] = []
            if self.rtl is not None:
                targets = [str(target.relative_to(self.project)) for _, target in self.rtl.copied]
                if any((self.project / target).exists() for target in targets):
                    raise ValueError("An RTL target already exists.")
                replace(
                    self.rtl,
                    copied=[
                        (source, staging / target)
                        for (source, _), target in zip(self.rtl.copied, targets, strict=True)
                    ],
                ).copy()
                cfg = replace(cfg, design_rtl=self.rtl.configured_paths)
            start, end = manifest_range_for_flow(cfg, flow_config)
            identity = workspace.stat()
            record = {
                "version": 1,
                "project_id": self.project_id,
                "workspace": run_name,
                "device": identity.st_dev,
                "inode": identity.st_ino,
                "original": self.original,
                "updated": self.updated,
                "rtl": targets,
                "start_step": start,
                "end_step": end,
                "skip_steps": (flow_config or {}).get("skip_steps"),
            }
            write_text_atomic(journal, json.dumps(record))
            try:
                with ExitStack() as rollback:
                    _publish_locked(self.project, record, rollback)
                    rollback.pop_all()
            except Exception:
                journal.unlink()
                raise
            # Registration is already committed. Reconcile can retry cleanup.
            with suppress(OSError):
                _clear_journal(journal, staging)


def reconcile_creation_draft(project: Path, *, blocking: bool) -> str | None:
    from chipcompiler.utility.workspace_lock import workspace_lock

    journal = project / _JOURNAL
    if not journal.exists() and not journal.is_symlink():
        return None
    with manifest_lock(project, blocking=blocking):
        if journal.is_symlink():
            raise OSError("Workspace draft journal must be a regular file")
        if not journal.exists():
            return None
        raw = journal.read_text(encoding="utf-8")
        try:
            record = json.loads(raw)
        except ValueError as exc:
            raise OSError("Invalid Workspace draft journal") from exc
        workspace = _journal_workspace(project, record)
    with workspace_lock(workspace, blocking=blocking), manifest_lock(project, blocking=blocking):
        if not journal.exists() or journal.read_text(encoding="utf-8") != raw:
            return None
        _publish_locked(project, record)
        _clear_journal(journal, workspace / "home" / _STAGING)
        return workspace.name


def _journal_workspace(project: Path, record: dict) -> Path:
    if not isinstance(record, dict) or record.get("version") != 1:
        raise OSError("Invalid Workspace draft journal")
    name = record.get("workspace")
    if not isinstance(name, str) or Path(name).name != name or name in ("", ".", ".."):
        raise OSError("Invalid Workspace draft target")
    workspace = project / name
    if workspace.resolve() != workspace or not workspace.is_dir():
        raise OSError("Workspace draft target is unavailable")
    identity = workspace.stat()
    if (identity.st_dev, identity.st_ino) != (record.get("device"), record.get("inode")):
        raise OSError("Workspace draft target changed")
    return workspace


def _publish_locked(project: Path, record: dict, rollback: ExitStack | None = None) -> None:
    workspace = _journal_workspace(project, record)
    manifest = load_manifest(str(project))
    if manifest.project_id != record["project_id"]:
        raise ManifestError("Project identity changed during Workspace creation")
    entry = manifest.find_workspace(workspace.name)
    if entry is not None:
        if Path(entry.workspace_path).resolve() != workspace:
            raise ManifestError("Draft Workspace identity conflicts with the Project Manifest")
        return

    path = project / CONFIG_FILENAME
    original, updated = record["original"], record["updated"]
    current = path.read_text(encoding="utf-8")
    if current not in (original, updated):
        raise OSError("Project configuration changed after an interrupted Workspace draft")
    cfg = parse_project_config(updated, str(path))
    staging = workspace / "home" / _STAGING
    for target in record["rtl"]:
        relative = Path(target)
        source, destination = staging / relative, project / relative
        if (
            relative.is_absolute()
            or len(relative.parts) < 2
            or relative.parts[0] != "rtl"
            or ".." in relative.parts
            or source.resolve() != source
            or destination.resolve() != destination
        ):
            raise OSError("Invalid RTL path in Workspace draft")
        if destination.exists() and destination.samefile(source):
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.hardlink_to(source)
        if rollback is not None:
            rollback.callback(destination.unlink, missing_ok=True)
    register = project_manifest_mutator(
        project,
        {
            "type": "register_workspace",
            "workspace_id": workspace.name,
            "name": cfg.design_name,
            "workspace_path": str(workspace),
            "start_step": record["start_step"],
            "end_step": record["end_step"],
        },
    )
    base_design = base_design_from_config(cfg, resolve_pdk_root(cfg))

    def mutate(document: dict) -> None:
        register(document)
        document["design_name"] = cfg.design_name
        document["base_design"] = base_design
        if record["skip_steps"] is not None:
            next(
                entry for entry in document["workspaces"] if entry["workspace_id"] == workspace.name
            )["skip_steps"] = record["skip_steps"]

    if current != updated:
        write_text_atomic(path, updated)
        if rollback is not None:
            rollback.callback(write_text_atomic, path, original)
    if not update_manifest_locked(project, mutate):
        raise OSError("Project Manifest update failed")


def _clear_journal(journal: Path, staging: Path) -> None:
    if staging.resolve() != staging:
        raise OSError("Invalid RTL staging directory in Workspace draft")
    if staging.is_dir():
        shutil.rmtree(staging)
    journal.unlink()


def prepare_creation_draft(ctx, raw: str):
    """Produce the config used by both preview and creation, without writing."""
    project = Path(ctx.project_dir)
    path = project / CONFIG_FILENAME
    try:
        data = json.loads(raw)
        allowed = {
            "settings",
            "enable",
            "disable",
            "insert",
            "remove",
            "maxParallelSteps",
            "filelist",
            "rtl",
        }
        if not isinstance(data, dict) or data.keys() - allowed:
            raise ValueError("Invalid Workspace draft fields")

        def strings(key: str) -> tuple[str, ...]:
            value = data.get(key, [])
            if not isinstance(value, list) or any(
                not isinstance(item, str) or not item for item in value
            ):
                raise ValueError(f"{key} must be a list of nonempty strings")
            return tuple(value)

        manifest = load_manifest(str(project))
        original = path.read_text(encoding="utf-8")
        updated = apply_settings_text(original, strings("settings"))
        cfg = parse_project_config(updated, str(path))
        enable, disable, insert, remove = (
            strings(key) for key in ("enable", "disable", "insert", "remove")
        )
        if enable or disable:
            skip = toggled_skip_steps(
                effective_skip_steps(cfg, None), enable=enable, disable=disable
            )
            updated = set_scoped_key(updated, "flow", "skip_steps", list(skip))
        if insert or remove:
            checks = changed_insert_steps(
                effective_insert_steps(cfg, None), insert=insert, remove=remove
            )
            updated = set_scoped_key(updated, "flow", "insert_steps", list(checks))
        if "maxParallelSteps" in data:
            from chipcompiler.cli.project.config import _max_parallel_steps_problem

            limit = data["maxParallelSteps"]
            if problem := _max_parallel_steps_problem(limit):
                raise ValueError(problem)
            updated = set_scoped_key(updated, "flow", "max_parallel_steps", limit)
        filelist, verilog = data.get("filelist"), strings("rtl")
        if filelist is not None and (not isinstance(filelist, str) or not filelist):
            raise ValueError("filelist must be a nonempty path")
        rtl = (
            plan_project_rtl(project, filelist=filelist, verilog=verilog)
            if filelist or verilog
            else None
        )
        if rtl:
            updated = set_scoped_key(updated, "design", "rtl", rtl.configured_paths)
        cfg = parse_project_config(updated, str(path))
        if rtl:
            cfg.design_rtl = rtl.source_paths
        draft = CreationDraft(project, manifest.project_id, original, updated, rtl)
        return replace(ctx, config=cfg, config_error=None), draft
    except (ProjectApplicationError, RtlImportError, ManifestError, OSError, ValueError) as exc:
        return CommandResult.err(
            [error_record(getattr(exc, "code", "invalid_workspace_draft"), reason=str(exc))]
        )
