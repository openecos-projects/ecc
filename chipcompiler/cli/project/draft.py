"""Validate one Workspace creation draft and publish its Project changes."""

import json
import shutil
import tempfile
from contextlib import contextmanager
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
from chipcompiler.cli.project.effective_config import project_manifest_summary
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
)
from chipcompiler.cli.project.rtl_import import (
    RtlImportError,
    RtlImportPlan,
    plan_project_rtl,
    require_rtl_target_parents,
)
from chipcompiler.cli.project.toml_edit import set_scoped_key
from chipcompiler.project.api import project_manifest_mutator
from chipcompiler.project.manifest import (
    CONFIG_FILENAME,
    ManifestError,
    ProjectManifest,
    load_manifest,
)
from chipcompiler.project.manifest_write import (
    manifest_lock,
    manifest_range_for_flow,
    update_manifest_locked,
)
from chipcompiler.utility.file import write_text_atomic

__all__ = [
    "CreationDraft",
    "prepare_creation_draft",
    "validate_draft_destination",
]


def validate_draft_destination(project: Path, workspace: Path, *, reuse_empty: bool) -> None:
    """Validate that *workspace* is an available direct child of *project*."""
    if workspace.is_symlink():
        raise FileExistsError(f"Workspace is a symbolic link: {workspace}")
    if workspace.parent != project:
        raise OSError("Draft Workspace is outside the Project.")
    if workspace.exists() and not (
        reuse_empty and workspace.is_dir() and not any(workspace.iterdir())
    ):
        raise FileExistsError(f"Workspace already exists: {workspace}")


def _check_rtl_targets(paths: list[tuple[Path, Path]]) -> None:
    """Reject occupied, symlinked, or file-blocked RTL destinations before building."""
    for _source, destination in paths:
        if destination.is_symlink():
            raise FileExistsError(f"RTL target is a symbolic link: {destination}")
        require_rtl_target_parents(destination)
        if destination.exists():
            raise FileExistsError(f"RTL target already exists: {destination}")


def _require_unregistered_name(manifest: ProjectManifest, name: str) -> None:
    if manifest.find_workspace(name) is not None:
        raise FileExistsError(f"Workspace already registered: {name}")


@dataclass(frozen=True)
class CreationDraft:
    project: Path
    original: str
    updated: str
    rtl: RtlImportPlan | None

    @contextmanager
    def build_target(self, workspace: Path, cfg: ProjectConfig, *, reuse_empty: bool):
        """Build privately in a sibling staging directory under the Workspace lock."""
        validate_draft_destination(self.project, workspace, reuse_empty=reuse_empty)
        staging = Path(tempfile.mkdtemp(prefix=f".{workspace.name}.draft-", dir=self.project))
        try:
            self._stage_rtl(staging)
            if self.rtl is not None:
                cfg = copy(cfg)
                cfg.design_rtl = [str(staging / path) for path in self.rtl.configured_paths]
            yield staging / "workspace", cfg
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def publish(
        self,
        cfg: ProjectConfig,
        flow_config,
        workspace: Path,
        *,
        built: Path,
        reuse_empty: bool,
        blocking: bool,
    ) -> None:
        """Publish the staged Workspace, RTL inputs, Project settings, and registration."""
        staging = built.parent
        config = self.project / CONFIG_FILENAME
        start, end = manifest_range_for_flow(cfg, flow_config)
        with manifest_lock(self.project, blocking=blocking):
            manifest = load_manifest(str(self.project))
            if config.read_text(encoding="utf-8") != self.original:
                raise ValueError(
                    "Project configuration changed during Workspace creation. "
                    "Retry with the current settings."
                )
            _require_unregistered_name(manifest, workspace.name)
            validate_draft_destination(self.project, workspace, reuse_empty=reuse_empty)
            if self.rtl is not None:
                _check_rtl_targets(self.rtl.copied)
            draft_config = parse_project_settings(self.project, self.updated)
            project_name, base_design = project_manifest_summary(draft_config, manifest)
            if self.rtl is not None:
                for _source, destination in self.rtl.copied:
                    staged = staging / destination.relative_to(self.project)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    staged.replace(destination)
            if self.updated != self.original:
                write_text_atomic(config, self.updated)
            built.rename(workspace)
            _register_workspace_locked(
                self.project,
                workspace,
                manifest,
                draft_config,
                start_step=start,
                end_step=end,
                skip_steps=(flow_config or {}).get("skip_steps"),
                project_name=project_name,
                base_design=base_design,
            )

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


def _register_workspace_locked(
    project: Path,
    workspace: Path,
    manifest: ProjectManifest,
    draft_config: ProjectConfig,
    *,
    start_step: str | None,
    end_step: str | None,
    skip_steps: list[str] | None,
    project_name: str,
    base_design: dict,
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
            "start_step": start_step,
            "end_step": end_step,
        },
    )

    def mutate(document: dict) -> None:
        register(document)
        document["design_name"] = project_name
        document["base_design"] = base_design
        if skip_steps is not None:
            entry = next(
                item for item in document["workspaces"] if item["workspace_id"] == workspace.name
            )
            entry["skip_steps"] = skip_steps

    if not update_manifest_locked(project, mutate):
        raise OSError("Project Manifest update failed")


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
        _require_unregistered_name(manifest, ctx.run_id)
        original = path.read_text(encoding="utf-8")
        updated = apply_settings_text(original, strings("settings"))
        parsed_text = updated
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
            _check_rtl_targets(rtl.copied)
            updated = set_scoped_key(updated, "design", "rtl", rtl.configured_paths)
        if updated != parsed_text:
            cfg = parse_project_config(updated, str(path))
        if rtl:
            cfg.design_rtl = rtl.source_paths
        draft = CreationDraft(project, original, updated, rtl)
        return replace(ctx, config=cfg, config_error=None), draft
    except FileExistsError as exc:
        return CommandResult.err(
            [
                error_record(
                    "run_exists", workspace_id=ctx.run_id, workspace=ctx.run_dir, reason=str(exc)
                )
            ]
        )
    except (ProjectApplicationError, RtlImportError, ManifestError, OSError, ValueError) as exc:
        return CommandResult.err(
            [error_record(getattr(exc, "code", "invalid_workspace_draft"), reason=str(exc))]
        )
