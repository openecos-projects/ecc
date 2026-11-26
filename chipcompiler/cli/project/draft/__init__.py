"""Validate one Workspace creation draft and publish its Project changes."""

import json
import stat
from contextlib import contextmanager, suppress
from copy import copy
from dataclasses import dataclass, replace
from pathlib import Path

from chipcompiler.cli.core.records import error_record
from chipcompiler.cli.core.types import CommandResult
from chipcompiler.cli.project.config import (
    ProjectConfig,
    max_parallel_steps_problem,
    parse_project_config,
)
from chipcompiler.cli.project.draft.journal import (
    CONFIG_STAGE,
    DRAFT_PROJECT_CHANGES_SKIPPED,
    JOURNAL_FILENAME,
    STAGING_ROOT,
    DraftJournal,
    check_destination,
    discard_staging,
    has_pending_draft,
    owns_directory,
    owns_staging_root,
    prepare_staging_root,
    read_journal,
    staging_dir,
    validate_draft_destination,
)
from chipcompiler.cli.project.draft.rtl import (
    discard_partial_rtl,
    rtl_digests,
    rtl_links,
    rtl_paths,
)
from chipcompiler.cli.project.effective_config import (
    apply_manifest_defaults,
    project_manifest_summary,
)
from chipcompiler.cli.project.flow_selection import (
    changed_insert_steps,
    effective_insert_steps,
    effective_skip_steps,
    toggled_skip_steps,
)
from chipcompiler.cli.project.project_application import (
    ProjectApplicationError,
    apply_settings_text,
    parse_project_settings,
    read_project_settings,
)
from chipcompiler.cli.project.rtl_import import (
    RtlImportError,
    RtlImportPlan,
    plan_project_rtl,
)
from chipcompiler.cli.project.toml_edit import set_scoped_key
from chipcompiler.project.api import project_manifest_mutator
from chipcompiler.project.manifest import (
    CONFIG_FILENAME,
    ManifestError,
    assemble_config,
    load_manifest,
)
from chipcompiler.project.manifest_write import (
    manifest_lock,
    manifest_range_for_flow,
    update_manifest_locked,
)
from chipcompiler.utility.file import write_text_atomic

__all__ = [
    "DRAFT_PROJECT_CHANGES_SKIPPED",
    "CreationDraft",
    "DraftJournal",
    "DraftPublicationPending",
    "PublicationResult",
    "prepare_creation_draft",
    "reconcile_creation_draft",
    "require_draft_published",
    "validate_draft_destination",
]


class DraftPublicationPending(OSError):
    """A journaled publish requires recovery before it can finish."""


@dataclass(frozen=True)
class PublicationResult:
    workspace_created: bool
    project_changes_skipped: str | None = None


