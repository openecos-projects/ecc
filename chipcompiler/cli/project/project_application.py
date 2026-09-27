"""Atomic Project configuration and manifest-summary application."""

import json
import os
import shutil
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

from chipcompiler.cli.project.config import (
    load_project_config,
    resolve_pdk_root,
    validate_project_config,
)
from chipcompiler.cli.project.config_fields import lookup_project_field, parse_project_field_values
from chipcompiler.cli.project.param_edit import set_parameter, unset_parameter
from chipcompiler.cli.project.params import lookup_schema, parse_value, validate_value
from chipcompiler.cli.project.toml_edit import remove_scoped_key, set_scoped_key
from chipcompiler.project.manifest import load_manifest
from chipcompiler.project.manifest_write import (
    base_design_from_config,
    manifest_lock,
    update_manifest_locked,
)
from chipcompiler.utility.file import write_text_atomic


class ProjectApplicationError(RuntimeError):
    def __init__(self, code: str, message: str, *, key: str | None = None):
        super().__init__(message)
        self.code = code
        self.key = key


@dataclass(frozen=True)
class ProjectReconcileReport:
    repairs: tuple[str, ...] = ()
    busy: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


def apply_project(
    project_dir: str | Path,
    *,
    sets: tuple[str, ...],
    unsets: tuple[str, ...],
    add_rtl: tuple[str, ...],
    remove_rtl: tuple[str, ...],
    blocking: bool = True,
) -> tuple[str, ...]:
    project = Path(project_dir).expanduser().resolve()
    config_path = project / "ecc.toml"
    if not any((sets, unsets, add_rtl, remove_rtl)):
        raise ProjectApplicationError("project_patch_empty", "At least one change is required")
    parsed_sets = _parse_sets(sets)
    _validate_conflicts(parsed_sets, unsets, add_rtl, remove_rtl)
    with manifest_lock(project, blocking=blocking):
        try:
            original = config_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ProjectApplicationError("config_error", str(exc)) from exc
        load_manifest(str(project))
        updated, changed = _apply_text(
            original,
            parsed_sets=parsed_sets,
            unsets=unsets,
            add_rtl=add_rtl,
            remove_rtl=remove_rtl,
        )
        cfg = _validate_text(project, updated)
        if updated == original:
            return tuple(changed)
        try:
            write_text_atomic(config_path, updated)
            if not _update_summary_locked(project, cfg):
                raise OSError("Project Manifest update failed")
        except BaseException as exc:
            try:
                write_text_atomic(config_path, original)
            except OSError as rollback_error:
                raise ProjectApplicationError(
                    "project_rollback_failed",
                    f"{exc}; rollback failed: {rollback_error}",
                ) from rollback_error
            if isinstance(exc, ProjectApplicationError):
                raise
            raise ProjectApplicationError("project_apply_failed", str(exc)) from exc
    return tuple(changed)


def reconcile_project_summary(project_dir: str | Path, *, blocking: bool) -> bool:
    project = Path(project_dir).expanduser().resolve()
    config_path = project / "ecc.toml"
    with manifest_lock(project, blocking=blocking):
        load_manifest(str(project))
        cfg = load_project_config(str(config_path))
        errors = validate_project_config(cfg)
        if errors:
            raise ProjectApplicationError("invalid_project_config", errors[0])
        before = load_manifest(str(project)).base_design
        expected = base_design_from_config(cfg, resolve_pdk_root(cfg))
        if before == expected:
            return False
        if not _update_summary_locked(project, cfg):
            raise ProjectApplicationError("project_reconcile_failed", "Manifest update failed")
        return True


