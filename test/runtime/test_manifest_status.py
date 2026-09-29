#!/usr/bin/env python

import json

import pytest

from chipcompiler.project.manifest_write import (
    build_manifest_document,
    write_manifest_if_absent,
)
from chipcompiler.runtime.manifest_status import (
    manifest_run_status,
    write_back_workspace_derived_fields,
    write_back_workspace_run_status,
)
from chipcompiler.runtime.operations import RuntimeOperationCancelled


def _workspace_facts(workspace_path, *, state="Success", frequency_max=125):
    from chipcompiler.data.parameter import Parameters, save_parameter

    home = workspace_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    (home / "flow.json").write_text(
        json.dumps({"steps": [{"name": "Synthesis", "tool": "yosys", "state": state}]})
    )
    assert save_parameter(
        Parameters(
            path=home / "params.toml",
            data={
                "pdk": "ics55",
                "design": "gcd",
                "top_module": "gcd",
                "clock": "clk",
                "frequency_max": frequency_max,
                "_flow": {"start": "Synthesis", "end": "Synthesis"},
            },
        )
    )


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


def test_write_back_derived_fields_refreshes_registered_workspace(tmp_path):
    workspace_path = _project_with_workspace(tmp_path)
    _workspace_facts(workspace_path)

    write_back_workspace_derived_fields(workspace_path)

    document = json.loads((tmp_path / "project.json").read_text())
    (entry,) = document["workspaces"]
    assert entry["start_step"] == "Synth"
    assert entry["end_step"] == "Synth"
    assert entry["status"] == "success"
    assert entry["parameter_patch"] == {"frequency_max": {"from": None, "to": 125}}
    # Declared lineage is never rewritten by a derived-field refresh.
    assert entry["source_workspace_id"] is None
    assert entry["branch_from"] is None


def test_write_back_derived_fields_skips_unregistered_workspace(tmp_path):
    _project_with_workspace(tmp_path, workspace_id="ws_0001")
    outsider = tmp_path / "elsewhere"
    outsider.mkdir()
    _workspace_facts(outsider)

    write_back_workspace_derived_fields(outsider)

    document = json.loads((tmp_path / "project.json").read_text())
    (entry,) = document["workspaces"]
    assert entry["status"] == "not_started"
    assert entry["start_step"] == "Synth"
    assert entry["end_step"] == "Harden"


def test_write_back_derived_fields_skips_workspace_outside_manifest_project(tmp_path):
    workspace_path = tmp_path / "standalone"
    workspace_path.mkdir()
    _workspace_facts(workspace_path)

    write_back_workspace_derived_fields(workspace_path)

    assert not (tmp_path / "project.json").exists()


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


def _recorded_write_backs(monkeypatch):
    """Both manifest write-backs as an ordered (kind, payload) event list."""
    events = []
    monkeypatch.setattr(
        "chipcompiler.runtime.manifest_status.write_back_workspace_run_status",
        lambda _directory, status: events.append(("status", status)),
    )
    monkeypatch.setattr(
        "chipcompiler.runtime.manifest_status.write_back_workspace_derived_fields",
        lambda _directory, *, include_status=True: events.append(("derived", include_status)),
    )
    return events


def test_manifest_run_status_converges_derived_fields_before_success(monkeypatch, tmp_path):
    events = _recorded_write_backs(monkeypatch)

    with manifest_run_status(tmp_path):
        pass

    assert events == [("status", "running"), ("derived", False), ("status", "success")]


def test_manifest_run_status_converges_derived_fields_before_failed(monkeypatch, tmp_path):
    events = _recorded_write_backs(monkeypatch)

    with pytest.raises(ValueError, match="boom"), manifest_run_status(tmp_path):
        raise ValueError("boom")

    assert events == [("status", "running"), ("derived", False), ("status", "failed")]


def test_manifest_run_status_converges_derived_fields_before_in_progress(monkeypatch, tmp_path):
    events = _recorded_write_backs(monkeypatch)

    with pytest.raises(RuntimeOperationCancelled), manifest_run_status(tmp_path):
        raise RuntimeOperationCancelled("cancelled at a step boundary")

    assert events == [("status", "running"), ("derived", False), ("status", "in_progress")]


def test_manifest_run_status_converges_entry_on_terminal_exit(tmp_path):
    """A run writes back computed parameters: at the terminal exit the
    entry's range/patch re-converge on the directory, then the terminal
    status lands — doctor finds nothing afterwards."""
    workspace_path = _project_with_workspace(tmp_path)
    _workspace_facts(workspace_path)

    with manifest_run_status(workspace_path):
        pass

    document = json.loads((tmp_path / "project.json").read_text())
    (entry,) = document["workspaces"]
    assert entry["status"] == "success"
    assert entry["start_step"] == "Synth"
    assert entry["end_step"] == "Synth"
    assert entry["parameter_patch"] == {"frequency_max": {"from": None, "to": 125}}
