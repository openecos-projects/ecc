"""Validate one Workspace creation draft and publish its Project changes."""

import json
import shutil
import stat
from contextlib import contextmanager, suppress
from copy import copy
from dataclasses import dataclass, replace
from pathlib import Path
from tempfile import mkdtemp

from chipcompiler.cli.core.records import error_record
from chipcompiler.cli.core.types import CommandResult
from chipcompiler.cli.project.config import ProjectConfig, parse_project_config, resolve_pdk_root
from chipcompiler.cli.project.design_inputs import resolve_design_inputs
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
from chipcompiler.cli.project.rtl_import import (
    RtlImportError,
    RtlImportPlan,
    plan_project_rtl,
    require_rtl_target_parents,
)
from chipcompiler.cli.project.toml_edit import set_scoped_key
from chipcompiler.project.api import project_manifest_mutator
from chipcompiler.project.manifest import CONFIG_FILENAME, ManifestError, load_manifest
from chipcompiler.project.manifest_write import (
    base_design_from_config,
    manifest_lock,
    manifest_range_for_flow,
    update_manifest_locked,
)
from chipcompiler.utility.file import file_digest, write_text_atomic
from chipcompiler.utility.filelist import FILELIST_SUFFIXES

_JOURNAL = ".workspace-draft-publish.json"
_STAGING_ROOT = ".workspace-draft-builds"
_STAGING_OWNER = ".owner"
_LEGACY_RTL = ".workspace-draft-rtl"
_CONFIG_STAGE = "ecc.toml.next"
DRAFT_PROJECT_CHANGES_SKIPPED = "draft_project_changes_skipped"


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
        if workspace.parent != self.project or workspace.resolve() != workspace:
            raise OSError("Draft Workspace is outside the Project.")
        if workspace.name == _STAGING_ROOT:
            raise FileExistsError(f"Workspace path is reserved: {workspace}")
        require_draft_published(self.project, workspace)
        _check_destination(workspace, reuse_empty=reuse_empty)
        _prepare_staging_root(self.project)
        staging = _staging(self.project, workspace)
        _discard_staging(staging)
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
            if not _has_pending_draft(self.project, workspace):
                _discard_staging(staging)

    def publish(
        self, cfg: ProjectConfig, flow_config, workspace: Path, *, reuse_empty: bool, blocking: bool
    ) -> PublicationResult:
        """Publish a completed staging tree, or leave enough evidence to resume."""
        from chipcompiler.engine.workspace.lifecycle import _rewrite_workspace_paths

        journal = self.project / _JOURNAL
        staging = _staging(self.project, workspace)
        built = staging / "workspace"
        _rewrite_workspace_paths(built, workspace)
        # Workspace configs and generated tool scripts are published together.
        for pattern in ("*/data/*.tcl", "*/script/*.tcl"):
            for path in built.glob(pattern):
                original = path.read_text(encoding="utf-8")
                updated = original.replace(f"{built}/", f"{workspace}/")
                if updated != original:
                    write_text_atomic(path, updated)
        targets = (
            [target.relative_to(self.project).as_posix() for _, target in self.rtl.copied]
            if self.rtl is not None
            else []
        )
        config = self.project / CONFIG_FILENAME
        next_config = staging / _CONFIG_STAGE
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
            empty_mode = _check_destination(workspace, reuse_empty=reuse_empty)
            next_config.chmod(stat.S_IMODE(config.stat().st_mode))
            record = {
                "version": 3,
                "project_id": self.project_id,
                "workspace": workspace.name,
                "device": identity.st_dev,
                "inode": identity.st_ino,
                "original": self.original,
                "updated": self.updated,
                "rtl": targets,
                "start_step": start,
                "end_step": end,
                "skip_steps": (flow_config or {}).get("skip_steps"),
                "empty_mode": empty_mode,
            }
            rtl_paths = _rtl_paths(self.project, staging, targets)
            _rtl_links(rtl_paths, {})
            digests = {}
            for source, destination in rtl_paths:
                digest = file_digest(source)
                if digest is None:
                    raise OSError(f"Could not read staged RTL: {source}")
                digests[destination.relative_to(self.project).as_posix()] = digest[0]
            record["rtl_sha256"] = digests
            write_text_atomic(journal, json.dumps(record))
            try:
                result = _publish_locked(self.project, record)
            except (OSError, ValueError) as exc:
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

    journal = project / _JOURNAL
    record = _read_journal(journal)
    repaired = None
    if record is not None:
        workspace = _journal_target(project, record)
        with (
            workspace_lock(workspace, blocking=blocking),
            manifest_lock(project, blocking=blocking),
        ):
            current = _read_journal(journal)
            if current is not None and _journal_target(project, current) == workspace:
                if current.get("phase") == "building":
                    _preserve_legacy_build(project, workspace, current)
                else:
                    _publish_locked(project, current)
                _finish(project, current, journal)
                repaired = workspace.name

    root = project / _STAGING_ROOT
    if _owns_staging_root(root):
        for staging in (root / "workspaces").iterdir():
            if not staging.is_dir() or staging.is_symlink():
                continue
            workspace = project / staging.name
            try:
                with workspace_lock(workspace, blocking=False):
                    if not _has_pending_draft(project, workspace):
                        _discard_staging(staging)
            except BlockingIOError:
                # An active build in its private directory needs no recovery.
                continue
    return repaired