def reconcile_project_state(
    project_dir: str | Path, *, blocking: bool
) -> ProjectReconcileReport:
    """Repair provable Project and Workspace intermediate states."""
    project = Path(project_dir).expanduser().resolve()
    repairs: list[str] = []
    busy: list[str] = []
    errors: list[str] = []
    if reconcile_project_summary(project, blocking=blocking):
        repairs.append("base_design")

    manifest = load_manifest(str(project))
    for entry in manifest.workspaces:
        workspace = Path(entry.workspace_path).resolve()
        if not workspace.is_dir() or workspace.is_symlink():
            errors.append(f"{entry.workspace_id}: workspace directory is unavailable")
            continue
        try:
            _reconcile_workspace_state(
                project,
                entry.workspace_id,
                workspace,
                blocking=blocking,
                repairs=repairs,
            )
        except BlockingIOError:
            busy.append(entry.workspace_id)
        except Exception as exc:
            errors.append(f"{entry.workspace_id}: {exc}")

    registered_paths = {Path(entry.workspace_path).resolve() for entry in manifest.workspaces}
    for candidate in project.iterdir():
        if (
            candidate.name.startswith(".")
            or candidate in registered_paths
            or candidate.is_symlink()
            or not candidate.is_dir()
            or not (candidate / "home" / "engineering-snapshot.json").is_file()
        ):
            continue
        try:
            workspace_id = _reconcile_orphan_workspace(
                project, candidate, blocking=blocking
            )
            repairs.append(f"orphan_workspace:{workspace_id}")
        except BlockingIOError:
            busy.append(candidate.name)
        except Exception as exc:
            errors.append(f"{candidate.name}: {exc}")

    from chipcompiler.engine.workspace_management import reconcile_workspace_deletes

    try:
        repairs.extend(reconcile_workspace_deletes(project, blocking=blocking))
    except BlockingIOError:
        busy.append("delete_staging")
    except Exception as exc:
        errors.append(f"delete_staging: {exc}")
    return ProjectReconcileReport(tuple(repairs), tuple(busy), tuple(errors))


