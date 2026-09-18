#!/usr/bin/env python

import json

import pytest

from chipcompiler.project.manifest_write import (
    build_manifest_document,
    write_manifest_if_absent,
)
from chipcompiler.runtime.manifest_status import (
    manifest_run_status,
    write_back_workspace_run_status,
)
from chipcompiler.runtime.operations import RuntimeOperationCancelled


def _project_with_workspace(project_dir, workspace_id="ws_0001"):
    workspace_path = project_dir / workspace_id
    workspace_path.mkdir(parents=True)
    document = build_manifest_document(
        str(project_dir),
        design_name="gcd",
        base_design={"parameters": {"design": "gcd"}},
        workspace_id=workspace_id,
        workspace_path=str(workspace_path),
        start_step="Synth",
        end_step="Harden",
        status="not_started",
    )
    write_manifest_if_absent(str(project_dir), document)
    return workspace_path


def _manifest_status(project_dir, workspace_id="ws_0001"):
    document = json.loads((project_dir / "project.json").read_text())
    (entry,) = [w for w in document["workspaces"] if w["workspace_id"] == workspace_id]
    return entry["status"]


def test_write_back_updates_registered_workspace(tmp_path):
    workspace_path = _project_with_workspace(tmp_path)

    write_back_workspace_run_status(workspace_path, "success")

    assert _manifest_status(tmp_path) == "success"


def test_write_back_skips_workspace_outside_manifest_project(tmp_path):
    workspace_path = tmp_path / "standalone"
    workspace_path.mkdir()

    write_back_workspace_run_status(workspace_path, "success")

    assert not (tmp_path / "project.json").exists()


def test_write_back_ignores_manifest_that_does_not_register_the_workspace(tmp_path):
    _project_with_workspace(tmp_path, workspace_id="ws_0001")
    outsider = tmp_path / "elsewhere"
    outsider.mkdir()

    write_back_workspace_run_status(outsider, "failed")

    assert _manifest_status(tmp_path) == "not_started"


def test_manifest_run_status_records_running_then_success(monkeypatch, tmp_path):
    statuses = []
    monkeypatch.setattr(
        "chipcompiler.runtime.manifest_status.write_back_workspace_run_status",
        lambda _directory, status: statuses.append(status),
    )

    with manifest_run_status(tmp_path):
        pass

    assert statuses == ["running", "success"]


def test_manifest_run_status_records_running_then_failed(monkeypatch, tmp_path):
    statuses = []
    monkeypatch.setattr(
        "chipcompiler.runtime.manifest_status.write_back_workspace_run_status",
        lambda _directory, status: statuses.append(status),
    )

    with pytest.raises(ValueError, match="boom"), manifest_run_status(tmp_path):
        raise ValueError("boom")

    assert statuses == ["running", "failed"]


def test_manifest_run_status_records_in_progress_on_cancel(monkeypatch, tmp_path):
    statuses = []
    monkeypatch.setattr(
        "chipcompiler.runtime.manifest_status.write_back_workspace_run_status",
        lambda _directory, status: statuses.append(status),
    )

    with pytest.raises(RuntimeOperationCancelled), manifest_run_status(tmp_path):
        raise RuntimeOperationCancelled("cancelled at a step boundary")

    assert statuses == ["running", "in_progress"]