def require_draft_published(project: Path, workspace: Path) -> None:
    """Keep a partially published draft from being used as a managed Workspace."""
    project = project.resolve()
    workspace = workspace.resolve()
    if workspace.parent == project and _has_pending_draft(project, workspace):
        raise OSError("An unfinished Workspace draft requires project reconcile.")


def _has_pending_draft(project: Path, workspace: Path) -> bool:
    record = _read_journal(project / _JOURNAL)
    return record is not None and _journal_target(project, record) == workspace


def _read_journal(journal: Path) -> dict | None:
    if journal.is_symlink():
        raise OSError("Workspace draft journal must be a regular file")
    try:
        record = json.loads(journal.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except ValueError as exc:
        raise OSError("Invalid Workspace draft journal") from exc
    if not isinstance(record, dict) or record.get("version") not in (1, 2, 3):
        raise OSError("Invalid Workspace draft journal")
    return record


def _journal_target(project: Path, record: dict) -> Path:
    name = record.get("workspace")
    if not isinstance(name, str) or Path(name).name != name or name in ("", ".", ".."):
        raise OSError("Invalid Workspace draft target")
    return project / name


def _staging(project: Path, workspace: Path) -> Path:
    root = project / _STAGING_ROOT
    staging = root / "workspaces" / workspace.name
    if not _owns_staging_root(root) or staging.resolve() != staging:
        raise OSError("Workspace draft staging must be a direct directory")
    return staging


def _owns_staging_root(root: Path) -> bool:
    owner = root / _STAGING_OWNER
    return (
        root.is_dir()
        and not root.is_symlink()
        and not owner.is_symlink()
        and owner.is_file()
        and owner.read_text(encoding="utf-8") == "ecc workspace draft staging\n"
        and (root / "workspaces").is_dir()
        and not (root / "workspaces").is_symlink()
    )


def _prepare_staging_root(project: Path) -> None:
    root = project / _STAGING_ROOT
    if _owns_staging_root(root):
        return
    if root.exists() or root.is_symlink():
        raise FileExistsError(f"Workspace draft staging path is already occupied: {root}")
    # Publish ownership and the directory together, including when two distinct
    # Workspace builds start before either takes the Project lock.
    staging = Path(mkdtemp(prefix=".workspace-draft-root-", dir=project))
    try:
        (staging / "workspaces").mkdir()
        write_text_atomic(staging / _STAGING_OWNER, "ecc workspace draft staging\n")
        try:
            staging.rename(root)
        except OSError:
            if not _owns_staging_root(root):
                raise
    finally:
        _discard_staging(staging)


def _discard_staging(staging: Path) -> None:
    if staging.resolve() != staging:
        raise OSError("Workspace draft staging must be a direct directory")
    if staging.is_dir():
        shutil.rmtree(staging)


def _owns_directory(path: Path, record: dict) -> bool:
    if path.resolve() != path or not path.is_dir():
        return False
    identity = path.stat()
    return (identity.st_dev, identity.st_ino) == (record.get("device"), record.get("inode"))


def _check_destination(workspace: Path, *, reuse_empty: bool) -> int | None:
    if workspace.is_symlink():
        raise FileExistsError(f"Workspace is a symbolic link: {workspace}")
    if not workspace.exists():
        return None
    if not (reuse_empty and workspace.is_dir() and not any(workspace.iterdir())):
        raise FileExistsError(f"Workspace already exists: {workspace}")
    return stat.S_IMODE(workspace.stat().st_mode)


def _preserve_legacy_build(project: Path, workspace: Path, record: dict) -> None:
    manifest = load_manifest(str(project))
    if manifest.project_id != record["project_id"] or manifest.find_workspace(workspace.name):
        raise OSError("Workspace draft registration changed")
    # Version 1 built in the target and cannot distinguish later user files.
    if _owns_directory(workspace, record):
        archive = Path(mkdtemp(prefix=".interrupted-workspace-draft-", dir=project))
        workspace.rename(archive / workspace.name)
        if record.get("reserved_in") is None:
            workspace.mkdir(mode=stat.S_IMODE((archive / workspace.name).stat().st_mode))


def _rtl_paths(project: Path, staging: Path, targets: list[str]) -> list[tuple[Path, Path]]:
    paths = []
    for target in targets:
        relative = Path(target)
        if relative.is_absolute() or relative.parts[:1] != ("rtl",) or ".." in relative.parts:
            raise OSError("Invalid RTL path in Workspace draft")
        source = staging / relative
        if len(relative.parts) < 2 or source.resolve() != source or not source.is_file():
            raise OSError("Invalid staged RTL in Workspace draft")
        paths.append((source, project / relative))
    return paths


def _rtl_links(paths: list[tuple[Path, Path]], digests: dict[Path, str]) -> list[tuple[Path, Path]]:
    links = []
    for source, destination in paths:
        if destination.resolve() != destination:
            raise FileExistsError(f"RTL target is a symbolic link: {destination}")
        require_rtl_target_parents(destination)
        if destination.exists():
            if destination.is_file() and destination.samefile(source):
                expected = digests.get(destination)
                if expected is None or _matches_digest(source, expected):
                    continue
            raise FileExistsError(f"RTL target already exists: {destination}")
        links.append((source, destination))
    return links


def _matches_digest(source: Path, expected: str) -> bool:
    digest = file_digest(source)
    return digest is not None and digest[0] == expected


def _discard_partial_rtl(
    cfg: ProjectConfig,
    paths: list[tuple[Path, Path]],
    digests: dict[Path, str],
) -> None:
    inputs = resolve_design_inputs(cfg)
    selected = {Path(path).resolve() for path in inputs.paths()}
    # A selected filelist can refer to other files in the same import.
    filelists = [
        Path(path) for path in inputs.rtl if Path(path).suffix.lower() in FILELIST_SUFFIXES
    ]
    if filelists:
        from chipcompiler.utility.filelist import parse_filelist, parse_incdir_directives

        include_dirs = set()
        for path in filelists:
            try:
                selected.update(
                    (path.parent / item).resolve() for item in parse_filelist(str(path))
                )
                include_dirs.update(
                    (path.parent / item).resolve() for item in parse_incdir_directives(str(path))
                )
            except (OSError, ValueError):
                return
        selected.update(
            destination
            for _, destination in paths
            if any(destination.is_relative_to(directory) for directory in include_dirs)
        )
    for source, destination in paths:
        expected = digests.get(destination)
        if (
            expected is not None
            and destination not in selected
            and destination.resolve() == destination
            and destination.is_file()
            and destination.samefile(source)
            and _matches_digest(source, expected)
        ):
            destination.unlink()


def _publish_locked(project: Path, record: dict) -> PublicationResult:
    workspace = _journal_target(project, record)
    manifest = load_manifest(str(project))
    if manifest.project_id != record["project_id"]:
        raise ManifestError("Project identity changed during Workspace creation")
    installed = _owns_directory(workspace, record)
    entry = manifest.find_workspace(workspace.name)
    if entry is not None:
        if not installed or Path(entry.workspace_path).resolve() != workspace:
            raise ManifestError("Draft Workspace identity conflicts with the Project Manifest")
        return PublicationResult(
            workspace_created=True,
            project_changes_skipped=entry.raw.get(DRAFT_PROJECT_CHANGES_SKIPPED),
        )

    legacy = record["version"] == 1
    staging = workspace / "home" / _LEGACY_RTL if legacy else _staging(project, workspace)
    config = project / CONFIG_FILENAME
    next_config = staging / _CONFIG_STAGE
    current = config.read_text(encoding="utf-8")
    original, updated = record["original"], record["updated"]
    # The atomic move consumes ecc.toml.next. Later Project edits then win,
    # including an edit that restores the original bytes.
    pending_config = current != updated if legacy else next_config.is_file()
    skipped = record.get(DRAFT_PROJECT_CHANGES_SKIPPED)
    links = []
    paths = []
    digests = {project / path: digest for path, digest in record.get("rtl_sha256", {}).items()}
    if pending_config or skipped:
        paths = _rtl_paths(project, staging, record["rtl"])
    if pending_config and not skipped:
        if current not in (original, updated):
            skipped = "Project configuration changed before the draft could update it."
        else:
            try:
                links = _rtl_links(paths, digests)
            except FileExistsError as exc:
                skipped = str(exc)
    if not installed:
        if skipped:
            return PublicationResult(workspace_created=False, project_changes_skipped=skipped)
        built = staging / "workspace"
        if legacy or not _owns_directory(built, record):
            raise OSError("Workspace draft staging changed")
        try:
            mode = _check_destination(workspace, reuse_empty=record["empty_mode"] is not None)
        except FileExistsError as exc:
            return PublicationResult(workspace_created=False, project_changes_skipped=str(exc))
        if mode is not None:
            built.chmod(mode)
        built.rename(workspace)

    if pending_config and not skipped:
        try:
            for source, destination in links:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.hardlink_to(source)
        except (FileExistsError, NotADirectoryError, IsADirectoryError) as exc:
            # The filesystem may change after checking all targets.
            skipped = str(exc)

    draft_config = parse_project_config(updated, str(config))
    cfg = (
        draft_config
        if pending_config and not skipped
        else parse_project_config(current, str(config))
    )
    if skipped:
        if DRAFT_PROJECT_CHANGES_SKIPPED not in record:
            record = {**record, DRAFT_PROJECT_CHANGES_SKIPPED: skipped}
            write_text_atomic(project / _JOURNAL, json.dumps(record))
        _discard_partial_rtl(cfg, paths, digests)
    elif pending_config:
        if legacy:
            write_text_atomic(config, updated)
        else:
            next_config.replace(config)

    register = project_manifest_mutator(
        project,
        {
            "type": "register_workspace",
            "workspace_id": workspace.name,
            "name": draft_config.design_name,
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
        entry = next(
            item for item in document["workspaces"] if item["workspace_id"] == workspace.name
        )
        if record["skip_steps"] is not None:
            entry["skip_steps"] = record["skip_steps"]
        if skipped:
            entry[DRAFT_PROJECT_CHANGES_SKIPPED] = skipped

    if not update_manifest_locked(project, mutate):
        raise OSError("Project Manifest update failed")
    return PublicationResult(workspace_created=True, project_changes_skipped=skipped)


def _finish(project: Path, record: dict, journal: Path) -> None:
    workspace = _journal_target(project, record)
    if record["version"] != 1:
        journal.unlink()
        _discard_staging(_staging(project, workspace))
    else:
        if record.get("phase") != "building":
            _discard_staging(workspace / "home" / _LEGACY_RTL)
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
