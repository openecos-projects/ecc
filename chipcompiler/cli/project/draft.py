"""Validate one Workspace creation draft and publish its Project changes."""

import json
import shutil
from contextlib import ExitStack, contextmanager, suppress
from dataclasses import dataclass, replace
from pathlib import Path
from tempfile import TemporaryDirectory

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
_BUILD_PREFIX = ".workspace-draft-build-"


@dataclass(frozen=True)
class CreationDraft:
    project: Path
    project_id: str
    original: str
    updated: str
    rtl: RtlImportPlan | None

    @contextmanager
    def build_target(self, workspace: Path, *, reuse_empty: bool, blocking: bool):
        """Record ownership before construction can leave a partial Workspace."""
        journal = self.project / _JOURNAL
        with manifest_lock(self.project, blocking=blocking):
            if journal.exists() or journal.is_symlink():
                raise OSError("An unfinished Workspace draft requires project reconcile.")
            if workspace.resolve() != workspace or workspace.parent != self.project:
                raise OSError("Draft Workspace is outside the Project.")
            manifest = load_manifest(str(self.project))
            if manifest.project_id != self.project_id:
                raise OSError("Project identity changed during Workspace creation.")
            if manifest.find_workspace(workspace.name) is not None:
                raise FileExistsError(f"Workspace already registered: {workspace.name}")
            existing = workspace.exists()
            if existing and not (
                reuse_empty and workspace.is_dir() and not any(workspace.iterdir())
            ):
                raise FileExistsError(f"Workspace already exists: {workspace}")
            with ExitStack() as reservation:
                if existing:
                    staged = workspace
                else:
                    container = Path(
                        reservation.enter_context(
                            TemporaryDirectory(prefix=_BUILD_PREFIX, dir=self.project)
                        )
                    )
                    staged = container / workspace.name
                    staged.mkdir()
                identity = staged.stat()
                building = {
                    "version": 1,
                    "phase": "building",
                    "project_id": self.project_id,
                    "workspace": workspace.name,
                    "device": identity.st_dev,
                    "inode": identity.st_ino,
                    "reserved_in": None if existing else staged.parent.name,
                }
                raw = json.dumps(building)
                write_text_atomic(journal, raw)
                if not existing:
                    try:
                        staged.rename(workspace)
                    except OSError:
                        journal.unlink()
                        raise
        try:
            yield
        finally:
            with manifest_lock(self.project):
                if journal.is_file() and journal.read_text(encoding="utf-8") == raw:
                    _discard_build(self.project, workspace, building, journal)

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
            building = _read_journal(journal)
            workspace = _journal_workspace(self.project, building)
            if (
                building.get("phase") != "building"
                or building.get("project_id") != self.project_id
                or workspace != Path(run_dir)
                or workspace.name != run_name
            ):
                raise OSError("Workspace draft reservation changed")
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
                    include_dirs={
                        source: staging / target.relative_to(self.project)
                        for source, target in self.rtl.include_dirs.items()
                    },
                ).copy()
                cfg = replace(cfg, design_rtl=self.rtl.configured_paths)
            start, end = manifest_range_for_flow(cfg, flow_config)
            record = {
                **building,
                "phase": "publishing",
                "original": self.original,
                "updated": self.updated,
                "rtl": targets,
                "start_step": start,
                "end_step": end,
                "skip_steps": (flow_config or {}).get("skip_steps"),
            }
            write_text_atomic(journal, json.dumps(record))
            rollback = ExitStack()
            try:
                _publish_locked(self.project, record, rollback)
            except Exception:
                rollback.close()
                write_text_atomic(journal, json.dumps(building))
                raise
            rollback.pop_all()
            # Registration is already committed. Reconcile can retry cleanup.
            with suppress(OSError):
                _clear_journal(journal, staging)


def reconcile_creation_draft(project: Path, *, blocking: bool) -> str | None:
    from chipcompiler.utility.workspace_lock import workspace_lock

    journal = project / _JOURNAL
    if not journal.exists() and not journal.is_symlink():
        return None
    with manifest_lock(project, blocking=blocking):
        if not journal.exists() and not journal.is_symlink():
            return None
        record = _read_journal(journal)
        workspace = _journal_target(project, record)
    with workspace_lock(workspace, blocking=blocking), manifest_lock(project, blocking=blocking):
        if not journal.exists() or _read_journal(journal) != record:
            return None
        if record.get("phase") == "building":
            _discard_build(project, workspace, record, journal)
        else:
            _publish_locked(project, record)
            _clear_journal(journal, workspace / "home" / _STAGING)
        return workspace.name


def require_draft_published(project: Path, workspace: Path) -> None:
    """Prevent adoption or replacement of a pending draft under the Workspace lock."""
    project = project.resolve()
    workspace = workspace.resolve()
    journal = project / _JOURNAL
    if workspace.parent == project and (journal.exists() or journal.is_symlink()):
        try:
            record = _read_journal(journal)
        except FileNotFoundError:
            return
        if _journal_target(project, record) == workspace:
            raise OSError("An unfinished Workspace draft requires project reconcile.")


def _read_journal(journal: Path) -> dict:
    if journal.is_symlink():
        raise OSError("Workspace draft journal must be a regular file")
    try:
        record = json.loads(journal.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise OSError("Invalid Workspace draft journal") from exc
    if not isinstance(record, dict) or record.get("version") != 1:
        raise OSError("Invalid Workspace draft journal")
    return record


def _journal_target(project: Path, record: dict) -> Path:
    name = record.get("workspace")
    if not isinstance(name, str) or Path(name).name != name or name in ("", ".", ".."):
        raise OSError("Invalid Workspace draft target")
    return project / name


def _owns_directory(path: Path, record: dict) -> bool:
    if path.resolve() != path or not path.is_dir():
        return False
    identity = path.stat()
    return (identity.st_dev, identity.st_ino) == (record.get("device"), record.get("inode"))


def _journal_workspace(project: Path, record: dict) -> Path:
    workspace = _journal_target(project, record)
    if not _owns_directory(workspace, record):
        raise OSError("Workspace draft target changed")
    return workspace


def _discard_build(project: Path, workspace: Path, record: dict, journal: Path) -> None:
    manifest = load_manifest(str(project))
    if manifest.project_id != record["project_id"] or manifest.find_workspace(workspace.name):
        raise OSError("Workspace draft registration changed")
    reservation = record["reserved_in"]
    if _owns_directory(workspace, record):
        if reservation is None:
            for child in workspace.iterdir():
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child)
                else:
                    child.unlink()
        else:
            shutil.rmtree(workspace)
    elif reservation is None:
        raise OSError("Workspace draft target changed")
    if reservation is not None:
        if Path(reservation).name != reservation or not reservation.startswith(_BUILD_PREFIX):
            raise OSError("Invalid Workspace draft reservation")
        container = project / reservation
        staged = container / workspace.name
        if container.exists():
            if _owns_directory(staged, record):
                staged.rmdir()
            if container.resolve() != container:
                raise OSError("Workspace draft reservation changed")
            container.rmdir()
    journal.unlink()


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