def _reconcile_orphan_workspace(
    project: Path, candidate: Path, *, blocking: bool
) -> str:
    from chipcompiler.engine.reconcile import _workspace_lock
    from chipcompiler.engine.snapshot import read_engineering_snapshot_from_directory
    from chipcompiler.engine.workspace_lifecycle import (
        WorkspaceLifecycleError,
        _workspace_command_fingerprint,
    )
    from chipcompiler.project.api import _project_manifest_mutator

    initial_stat = candidate.stat(follow_symlinks=False)
    with _workspace_lock(candidate, blocking=blocking):
        if candidate.is_symlink() or not candidate.is_dir():
            raise WorkspaceLifecycleError(
                "workspace_orphan_unsafe", "Workspace path changed during reconcile"
            )
        if not os.path.samestat(initial_stat, candidate.stat(follow_symlinks=False)):
            raise WorkspaceLifecycleError(
                "workspace_orphan_unsafe", "Workspace identity changed during reconcile"
            )
        manifest = load_manifest(str(project))
        snapshot = read_engineering_snapshot_from_directory(candidate)
        try:
            ledger = json.loads(
                (candidate / "home" / "workspace-commands.json").read_text(
                    encoding="utf-8"
                )
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WorkspaceLifecycleError(
                "workspace_orphan_unproven", "Workspace command ledger is unavailable"
            ) from exc
        commands = ledger.get("commands") if isinstance(ledger, dict) else None
        if (
            not isinstance(ledger, dict)
            or ledger.get("schemaVersion") != 1
            or not isinstance(commands, dict)
        ):
            raise WorkspaceLifecycleError(
                "workspace_orphan_unproven", "Workspace command ledger is invalid"
            )
        matches = []
        for command_id, record in commands.items():
            metadata = record.get("metadata") if isinstance(record, dict) else None
            if not isinstance(command_id, str) or not isinstance(metadata, dict):
                continue
            operation = metadata.get("operation")
            workspace_id = metadata.get("workspaceId")
            request = metadata.get("request")
            if (
                operation not in {"create", "derive"}
                or metadata.get("projectId") != manifest.project_id
                or workspace_id != candidate.name
                or not isinstance(request, dict)
                or Path(str(metadata.get("workspacePath", ""))).resolve() != candidate
            ):
                continue
            expected_revision = metadata.get("expectedRevision")
            if expected_revision is not None and (
                not isinstance(expected_revision, int) or isinstance(expected_revision, bool)
            ):
                continue
            expected = _workspace_command_fingerprint(
                operation,
                request,
                None,
                expected_revision if operation == "create" else None,
            )
            if (
                record.get("fingerprint") != expected
                or record.get("result")
                != {
                    "workspaceId": snapshot["workspaceId"],
                    "workspaceRevision": snapshot["workspaceRevision"],
                }
            ):
                continue
            matches.append((workspace_id, operation, metadata, request))
        if len(matches) != 1:
            raise WorkspaceLifecycleError(
                "workspace_orphan_unproven",
                "Workspace has no unique matching create/derive command",
            )
        workspace_id, operation, metadata, request = matches[0]
        mutation = {
            "type": "register_workspace",
            "workspace_id": workspace_id,
            "workspace_path": str(candidate),
        }
        if operation == "derive":
            source_id = metadata.get("sourceWorkspaceId")
            source = manifest.find_workspace(source_id) if isinstance(source_id, str) else None
            if (
                source is None
                or Path(source.workspace_path).resolve()
                != Path(str(request.get("directory", ""))).resolve()
                or Path(str(request.get("targetDirectory", ""))).resolve() != candidate
            ):
                raise WorkspaceLifecycleError(
                    "workspace_orphan_unproven", "Derived Workspace source does not match"
                )
            source_step = request.get("resetFromStep")
            mutation.update(
                {
                    "source_workspace_id": source_id,
                    "branch_from": {
                        "source_workspace_id": source_id,
                        **(
                            {"source_step": source_step}
                            if isinstance(source_step, str) and source_step
                            else {}
                        ),
                    },
                }
            )
        with manifest_lock(project, blocking=blocking):
            current = load_manifest(str(project))
            if current.project_id != manifest.project_id:
                raise WorkspaceLifecycleError(
                    "workspace_identity_changed", "Project identity changed during reconcile"
                )
            if not update_manifest_locked(
                project, _project_manifest_mutator(project, mutation)
            ):
                raise WorkspaceLifecycleError(
                    "project_manifest_update_failed", "Project Manifest update failed"
                )
        return workspace_id


def _reconcile_workspace_state(
    project: Path,
    workspace_id: str,
    workspace: Path,
    *,
    blocking: bool,
    repairs: list[str],
) -> None:
    from chipcompiler.data import load_workspace, recover_workspace_file_transaction
    from chipcompiler.data.schema_migrations import (
        ENGINEERING_SNAPSHOT,
        read_file_schema_version,
    )
    from chipcompiler.engine.interrupted_run import recover_interrupted_run
    from chipcompiler.engine.reconcile import _workspace_lock
    from chipcompiler.engine.snapshot import (
        LEGACY_SNAPSHOT_SCHEMA_VERSION,
        SNAPSHOT_V3_SCHEMA_VERSION,
        migrate_engineering_snapshot,
    )
    from chipcompiler.project.runtime_processes import (
        RuntimeProcessError,
        identity_is_live,
        validate_runtime_entry,
    )

    with _workspace_lock(workspace, blocking=blocking):
        current = load_manifest(str(project))
        current_entry = current.find_workspace(workspace_id)
        if current_entry is None or Path(current_entry.workspace_path).resolve() != workspace:
            raise ProjectApplicationError(
                "workspace_identity_changed", "Workspace registration changed during reconcile"
            )
        if _reconcile_workspace_refresh_exchange(workspace):
            repairs.append(f"refresh_exchange:{workspace_id}")
        recover_workspace_file_transaction(workspace)
        version = read_file_schema_version(ENGINEERING_SNAPSHOT, workspace)
        if version in {LEGACY_SNAPSHOT_SCHEMA_VERSION, SNAPSHOT_V3_SCHEMA_VERSION}:
            loaded = load_workspace(workspace)
            if loaded is None:
                raise ProjectApplicationError(
                    "workspace_invalid", "Workspace cannot be loaded for Snapshot migration"
                )
            migrate_engineering_snapshot(loaded)
            repairs.append(f"snapshot:{workspace_id}")

        raw_processes = current.raw.get("runtime_processes", {})
        raw_entry = raw_processes.get(workspace_id) if isinstance(raw_processes, dict) else None
        if raw_entry is None:
            recovered = recover_interrupted_run(
                workspace, run_id=None, allow_markerless=True
            )
            if recovered:
                repairs.append(f"orphan_flow:{workspace_id}")
            return
        try:
            process = validate_runtime_entry(raw_entry)
        except RuntimeProcessError:
            process = None
        if process is not None and identity_is_live(process):
            raise ProjectApplicationError(
                "runtime_process_inconsistent",
                "Live runtime process does not hold the Workspace lock",
            )
        recovered = recover_interrupted_run(
            workspace,
            run_id=process["run_id"] if process is not None else None,
            allow_markerless=process is None,
        )
        _remove_runtime_entry(project, workspace_id, raw_entry, blocking=blocking)
        repairs.append(f"runtime:{workspace_id}")
        if recovered:
            repairs.append(f"interrupted_flow:{workspace_id}")


def _reconcile_workspace_refresh_exchange(workspace: Path) -> bool:
    """Recover one provable Workspace refresh exchange while its lock is held."""
    from chipcompiler.engine.snapshot import read_engineering_snapshot_from_directory
    from chipcompiler.engine.workspace_lifecycle import (
        WorkspaceLifecycleError,
        _exchange_directories,
    )

    prefix = f".{workspace.name}.staging-"
    candidates = [
        candidate
        for candidate in workspace.parent.iterdir()
        if candidate.name.startswith(prefix)
        and (candidate.is_dir() or candidate.is_symlink())
    ]
    if not candidates:
        return False
    if len(candidates) != 1:
        raise WorkspaceLifecycleError(
            "workspace_refresh_recovery_ambiguous",
            "Multiple refresh staging directories match the Workspace",
        )
    staging = candidates[0]
    if staging.is_symlink() or not staging.is_dir() or workspace.is_symlink():
        raise WorkspaceLifecycleError(
            "workspace_refresh_recovery_unsafe",
            "Refresh staging must be a direct, non-symlink sibling directory",
        )
    target_snapshot = read_engineering_snapshot_from_directory(workspace)
    staging_snapshot = read_engineering_snapshot_from_directory(staging)
    if target_snapshot["workspaceId"] != staging_snapshot["workspaceId"]:
        raise WorkspaceLifecycleError(
            "workspace_refresh_recovery_unproven",
            "Refresh staging Workspace identity does not match",
        )
    target_revision = target_snapshot["workspaceRevision"]
    staging_revision = staging_snapshot["workspaceRevision"]
    if staging_revision == target_revision + 1:
        _require_refresh_command_proof(staging, staging_snapshot, target_revision)
        _exchange_directories(workspace, staging)
        shutil.rmtree(staging)
        return True
    if target_revision == staging_revision + 1:
        _require_refresh_command_proof(workspace, target_snapshot, staging_revision)
        shutil.rmtree(staging)
        return True
    raise WorkspaceLifecycleError(
        "workspace_refresh_recovery_unproven",
        "Refresh staging revisions do not form one committed update",
    )


def _require_refresh_command_proof(
    updated_workspace: Path, snapshot: dict, source_revision: int
) -> None:
    from chipcompiler.engine.workspace_lifecycle import (
        WorkspaceLifecycleError,
        _workspace_command_fingerprint,
    )

    try:
        ledger = json.loads(
            (updated_workspace / "home" / "workspace-commands.json").read_text(
                encoding="utf-8"
            )
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkspaceLifecycleError(
            "workspace_refresh_recovery_unproven",
            "Refresh staging command ledger is unavailable",
        ) from exc
    commands = ledger.get("commands") if isinstance(ledger, dict) else None
    if (
        not isinstance(ledger, dict)
        or ledger.get("schemaVersion") != 1
        or not isinstance(commands, dict)
    ):
        raise WorkspaceLifecycleError(
            "workspace_refresh_recovery_unproven",
            "Refresh staging command ledger is invalid",
        )
    expected_result = {
        "workspaceId": snapshot["workspaceId"],
        "workspaceRevision": snapshot["workspaceRevision"],
    }
    matches = []
    for record in commands.values():
        if not isinstance(record, dict) or record.get("result") != expected_result:
            continue
        metadata = record.get("metadata")
        request = metadata.get("request") if isinstance(metadata, dict) else None
        if (
            not isinstance(metadata, dict)
            or metadata.get("operation") != "update"
            or metadata.get("expectedRevision") != source_revision
            or not isinstance(request, dict)
            or set(request) != {"workspaceSpec", "workspaceBindings"}
        ):
            continue
        expected = _workspace_command_fingerprint(
            "update",
            request["workspaceSpec"],
            request["workspaceBindings"],
            source_revision,
        )
        if record.get("fingerprint") == expected:
            matches.append(record)
    if len(matches) != 1:
        raise WorkspaceLifecycleError(
            "workspace_refresh_recovery_unproven",
            "Refresh staging has no unique matching update command",
        )


def _remove_runtime_entry(
    project: Path, workspace_id: str, expected: object, *, blocking: bool
) -> None:
    with manifest_lock(project, blocking=blocking):
        manifest = load_manifest(str(project))
        processes = manifest.raw.get("runtime_processes", {})
        current = processes.get(workspace_id) if isinstance(processes, dict) else None
        if current != expected:
            raise ProjectApplicationError(
                "runtime_process_changed", "Runtime process changed during reconcile"
            )

        def mutate(document: dict) -> None:
            values = document.get("runtime_processes", {})
            current_value = values.get(workspace_id) if isinstance(values, dict) else None
            if current_value != expected:
                raise ProjectApplicationError(
                    "runtime_process_changed", "Runtime process changed during reconcile"
                )
            del values[workspace_id]

        if not update_manifest_locked(project, mutate):
            raise ProjectApplicationError(
                "project_reconcile_failed", "Failed to remove stale runtime process"
            )


def select_qor_baseline(project_dir: str | Path, workspace_id: str, reason: str) -> None:
    from chipcompiler.project.api import _project_manifest_mutator

    project = Path(project_dir).expanduser().resolve()
    mutation = {
        "type": "select_qor_baseline",
        "workspace_id": workspace_id,
        "reason": reason,
    }
    with manifest_lock(project):
        if not update_manifest_locked(project, _project_manifest_mutator(project, mutation)):
            raise ProjectApplicationError(
                "project_manifest_update_failed", "Manifest update failed"
            )


def _parse_sets(values: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    parsed = []
    seen = set()
    for value in values:
        key, separator, raw = value.partition("=")
        key = key.strip()
        if not separator or not key:
            raise ProjectApplicationError("invalid_project_patch", f"Invalid --set: {value}")
        if key in seen:
            raise ProjectApplicationError("duplicate_project_key", f"Duplicate key: {key}", key=key)
        seen.add(key)
        parsed.append((key, raw))
    return tuple(parsed)


def _validate_conflicts(
    sets: tuple[tuple[str, str], ...],
    unsets: tuple[str, ...],
    add_rtl: tuple[str, ...],
    remove_rtl: tuple[str, ...],
) -> None:
    set_keys = {key for key, _value in sets}
    unset_keys = set(unsets)
    duplicate_unsets = len(unset_keys) != len(unsets)
    conflict = set_keys & unset_keys
    if duplicate_unsets or conflict:
        key = min(conflict) if conflict else ""
        raise ProjectApplicationError("conflicting_project_patch", "Set/unset conflict", key=key)
    if "design.rtl" in set_keys | unset_keys and (add_rtl or remove_rtl):
        raise ProjectApplicationError(
            "conflicting_project_patch", "design.rtl set/unset conflicts with add/remove"
        )
    overlap = set(add_rtl) & set(remove_rtl)
    if overlap:
        raise ProjectApplicationError(
            "conflicting_project_patch", f"RTL appears in add and remove: {min(overlap)}"
        )


def _apply_text(
    text: str,
    *,
    parsed_sets: tuple[tuple[str, str], ...],
    unsets: tuple[str, ...],
    add_rtl: tuple[str, ...],
    remove_rtl: tuple[str, ...],
) -> tuple[str, list[str]]:
    changed: list[str] = []
    updated = text
    for key, raw in parsed_sets:
        field = lookup_project_field(key)
        schema = lookup_schema(key)
        if field is not None:
            value = _parse_field_value(field, raw)
            updated = set_scoped_key(updated, field.table, field.name, value)
        elif schema is not None:
            try:
                value = parse_value(raw, schema)
            except ValueError as exc:
                raise ProjectApplicationError("invalid_value", str(exc), key=key) from exc
            errors = validate_value(value, schema)
            if errors:
                raise ProjectApplicationError("invalid_value", errors[0], key=key)
            updated = set_parameter(updated, schema, value)
        else:
            raise ProjectApplicationError("unknown_project_field", f"Unknown key: {key}", key=key)
        changed.append(key)
    for key in unsets:
        field = lookup_project_field(key)
        schema = lookup_schema(key)
        if field is not None:
            result = remove_scoped_key(updated, field.table, field.name)
        elif schema is not None:
            result = unset_parameter(updated, schema)
        else:
            raise ProjectApplicationError("unknown_project_field", f"Unknown key: {key}", key=key)
        if result is not None:
            updated = result
        changed.append(key)
    if add_rtl or remove_rtl:
        try:
            data = tomllib.loads(updated)
        except tomllib.TOMLDecodeError as exc:
            raise ProjectApplicationError("invalid_project_config", str(exc)) from exc
        current = data.get("design", {}).get("rtl", [])
        if not isinstance(current, list) or not all(isinstance(value, str) for value in current):
            raise ProjectApplicationError(
                "invalid_project_config", "design.rtl must be a string list"
            )
        result = [*current, *(value for value in add_rtl if value not in current)]
        result = [value for value in result if value not in remove_rtl]
        updated = set_scoped_key(updated, "design", "rtl", result)
        changed.append("design.rtl")
    return updated, changed


def _parse_field_value(field, raw: str) -> object:
    if field.list_value:
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProjectApplicationError("invalid_project_value", str(exc), key=field.key) from exc
        if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
            raise ProjectApplicationError(
                "invalid_project_value", f"{field.key} requires a JSON string array", key=field.key
            )
        return value
    try:
        return parse_project_field_values(field, (raw,))
    except ValueError as exc:
        raise ProjectApplicationError("invalid_project_value", str(exc), key=field.key) from exc


def _validate_text(project: Path, text: str):
    descriptor, name = tempfile.mkstemp(prefix=".ecc.toml.validate-", dir=project)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        cfg = load_project_config(name)
        # The temporary file is in the Project root, so relative paths resolve identically.
        errors = validate_project_config(cfg)
        if errors:
            raise ProjectApplicationError("invalid_project_config", errors[0])
        cfg.config_path = str(project / "ecc.toml")
        cfg.project_dir = str(project)
        return cfg
    finally:
        Path(name).unlink(missing_ok=True)


def _update_summary_locked(project: Path, cfg) -> bool:
    base_design = base_design_from_config(cfg, resolve_pdk_root(cfg))

    def mutate(document: dict) -> None:
        document["design_name"] = cfg.design_name
        document["base_design"] = base_design

    return update_manifest_locked(project, mutate)
