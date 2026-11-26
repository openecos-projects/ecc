"""Typed journal and private staging directory management for Workspace drafts."""

import json
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from tempfile import mkdtemp
from typing import Any

from chipcompiler.utility.file import write_text_atomic

JOURNAL_FILENAME = ".workspace-draft-publish.json"
JOURNAL_VERSION = 1
STAGING_ROOT = ".workspace-draft-builds"
STAGING_OWNER = ".owner"
CONFIG_STAGE = "ecc.toml.next"
DRAFT_PROJECT_CHANGES_SKIPPED = "draft_project_changes_skipped"


@dataclass(frozen=True)
class DraftJournal:
    project_id: str
    workspace: str
    device: int
    inode: int
    original: str
    updated: str
    rtl: tuple[str, ...]
    rtl_sha256: dict[str, str]
    start_step: str | None
    end_step: str | None
    skip_steps: list[str] | None
    empty_mode: int | None
    project_changes_skipped: str | None = None

    def target(self, project: Path) -> Path:
        return project / self.workspace

    def to_dict(self) -> dict:
        payload = {
            "version": JOURNAL_VERSION,
            "project_id": self.project_id,
            "workspace": self.workspace,
            "device": self.device,
            "inode": self.inode,
            "original": self.original,
            "updated": self.updated,
            "rtl": list(self.rtl),
            "rtl_sha256": dict(self.rtl_sha256),
            "start_step": self.start_step,
            "end_step": self.end_step,
            "skip_steps": self.skip_steps,
            "empty_mode": self.empty_mode,
        }
        if self.project_changes_skipped is not None:
            payload[DRAFT_PROJECT_CHANGES_SKIPPED] = self.project_changes_skipped
        return payload

    @classmethod
    def from_dict(cls, data: Any) -> "DraftJournal":
        if not isinstance(data, dict) or data.get("version") != JOURNAL_VERSION:
            raise OSError("Invalid Workspace draft journal")
        workspace = data.get("workspace")
        if (
            not isinstance(workspace, str)
            or Path(workspace).name != workspace
            or workspace in ("", ".", "..")
        ):
            raise OSError("Invalid Workspace draft target")
        project_id = data.get("project_id")
        device, inode = data.get("device"), data.get("inode")
        original, updated = data.get("original"), data.get("updated")
        rtl = data.get("rtl")
        rtl_sha256 = data.get("rtl_sha256", {})
        empty_mode = data.get("empty_mode")
        skipped = data.get(DRAFT_PROJECT_CHANGES_SKIPPED)
        if (
            not isinstance(project_id, str)
            or isinstance(device, bool)
            or not isinstance(device, int)
            or isinstance(inode, bool)
            or not isinstance(inode, int)
            or not isinstance(original, str)
            or not isinstance(updated, str)
            or not isinstance(rtl, list)
            or not all(isinstance(item, str) for item in rtl)
            or not isinstance(rtl_sha256, dict)
            or not all(
                isinstance(key, str) and isinstance(value, str) for key, value in rtl_sha256.items()
            )
            or (
                empty_mode is not None
                and (isinstance(empty_mode, bool) or not isinstance(empty_mode, int))
            )
            or (skipped is not None and not isinstance(skipped, str))
        ):
            raise OSError("Invalid Workspace draft journal")
        return cls(
            project_id=project_id,
            workspace=workspace,
            device=device,
            inode=inode,
            original=original,
            updated=updated,
            rtl=tuple(rtl),
            rtl_sha256=dict(rtl_sha256),
            start_step=data.get("start_step"),
            end_step=data.get("end_step"),
            skip_steps=data.get("skip_steps"),
            empty_mode=empty_mode,
            project_changes_skipped=skipped,
        )


def read_journal(journal: Path) -> DraftJournal | None:
    if journal.is_symlink():
        raise OSError("Workspace draft journal must be a regular file")
    try:
        raw = json.loads(journal.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except ValueError as exc:
        raise OSError("Invalid Workspace draft journal") from exc
    return DraftJournal.from_dict(raw)


def has_pending_draft(project: Path, workspace: Path) -> bool:
    record = read_journal(project / JOURNAL_FILENAME)
    return record is not None and record.target(project) == workspace


def staging_dir(project: Path, workspace: Path) -> Path:
    root = project / STAGING_ROOT
    staging = root / "workspaces" / workspace.name
    if not owns_staging_root(root) or staging.resolve() != staging:
        raise OSError("Workspace draft staging must be a direct directory")
    return staging


def owns_staging_root(root: Path) -> bool:
    owner = root / STAGING_OWNER
    return (
        root.is_dir()
        and not root.is_symlink()
        and not owner.is_symlink()
        and owner.is_file()
        and owner.read_text(encoding="utf-8") == "ecc workspace draft staging\n"
        and (root / "workspaces").is_dir()
        and not (root / "workspaces").is_symlink()
    )


def prepare_staging_root(project: Path) -> None:
    root = project / STAGING_ROOT
    if owns_staging_root(root):
        return
    if root.exists() or root.is_symlink():
        raise FileExistsError(f"Workspace draft staging path is already occupied: {root}")
    # Publish ownership and the directory together, including when two distinct
    # Workspace builds start before either takes the Project lock.
    staging = Path(mkdtemp(prefix=".workspace-draft-root-", dir=project))
    try:
        (staging / "workspaces").mkdir()
        write_text_atomic(staging / STAGING_OWNER, "ecc workspace draft staging\n")
        try:
            staging.rename(root)
        except OSError:
            if not owns_staging_root(root):
                raise
    finally:
        discard_staging(staging)


def discard_staging(staging: Path) -> None:
    if staging.resolve() != staging:
        raise OSError("Workspace draft staging must be a direct directory")
    if staging.is_dir():
        shutil.rmtree(staging)


def owns_directory(path: Path, record: DraftJournal) -> bool:
    if path.resolve() != path or not path.is_dir():
        return False
    identity = path.stat()
    return (identity.st_dev, identity.st_ino) == (record.device, record.inode)


def check_destination(workspace: Path, *, reuse_empty: bool) -> int | None:
    if workspace.is_symlink():
        raise FileExistsError(f"Workspace is a symbolic link: {workspace}")
    if not workspace.exists():
        return None
    if not (reuse_empty and workspace.is_dir() and not any(workspace.iterdir())):
        raise FileExistsError(f"Workspace already exists: {workspace}")
    return stat.S_IMODE(workspace.stat().st_mode)


def validate_draft_destination(project: Path, workspace: Path, *, reuse_empty: bool) -> int | None:
    """Read-only destination check shared by draft preview and locked draft builds."""
    if workspace.is_symlink():
        raise FileExistsError(f"Workspace is a symbolic link: {workspace}")
    if workspace.parent != project or workspace.resolve() != workspace:
        raise OSError("Draft Workspace is outside the Project.")
    if workspace.name == STAGING_ROOT:
        raise FileExistsError(f"Workspace path is reserved: {workspace}")
    if has_pending_draft(project, workspace):
        raise OSError("An unfinished Workspace draft requires project reconcile.")
    return check_destination(workspace, reuse_empty=reuse_empty)
