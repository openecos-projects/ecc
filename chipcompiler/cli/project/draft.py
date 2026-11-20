"""Validate one Workspace creation draft and publish its Project changes."""

import json
from contextlib import ExitStack
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


@dataclass(frozen=True)
class CreationDraft:
    project: Path
    project_id: str
    original: str
    updated: str
    rtl: RtlImportPlan | None

    def publish(self, cfg, flow_config, run_name: str, run_dir: str, *, blocking: bool) -> None:
        path = self.project / CONFIG_FILENAME
        with manifest_lock(self.project, blocking=blocking), ExitStack() as rollback:
            manifest = load_manifest(self.project)
            if manifest.project_id != self.project_id or path.read_text() != self.original:
                raise ValueError(
                    "Project configuration changed during Workspace creation. "
                    "Retry with the current settings."
                )
            if self.rtl:
                self.rtl.copy(rollback=rollback)
                cfg = replace(cfg, design_rtl=self.rtl.configured_paths)
            start, end = manifest_range_for_flow(cfg, flow_config)
            register = project_manifest_mutator(
                self.project,
                {
                    "type": "register_workspace",
                    "workspace_id": run_name,
                    "name": cfg.design_name,
                    "workspace_path": run_dir,
                    "start_step": start,
                    "end_step": end,
                },
            )
            base_design = base_design_from_config(cfg, resolve_pdk_root(cfg))

            def mutate(document: dict) -> None:
                if document.get("project_id") != self.project_id:
                    raise ManifestError("Project identity changed during Workspace creation")
                register(document)
                document["design_name"] = cfg.design_name
                document["base_design"] = base_design
                if flow_config and "skip_steps" in flow_config:
                    next(
                        entry
                        for entry in document["workspaces"]
                        if entry["workspace_id"] == run_name
                    )["skip_steps"] = flow_config["skip_steps"]

            if self.updated != self.original:
                write_text_atomic(path, self.updated)
                rollback.callback(write_text_atomic, path, self.original)
            if not update_manifest_locked(self.project, mutate):
                raise OSError("Project Manifest update failed")
            rollback.pop_all()


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

        manifest = load_manifest(project)
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
