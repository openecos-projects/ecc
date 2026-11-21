"""Project workspace registration checks and explicit repair.

The CLI owns execution state in workspace files and no longer synchronizes
cached range, status, or parameter fields in project.json. Doctor checks
directory existence, workspace readability, and unregistered directories.
Repair removes missing-directory entries and registers existing workspaces;
unreadable workspace files must be restored without deleting their registration.

A project directory that was renamed, moved or copied is found before the
manifest is loaded (the loader rejects it): its root_path still names the
former location. Repair re-anchors the project-local workspaces (their tool
configuration, then their manifest paths) and root_path to the directory the
manifest is in.

Keep module-level imports cheap: this module sits on the CLI startup path.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path

from chipcompiler.project.manifest import MANIFEST_FILENAME, ManifestError, ProjectManifest
from chipcompiler.project.manifest_write import now_iso, update_manifest

INVALID_WORKSPACE = "invalid-workspace"
MISSING_DIRECTORY = "missing-directory"
MOVED_PROJECT = "moved-project"
UNREGISTERED_DIRECTORY = "unregistered-directory"


@dataclass(frozen=True)
class ConsistencyFinding:
    check: str
    workspace_id: str
    workspace_path: str
    detail: str


@dataclass(frozen=True)
class FixAction:
    finding: ConsistencyFinding
    action: str  # removed | registered | existing | unchanged | failed
    detail: str = ""


@dataclass(frozen=True)
class Relocation:
    recorded_root: str
    project_dir: str
    # (workspace_id, path below project_dir) of every project-local workspace.
    workspaces: tuple[tuple[str, str], ...] = ()
    # (name, path) of the workspace directories below project_dir that have no
    # manifest entry: the repair that follows registers them where they are.
    unregistered: tuple[tuple[str, str], ...] = ()


def find_relocation(project_dir: str) -> Relocation | None:
    """The root the manifest records, when it is not the directory it is in.

    Returns None for a manifest that cannot be read or records no root_path:
    those are not relocations and remain load_manifest's to report.
    """
    try:
        with open(os.path.join(project_dir, MANIFEST_FILENAME), encoding="utf-8") as f:
            document = json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    recorded = document.get("root_path") if isinstance(document, dict) else None
    if not isinstance(recorded, str) or not recorded:
        return None
    if os.path.realpath(recorded) == os.path.realpath(project_dir):
        return None
    local = tuple(_local_workspaces(document, recorded, project_dir))
    known = {path for _workspace_id, path in local}
    unregistered = tuple(
        (name, path)
        for name, path in _workspace_directories(project_dir)
        if os.path.realpath(path) not in known
    )
    return Relocation(recorded, project_dir, local, unregistered)


def relocate_project(relocation: Relocation) -> str | None:
    """Re-anchor a moved or copied project; the failure detail, or None.

    A workspace registered inside the recorded root moved (or was copied)
    with the project: the absolute paths its tool configuration keeps under
    the recorded root are rewritten first, then root_path and the workspace
    paths in the manifest. The manifest goes last so that a failed run can be
    repeated. A workspace registered elsewhere is external and is left alone.
    """
    from contextlib import ExitStack

    from chipcompiler.data.workspace.transaction import recover_workspace_file_transaction
    from chipcompiler.utility.file import write_text_atomic
    from chipcompiler.utility.workspace_lock import workspace_lock

    project_dir = relocation.project_dir
    # reported as missing-directory once the manifest loads
    # An unregistered workspace directory moved with the project as well; it
    # is rewritten now, because nothing reports the former root once the
    # manifest records the new one.
    candidates = (*relocation.workspaces, *relocation.unregistered)
    present = sorted({(os.path.realpath(path), workspace_id) for workspace_id, path in candidates})
    present = [(path, workspace_id) for path, workspace_id in present if os.path.isdir(path)]
    # The workspace locks are taken first, in a fixed order, and held until
    # the last file is written: what is read here cannot be changed by another
    # command before it is written back. Every configuration file is read
    # before the first one is written, so a file that cannot be parsed stops
    # the repair with nothing changed.
    with ExitStack() as locks:
        for path, workspace_id in present:
            try:
                locks.enter_context(workspace_lock(Path(path), blocking=False))
            except BlockingIOError:
                return f"workspace {workspace_id} is busy"
        planned = []
        for path, workspace_id in present:
            try:
                # A configuration update interrupted before the move left its
                # backup behind; the next load would restore it over what is
                # rewritten here. It is settled first, as a load would.
                recover_workspace_file_transaction(path)
                rewrites = _planned_config_rewrites(path, relocation.recorded_root, project_dir)
                parameters = _planned_parameter_rewrite(path, relocation.recorded_root, project_dir)
            except (OSError, ValueError) as exc:
                return f"workspace {workspace_id}: {exc}"
            planned.append((workspace_id, path, rewrites, parameters))
        try:
            project_config = _planned_project_config(relocation.recorded_root, project_dir)
        except (OSError, ValueError) as exc:
            return f"ecc.toml: {exc}"
        for workspace_id, path, rewrites, parameters in planned:
            try:
                _write_workspace_rewrites(path, rewrites, parameters)
            except OSError as exc:
                return f"workspace {workspace_id}: {exc}"
        if project_config is not None:
            try:
                write_text_atomic(*project_config)
            except OSError as exc:
                return f"ecc.toml: {exc}"

    new_root = os.path.abspath(project_dir)

    def mutate(document: dict) -> None:
        recorded = document.get("root_path")
        if not isinstance(recorded, str) or not recorded:
            return
        if os.path.realpath(recorded) == os.path.realpath(new_root):
            return
        local = dict(_local_workspaces(document, recorded, project_dir))
        for entry in document.get("workspaces", []):
            if not isinstance(entry, dict) or entry.get("workspace_id") not in local:
                continue
            if os.path.isabs(str(entry.get("workspace_path"))):
                entry["workspace_path"] = local[entry["workspace_id"]]
        # A run registered for a workspace of the former location is not a run
        # of this project: after a copy it is the original's process, which a
        # cancel through the copy would signal. A run of this directory would
        # hold the workspace lock, and the repair does not get that far then.
        processes = document.get("runtime_processes")
        if isinstance(processes, dict):
            for workspace_id in local:
                processes.pop(workspace_id, None)
        # Paths base_design keeps below the recorded root (a PDK inside the
        # project, an entry input) moved too; paths elsewhere are left alone.
        if isinstance(document.get("base_design"), dict):
            document["base_design"] = _rebase_values(
                document["base_design"], recorded, os.path.realpath(new_root)
            )
        document["root_path"] = new_root
        document["updated_at"] = now_iso()

    if not update_manifest(project_dir, mutate):
        return "manifest update failed"
    return None


def _local_workspaces(document: dict, recorded_root: str, project_dir: str):
    """(workspace_id, path below project_dir) for entries registered below recorded_root.

    A relative registration is resolved below the project directory, as the
    manifest loader does; it moved with the project like an absolute one.
    """
    new_root = os.path.realpath(project_dir)
    for entry in document.get("workspaces") or []:
        if not isinstance(entry, dict):
            continue
        workspace_id, path = entry.get("workspace_id"), entry.get("workspace_path")
        if not isinstance(workspace_id, str) or not isinstance(path, str) or not path:
            continue
        if os.path.isabs(path):
            rebased = _rebased_path(path, recorded_root, new_root)
        else:
            rebased = os.path.realpath(os.path.join(new_root, path))
            if not _is_below(rebased, new_root):
                continue  # escapes the project: the loader reports it
        if rebased is not None and rebased != new_root:
            yield workspace_id, rebased


def _root_spellings(root: str) -> tuple[str, ...]:
    """root_path is stored as typed while workspace paths are stored resolved."""
    return tuple(dict.fromkeys((os.path.normpath(root), os.path.realpath(root))))


def _rebased_path(value: str, recorded_root: str, new_root: str) -> str | None:
    """``value`` moved from below ``recorded_root`` to ``new_root``; None when outside."""
    if not os.path.isabs(value):
        return None
    normalized = os.path.normpath(value)
    for root in _root_spellings(recorded_root):
        if _is_below(new_root, root) and _is_below(normalized, new_root):
            # The project now lies below the root it records (a copy made
            # inside the original). A path below the new root is already in
            # place - written by an earlier, interrupted repair - although it
            # still starts with the recorded root.
            return None
        if normalized == root:
            return new_root
        if normalized.startswith(root + os.sep):
            return new_root + normalized[len(root) :]
    return None


def _is_below(path: str, root: str) -> bool:
    return path == root or path.startswith(root + os.sep)


def _planned_config_rewrites(
    workspace_dir: str, recorded_root: str, project_dir: str
) -> list[tuple[Path, object]]:
    """The ``config/*.json`` files whose absolute paths lie below ``recorded_root``.

    The tool configuration keeps a few absolute paths into the workspace
    (the default timing constraints, the EMIR technology file). Left alone
    they name files of the former location: gone after a move, the original
    project's after a copy.

    Only a file that resolves to a place inside the relocated project is
    planned. A ``config`` directory or a file that is a symbolic link out of
    it belongs to someone else - after a link-preserving copy, to the
    original project - and is left as it is.
    """
    new_root = os.path.realpath(project_dir)
    rewrites: list[tuple[Path, object]] = []
    for path in sorted(Path(workspace_dir, "config").glob("*.json")):
        if path.is_symlink() or not path.is_file():
            continue
        if not _is_below(os.path.realpath(path), new_root):
            continue
        document = json.loads(path.read_text(encoding="utf-8"))
        rebased = _rebase_values(document, recorded_root, new_root)
        if rebased != document:
            rewrites.append((path, rebased))
    return rewrites


def _write_workspace_rewrites(workspace_dir: str, rewrites, parameters) -> None:
    """Write one workspace's rebased files as one workspace file transaction.

    The configs, the parameters and the derivation record change together:
    if one write fails, the files already written are restored, so a retry
    plans the same rewrite again instead of skipping files whose record was
    never updated.
    """
    from chipcompiler.data.workspace.config_manifest import derived_config_manifest_path
    from chipcompiler.data.workspace.transaction import WorkspaceFileTransaction

    if not rewrites and parameters is None:
        return
    root = Path(workspace_dir).resolve()
    managed = [path for path, _document in rewrites]
    if parameters is not None:
        managed.append(Path(parameters.path))
    managed.append(derived_config_manifest_path(workspace_dir))
    # The transaction manages files under the workspace's own config/ and
    # home/. A config directory linked elsewhere (inside the project, maybe
    # inside the workspace) resolves outside them; those files are written
    # without it, so the transaction is never handed a path it refuses.
    managed = [path for path in managed if _transaction_managed(path, root)]
    transaction = WorkspaceFileTransaction.begin(root, managed)
    try:
        _write_config_rewrites(workspace_dir, rewrites)
        _write_parameter_rewrite(parameters)
        transaction.commit()
    except BaseException:
        transaction.rollback()
        raise


def _transaction_managed(path: Path, workspace: Path) -> bool:
    try:
        relative = path.resolve().relative_to(workspace)
    except ValueError:
        return False
    return bool(relative.parts) and relative.parts[0] in ("config", "home")


def _write_config_rewrites(workspace_dir: str, rewrites: list[tuple[Path, object]]) -> None:
    """Write the rebased configs; a generated file stays a generated file.

    A file that matched its last derivation before the rewrite is recorded
    again with its new content, so ``workspace refresh`` does not take the
    relocation for a hand edit. A file that had been edited stays reported.
    """
    from chipcompiler.data.workspace.config_manifest import (
        modified_derived_configs,
        rerecord_derived_configs,
    )
    from chipcompiler.utility import json_write

    edited = set(modified_derived_configs(workspace_dir))
    for path, document in rewrites:
        if not json_write(path, document):
            raise OSError(f"cannot rewrite {path}")
    untouched = [path.name for path, _document in rewrites if path.name not in edited]
    if not rerecord_derived_configs(workspace_dir, untouched):
        raise OSError(f"cannot update the derivation record of {workspace_dir}")


# ecc.toml keys that name files or directories.
_PROJECT_PATH_KEYS = (
    ("design", "rtl"),
    ("design", "netlist"),
    ("design", "golden_netlist"),
    ("design", "def"),
    ("design", "sdc"),
    ("design", "spef"),
    ("pdk", "root"),
)


def _planned_project_config(recorded_root: str, project_dir: str) -> tuple[Path, str] | None:
    """``ecc.toml`` with its absolute paths below ``recorded_root`` rebased.

    An explicit ecc.toml value outranks the manifest, so a path written there
    as an absolute path into the former location would shadow the repaired
    manifest. Only those values change: relative paths, paths elsewhere and
    the rest of the file (comments, layout) stay as written.
    """
    import tomllib

    from chipcompiler.cli.project.toml_edit import set_scoped_key
    from chipcompiler.project.manifest import CONFIG_FILENAME

    path = Path(project_dir) / CONFIG_FILENAME
    if path.is_symlink() or not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    document = tomllib.loads(text)
    new_root = os.path.realpath(project_dir)
    updated = text
    expected = {
        table: dict(section) for table, section in document.items() if isinstance(section, dict)
    }
    for table, key in _PROJECT_PATH_KEYS:
        section = document.get(table)
        if not isinstance(section, dict) or key not in section:
            continue
        value = section[key]
        rebased = _rebase_values(value, recorded_root, new_root)
        if rebased != value:
            updated = set_scoped_key(updated, table, key, rebased)
            expected[table][key] = rebased
    if updated == text:
        return None
    # The editor only knows [table] sections. Whatever it wrote has to read
    # back as the same document with just these values changed; otherwise
    # (an inline table, say) the repair stops before writing anything.
    try:
        written = tomllib.loads(updated)
    except tomllib.TOMLDecodeError:
        written = None
    unchanged = {key: value for key, value in document.items() if not isinstance(value, dict)}
    if written != {**unchanged, **expected}:
        keys = ", ".join(
            f"[{table}] {key}"
            for table, key in _PROJECT_PATH_KEYS
            if table in expected
            and expected[table].get(key) != (document.get(table) or {}).get(key)
        )
        raise ValueError(
            f"cannot rewrite {keys} in place; replace the path into {recorded_root} "
            f"by one into {new_root} and run the repair again"
        )
    return path, updated


def _planned_parameter_rewrite(workspace_dir: str, recorded_root: str, project_dir: str):
    """The workspace parameters (``home/params.toml``) with their paths rebased.

    They keep paths of their own - the PDK root above all, which the
    workspace loader validates - next to the copies in the manifest. None
    when nothing below the recorded root is recorded there.
    """
    from chipcompiler.data.parameter import Parameters, load_parameter

    path = Path(workspace_dir) / "home" / "params.toml"
    if path.is_symlink() or not path.is_file():
        return None
    new_root = os.path.realpath(project_dir)
    if not _is_below(os.path.realpath(path), new_root):
        return None
    parameters = load_parameter(path)
    rebased = _rebase_values(parameters.data, recorded_root, new_root)
    if not isinstance(rebased, dict) or rebased == parameters.data:
        return None
    return Parameters(path=path, data=rebased)


def _write_parameter_rewrite(parameters) -> None:
    from chipcompiler.data.parameter import save_parameter

    if parameters is not None and not save_parameter(parameters):
        raise OSError(f"cannot rewrite {parameters.path}")


def _rebase_values(value, recorded_root: str, new_root: str):
    if isinstance(value, dict):
        return {key: _rebase_values(item, recorded_root, new_root) for key, item in value.items()}
    if isinstance(value, list):
        return [_rebase_values(item, recorded_root, new_root) for item in value]
    if isinstance(value, str):
        return _rebased_path(value, recorded_root, new_root) or value
    return value


def find_inconsistencies(manifest: ProjectManifest) -> list[ConsistencyFinding]:
    """All manifest ↔ directory inconsistencies, in a stable order.

    Entry checks follow manifest order; unregistered directories follow
    sorted directory names.
    """
    findings = []
    for entry in manifest.workspaces:
        finding = _check_entry(manifest, entry)
        if finding is not None:
            findings.append(finding)
    findings.extend(_scan_unregistered(manifest))
    return findings


def repair_findings(
    manifest: ProjectManifest, findings: list[ConsistencyFinding]
) -> list[FixAction]:
    """Repair every finding explicitly, one audited action per finding."""
    actions = []
    for finding in findings:
        if finding.check == UNREGISTERED_DIRECTORY:
            actions.append(_register_directory(manifest, finding))
        elif finding.check == MISSING_DIRECTORY:
            actions.append(_remove_dead_entry(manifest, finding))
        else:
            actions.append(
                FixAction(finding, "failed", "restore the workspace files before retrying")
            )
    return actions


def _check_entry(manifest: ProjectManifest, entry) -> ConsistencyFinding | None:
    from chipcompiler.cli.project.workspace_registration import (
        WorkspaceRegistrationError,
        inspect_existing_workspace,
    )
    from chipcompiler.project.runtime_processes import identity_is_live

    path = entry.workspace_path
    if not os.path.isdir(path):
        return ConsistencyFinding(
            MISSING_DIRECTORY,
            entry.workspace_id,
            path,
            "workspace directory does not exist",
        )
    if entry.status == "archived":
        return None
    runtime_entry = (manifest.raw.get("runtime_processes") or {}).get(entry.workspace_id)
    if isinstance(runtime_entry, dict):
        try:
            if identity_is_live(runtime_entry):
                # Live processes can be replacing workspace files during inspection.
                return None
        except Exception:
            # Invalid or stale registrations must be inspected like any other workspace.
            pass
    try:
        inspect_existing_workspace(
            path,
            expected_design=manifest.design_name,
            expected_pdk=str(manifest.base_design.get("pdk") or ""),
        )
    except (WorkspaceRegistrationError, ManifestError) as exc:
        return ConsistencyFinding(
            INVALID_WORKSPACE,
            entry.workspace_id,
            path,
            f"workspace facts unreadable: {exc}",
        )
    return None


def _workspace_directories(project_dir: str) -> list[tuple[str, str]]:
    """(name, path) of the direct children of ``project_dir`` that are workspaces."""
    from chipcompiler.cli.project.workspace_registration import is_ecc_workspace_directory

    directories = []
    for name in sorted(os.listdir(project_dir)):
        if name == "runs":
            # The legacy runs/ container holds run directories, never one workspace.
            continue
        path = os.path.join(project_dir, name)
        if is_ecc_workspace_directory(path):
            directories.append((name, path))
    return directories


def _scan_unregistered(manifest: ProjectManifest) -> list[ConsistencyFinding]:
    registered = {os.path.realpath(w.workspace_path) for w in manifest.workspaces}
    return [
        ConsistencyFinding(
            UNREGISTERED_DIRECTORY,
            name,
            path,
            "workspace directory has no manifest entry",
        )
        for name, path in _workspace_directories(manifest.project_dir)
        if os.path.realpath(path) not in registered
    ]


def _remove_dead_entry(manifest: ProjectManifest, finding: ConsistencyFinding) -> FixAction:
    workspace_id = finding.workspace_id
    removed = False

    def mutate(document: dict) -> None:
        nonlocal removed
        entries = [e for e in document.get("workspaces", []) if isinstance(e, dict)]
        if not any(e.get("workspace_id") == workspace_id for e in entries):
            return
        removed = True
        # Mirrors the delete-workspace mutation: drop the entry and null
        # every reference (lineage, baseline, best) that pointed at it.
        document["workspaces"] = [e for e in entries if e.get("workspace_id") != workspace_id]
        for entry in document["workspaces"]:
            if entry.get("source_workspace_id") == workspace_id:
                entry["source_workspace_id"] = None
        for field in ("qor_baseline", "best_workspace"):
            selection = document.get(field)
            if isinstance(selection, dict) and selection.get("workspace_id") == workspace_id:
                document[field] = None
        document["updated_at"] = now_iso()

    if not update_manifest(manifest.project_dir, mutate):
        return FixAction(finding, "failed", "manifest update failed")
    return FixAction(finding, "removed" if removed else "unchanged")


def _register_directory(manifest: ProjectManifest, finding: ConsistencyFinding) -> FixAction:
    from chipcompiler.cli.project.workspace_registration import (
        WorkspaceRegistrationError,
        import_managed_workspace,
    )

    base_design = manifest.base_design
    try:
        outcome, _metadata = import_managed_workspace(
            manifest.project_dir,
            design_name=manifest.design_name,
            workspace_id=finding.workspace_id,
            workspace_path=finding.workspace_path,
            expected_pdk=str(base_design.get("pdk") or ""),
        )
    except WorkspaceRegistrationError as exc:
        return FixAction(finding, "failed", str(exc))
    if outcome in ("registered", "existing"):
        return FixAction(finding, outcome)
    return FixAction(finding, "failed", f"registration outcome: {outcome}")