@dataclass(frozen=True)
class CreationDraft:
    project: Path
    project_id: str
    original: str
    updated: str
    rtl: RtlImportPlan | None

    @contextmanager
    def build_target(self, workspace: Path, cfg: ProjectConfig, *, reuse_empty: bool):
        """Build privately under the caller's lock on the final Workspace."""
        validate_draft_destination(self.project, workspace, reuse_empty=reuse_empty)
        prepare_staging_root(self.project)
        staging = staging_dir(self.project, workspace)
        discard_staging(staging)
        staging.mkdir(mode=0o700)
        try:
            self._stage_rtl(staging)
            if self.rtl is not None:
                cfg = copy(cfg)
                cfg.design_rtl = [str(staging / path) for path in self.rtl.configured_paths]
            yield staging / "workspace", cfg
        finally:
            # The journal is replaced atomically. This Workspace's lock prevents
            # another caller from creating or recovering a journal for this target.
            if not has_pending_draft(self.project, workspace):
                discard_staging(staging)

    def publish(
        self, cfg: ProjectConfig, flow_config, workspace: Path, *, reuse_empty: bool, blocking: bool
    ) -> PublicationResult:
        """Publish a completed staging tree, or leave enough evidence to resume."""
        journal = self.project / JOURNAL_FILENAME
        staging = staging_dir(self.project, workspace)
        built = staging / "workspace"
        targets = (
            tuple(target.relative_to(self.project).as_posix() for _, target in self.rtl.copied)
            if self.rtl is not None
            else ()
        )
        config = self.project / CONFIG_FILENAME
        next_config = staging / CONFIG_STAGE
        write_text_atomic(next_config, self.updated)
        start, end = manifest_range_for_flow(cfg, flow_config)
        identity = built.stat()
        with manifest_lock(self.project, blocking=blocking):
            if journal.exists() or journal.is_symlink():
                raise OSError("An unfinished Workspace draft requires project reconcile.")
            manifest = load_manifest(str(self.project))
            if (
                manifest.project_id != self.project_id
                or config.read_text(encoding="utf-8") != self.original
            ):
                raise ValueError(
                    "Project configuration changed during Workspace creation. "
                    "Retry with the current settings."
                )
            if manifest.find_workspace(workspace.name) is not None:
                raise FileExistsError(f"Workspace already registered: {workspace.name}")
            empty_mode = check_destination(workspace, reuse_empty=reuse_empty)
            next_config.chmod(stat.S_IMODE(config.stat().st_mode))
            staged_rtl = rtl_paths(self.project, staging, targets)
            rtl_links(staged_rtl, {})
            digests = rtl_digests(self.project, staged_rtl)
            record = DraftJournal(
                project_id=self.project_id,
                workspace=workspace.name,
                device=identity.st_dev,
                inode=identity.st_ino,
                original=self.original,
                updated=self.updated,
                rtl=targets,
                rtl_sha256=digests,
                start_step=start,
                end_step=end,
                skip_steps=(flow_config or {}).get("skip_steps"),
                empty_mode=empty_mode,
            )
            write_text_atomic(journal, json.dumps(record.to_dict()))
            try:
                result = _publish_locked(self.project, record)
            except (OSError, ProjectApplicationError, ValueError) as exc:
                raise DraftPublicationPending(
                    f"{exc}. Run ecc project reconcile to finish."
                ) from exc
            with suppress(OSError):
                _finish(self.project, record, journal)
            return result

    def _stage_rtl(self, staging: Path) -> None:
        if self.rtl is None:
            return
        replace(
            self.rtl,
            copied=[
                (source, staging / target.relative_to(self.project))
                for source, target in self.rtl.copied
            ],
            include_dirs={
                source: staging / target.relative_to(self.project)
                for source, target in self.rtl.include_dirs.items()
            },
        ).copy()


def reconcile_creation_draft(project: Path, *, blocking: bool) -> str | None:
    from chipcompiler.utility.workspace_lock import workspace_lock

    journal = project / JOURNAL_FILENAME
    record = read_journal(journal)
    repaired = None
    if record is not None:
        workspace = record.target(project)
        with (
            workspace_lock(workspace, blocking=blocking),
            manifest_lock(project, blocking=blocking),
        ):
            current = read_journal(journal)
            if current is not None and current.target(project) == workspace:
                _publish_locked(project, current)
                _finish(project, current, journal)
                repaired = workspace.name

    root = project / STAGING_ROOT
    if owns_staging_root(root):
        for staging in (root / "workspaces").iterdir():
            if not staging.is_dir() or staging.is_symlink():
                continue
            workspace = project / staging.name
            try:
                with workspace_lock(workspace, blocking=False):
                    if not has_pending_draft(project, workspace):
                        discard_staging(staging)
            except BlockingIOError:
                # An active build in its private directory needs no recovery.
                continue
    return repaired


def require_draft_published(project: Path, workspace: Path) -> None:
    """Keep a partially published draft from being used as a managed Workspace."""
    project = project.resolve()
    workspace = workspace.resolve()
    if workspace.parent == project and has_pending_draft(project, workspace):
        raise OSError("An unfinished Workspace draft requires project reconcile.")


def _plan_project_changes(
    project: Path,
    staging: Path,
    record: DraftJournal,
    current: str,
    *,
    pending_config: bool,
) -> tuple[list[tuple[Path, Path]], list[tuple[Path, Path]], dict[Path, str], str | None]:
    skipped = record.project_changes_skipped
    digests = {project / path: digest for path, digest in record.rtl_sha256.items()}
    paths = rtl_paths(project, staging, record.rtl) if (pending_config or skipped) else []
    links: list[tuple[Path, Path]] = []
    if pending_config and not skipped:
        if current not in (record.original, record.updated):
            skipped = "Project configuration changed before the draft could update it."
        else:
            try:
                links = rtl_links(paths, digests)
            except FileExistsError as exc:
                skipped = str(exc)
    return paths, links, digests, skipped


