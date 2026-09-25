"""Run manifest: schema version, run id, tool versions for dashboard joins."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

# Bump when manifest field set or semantics change (dashboard consumers pin this).
MANIFEST_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class RunManifest:
    schema_version: int
    kind: str
    run_id: str
    exported_at: str
    design: str
    workspace: str
    workspace_id: str
    git_commit: str | None
    spec_path: str | None
    spec_sha256: str | None
    tools: dict[str, str]
    pdk_root: str | None = None
    gates_total: int = 0
    gates_failed: int = 0
    extra: dict = field(default_factory=dict)


def _sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tool_version(argv: list[str]) -> str:
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, check=False, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable"
    text = (proc.stdout or proc.stderr or "").strip().splitlines()
    return text[0] if text else "unavailable"


def _git_commit(repo: Path | None = None) -> str | None:
    env_commit = os.environ.get("GITHUB_SHA") or os.environ.get("ECC_GIT_COMMIT")
    if env_commit:
        return env_commit.strip()
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo) if repo else None,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (proc.stdout or "").strip()
    return text or None


def build_run_manifest(
    *,
    design: str,
    workspace: str | Path,
    spec_path: str | Path | None,
    gates_total: int = 0,
    gates_failed: int = 0,
    run_id: str | None = None,
    extra: dict | None = None,
) -> RunManifest:
    from chipcompiler import __version__ as ecc_version

    ws = Path(workspace).resolve()
    spec = Path(spec_path) if spec_path else None
    pdk = os.environ.get("ECC_PDK_ROOT") or os.environ.get("CHIPCOMPILER_PDK_ROOT")
    return RunManifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        kind="signoff_csv_run",
        run_id=run_id or os.environ.get("ECC_SIGNOFF_RUN_ID") or str(uuid.uuid4()),
        exported_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        design=design,
        workspace=str(ws),
        workspace_id=ws.name,
        git_commit=_git_commit(Path(os.environ.get("ECC_REPO_ROOT") or ws)),
        spec_path=str(spec.resolve()) if spec and spec.is_file() else (str(spec) if spec else None),
        spec_sha256=_sha256_file(spec) if spec else None,
        tools={
            "ecc": ecc_version,
            "python": platform.python_version(),
            "lit": _tool_version(["lit", "--version"]),
            "filecheck": _tool_version(["filecheck", "--version"]),
        },
        pdk_root=str(Path(pdk).resolve()) if pdk else None,
        gates_total=gates_total,
        gates_failed=gates_failed,
        extra=dict(extra or {}),
    )


def write_run_manifest(manifest: RunManifest, path: str | Path) -> Path:
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(manifest)
    dest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return dest