def _install_staged_workspace(staging: Path, workspace: Path, record: DraftJournal) -> str | None:
    built = staging / "workspace"
    if not owns_directory(built, record):
        raise OSError("Workspace draft staging changed")
    try:
        mode = check_destination(workspace, reuse_empty=record.empty_mode is not None)
    except FileExistsError as exc:
        return str(exc)
    if mode is not None:
        built.chmod(mode)
    built.rename(workspace)
    return None


def _publish_locked(project: Path, record: DraftJournal) -> PublicationResult:
    workspace = record.target(project)
    manifest = load_manifest(str(project))
    if manifest.project_id != record.project_id:
        raise ManifestError("Project identity changed during Workspace creation")
    installed = owns_directory(workspace, record)
    entry = manifest.find_workspace(workspace.name)
    if entry is not None:
        if not installed or Path(entry.workspace_path).resolve() != workspace:
            raise ManifestError("Draft Workspace identity conflicts with the Project Manifest")
        return PublicationResult(
            workspace_created=True,
            project_changes_skipped=entry.raw.get(DRAFT_PROJECT_CHANGES_SKIPPED),
        )

    staging = staging_dir(project, workspace)
    config = project / CONFIG_FILENAME
    next_config = staging / CONFIG_STAGE
    current = read_project_settings(project)
    current_config = parse_project_settings(project, current)
    draft_config = (
        current_config
        if current == record.updated
        else parse_project_settings(project, record.updated)
    )
    # The atomic move consumes ecc.toml.next. Later Project edits then win,
    # including an edit that restores the original bytes.
    pending_config = next_config.is_file()
    paths, links, digests, skipped = _plan_project_changes(
        project, staging, record, current, pending_config=pending_config
    )
    if not installed:
        if skipped:
            return PublicationResult(workspace_created=False, project_changes_skipped=skipped)
        conflict = _install_staged_workspace(staging, workspace, record)
        if conflict is not None:
            return PublicationResult(workspace_created=False, project_changes_skipped=conflict)

    if pending_config and not skipped:
        try:
            for source, destination in links:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.hardlink_to(source)
        except (FileExistsError, NotADirectoryError, IsADirectoryError) as exc:
            # The filesystem may change after checking all targets.
            skipped = str(exc)

    cfg = draft_config if pending_config and not skipped else current_config
    project_name, base_design = project_manifest_summary(cfg, manifest)
    if skipped:
        if record.project_changes_skipped is None:
            record = replace(record, project_changes_skipped=skipped)
            write_text_atomic(project / JOURNAL_FILENAME, json.dumps(record.to_dict()))
        apply_manifest_defaults(cfg, assemble_config(manifest, None), str(project))
        discard_partial_rtl(cfg, paths, digests)
    elif pending_config:
        next_config.replace(config)

    _register_workspace_locked(
        project, workspace, manifest, draft_config, record, project_name, base_design, skipped
    )
    return PublicationResult(workspace_created=True, project_changes_skipped=skipped)


def _register_workspace_locked(
    project: Path,
    workspace: Path,
    manifest,
    draft_config: ProjectConfig,
    record: DraftJournal,
    project_name: str,
    base_design: dict,
    skipped: str | None,
) -> None:
    register = project_manifest_mutator(
        project,
        {
            "type": "register_workspace",
            "workspace_id": workspace.name,
            "name": draft_config.design_name
            if "design.name" in draft_config._explicit_keys
            else manifest.design_name,
            "workspace_path": str(workspace),
            "start_step": record.start_step,
            "end_step": record.end_step,
        },
    )

    def mutate(document: dict) -> None:
        register(document)
        document["design_name"] = project_name
        document["base_design"] = base_design
        entry = next(
            item for item in document["workspaces"] if item["workspace_id"] == workspace.name
        )
        if record.skip_steps is not None:
            entry["skip_steps"] = record.skip_steps
        if skipped:
            entry[DRAFT_PROJECT_CHANGES_SKIPPED] = skipped

    if not update_manifest_locked(project, mutate):
        raise OSError("Project Manifest update failed")


def _finish(project: Path, record: DraftJournal, journal: Path) -> None:
    workspace = record.target(project)
    journal.unlink()
    discard_staging(staging_dir(project, workspace))


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
            limit = data["maxParallelSteps"]
            if problem := max_parallel_steps_problem(limit):
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
