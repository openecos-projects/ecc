"""Runtime RPC handlers for ``project.doctor.check`` / ``project.doctor.repair``.

Fixtures mirror the CLI doctor tests: manifest-only projects whose workspace
directories carry the real ``home/flow.json`` + ``home/params.toml`` pair so
inspection derives the same fields a registration would write. The check
handler must stay read-only; only repair may write.
"""

import json

from chipcompiler.data.parameter import Parameters, save_parameter
from chipcompiler.runtime.requests import (
    ProjectDoctorCheckRequest,
    ProjectDoctorRepairRequest,
)
from chipcompiler.runtime.workspace_api import WorkspaceRuntimeApi


def _make_workspace(project_dir, name, *, state="Success", start="Synthesis", end="Harden"):
    """A consistent workspace directory: range Synthesis..Harden, patch {}."""
    home = project_dir / name / "home"
    home.mkdir(parents=True)
    (home / "flow.json").write_text(
        json.dumps({"steps": [{"name": start, "tool": "yosys", "state": state}]})
    )
    assert save_parameter(
        Parameters(
            path=home / "params.toml",
            data={
                "pdk": "ics55",
                "design": "gcd",
                "top_module": "gcd",
                "clock": "clk",
                "frequency_max": 100,
                "_flow": {"start": start, "end": end},
            },
        )
    )


def _write_manifest(project_dir, workspaces):
    project_dir.mkdir(parents=True, exist_ok=True)
    document = {
        "schema_version": 1,
        "design_name": "gcd",
        "root_path": str(project_dir),
        "base_design": {
            "pdk": "ics55",
            "top_module": "gcd",
            "clock": "clk",
            "rtl_list": [],
            "parameters": {"design": "gcd", "frequency_max": 100},
        },
        "workspaces": workspaces,
    }
    (project_dir / "project.json").write_text(json.dumps(document))


def _entry(project_dir, workspace_id, status="success"):
    return {
        "workspace_id": workspace_id,
        "workspace_path": str(project_dir / workspace_id),
        "status": status,
    }


def _check(api, project_dir):
    return api.check_project_doctor(ProjectDoctorCheckRequest(project_dir=str(project_dir)))


def _repair(api, project_dir):
    return api.repair_project_doctor(ProjectDoctorRepairRequest(project_dir=str(project_dir)))


def _manifest(project_dir):
    return json.loads((project_dir / "project.json").read_text())


class TestProjectDoctorCheck:
    def test_consistent_project_is_ok_and_writes_nothing(self, tmp_path):
        project_dir = tmp_path / "gcd"
        _make_workspace(project_dir, "ws_0001")
        _write_manifest(project_dir, [_entry(project_dir, "ws_0001")])
        before = (project_dir / "project.json").read_bytes()

        result = _check(WorkspaceRuntimeApi(), project_dir)

        assert result == {
            "doctor": "project",
            "status": "ok",
            "projectRoot": str(project_dir),
            "checked": 1,
            "inconsistent": 0,
            "findings": [],
        }
        assert (project_dir / "project.json").read_bytes() == before

    def test_findings_are_reported_without_writes(self, tmp_path):
        project_dir = tmp_path / "gcd"
        _make_workspace(project_dir, "ws_0001")
        entry = {
            **_entry(project_dir, "ws_0001", status="failed"),
            "start_step": "Place",
            "parameter_patch": {"frequency_max": {"from": 100, "to": 125}},
        }
        _write_manifest(project_dir, [entry, _entry(project_dir, "ghost")])
        before = (project_dir / "project.json").read_bytes()

        result = _check(WorkspaceRuntimeApi(), project_dir)

        assert result["status"] == "failed"
        assert result["checked"] == 2
        assert result["inconsistent"] == 2
        assert [finding["check"] for finding in result["findings"]] == [
            "derived-field-mismatch",
            "missing-directory",
        ]
        finding = result["findings"][0]
        assert finding["status"] == "fail"
        assert finding["workspace_id"] == "ws_0001"
        assert finding["workspace"] == str(project_dir / "ws_0001")
        assert finding["detail"]
        assert (project_dir / "project.json").read_bytes() == before

    def test_manifest_is_discovered_from_a_nested_directory(self, tmp_path):
        project_dir = tmp_path / "gcd"
        _make_workspace(project_dir, "ws_0001")
        _write_manifest(project_dir, [_entry(project_dir, "ws_0001")])

        result = _check(WorkspaceRuntimeApi(), project_dir / "ws_0001")

        assert result["status"] == "ok"
        assert result["projectRoot"] == str(project_dir)

    def test_directory_without_manifest_is_not_applicable(self, tmp_path):
        plain = tmp_path / "plain"
        plain.mkdir()

        assert _check(WorkspaceRuntimeApi(), plain) == {
            "doctor": "project",
            "status": "not_applicable",
            "projectRoot": None,
            "checked": 0,
            "inconsistent": 0,
            "findings": [],
        }
        assert _check(WorkspaceRuntimeApi(), tmp_path / "missing")["status"] == "not_applicable"


class TestProjectDoctorRepair:
    def test_repair_rebuilds_derived_fields_and_rechecks_clean(self, tmp_path):
        project_dir = tmp_path / "gcd"
        _make_workspace(project_dir, "ws_0001")
        entry = {
            **_entry(project_dir, "ws_0001", status="failed"),
            "start_step": "Place",
            "parameter_patch": {"frequency_max": {"from": 100, "to": 125}},
        }
        _write_manifest(project_dir, [entry])
        api = WorkspaceRuntimeApi()

        result = _repair(api, project_dir)

        assert result["status"] == "fixed"
        assert result["checked"] == 1
        assert result["inconsistent"] == 1
        assert result["fixed"] == 1
        assert result["findings"][0]["check"] == "derived-field-mismatch"
        assert result["findings"][0]["fix"] == "rebuilt"
        (repaired,) = _manifest(project_dir)["workspaces"]
        assert repaired["start_step"] == "Synth"
        assert repaired["end_step"] == "Harden"
        assert repaired["status"] == "success"
        assert repaired["parameter_patch"] == {}
        assert _check(api, project_dir)["status"] == "ok"

    def test_repair_removes_missing_directory_entry(self, tmp_path):
        project_dir = tmp_path / "gcd"
        _make_workspace(project_dir, "ws_0001")
        _write_manifest(
            project_dir,
            [_entry(project_dir, "ghost"), _entry(project_dir, "ws_0001")],
        )

        result = _repair(WorkspaceRuntimeApi(), project_dir)

        assert result["status"] == "fixed"
        assert result["findings"][0]["fix"] == "removed"
        assert [w["workspace_id"] for w in _manifest(project_dir)["workspaces"]] == ["ws_0001"]

    def test_repair_registers_unregistered_directory(self, tmp_path):
        project_dir = tmp_path / "gcd"
        _make_workspace(project_dir, "ws_0002")
        _write_manifest(project_dir, [])

        result = _repair(WorkspaceRuntimeApi(), project_dir)

        assert result["status"] == "fixed"
        assert result["findings"][0]["check"] == "unregistered-directory"
        assert result["findings"][0]["fix"] == "registered"
        (entry,) = _manifest(project_dir)["workspaces"]
        assert entry["workspace_id"] == "ws_0002"
        assert entry["status"] == "success"

    def test_repair_on_consistent_project_writes_nothing(self, tmp_path):
        project_dir = tmp_path / "gcd"
        _make_workspace(project_dir, "ws_0001")
        _write_manifest(project_dir, [_entry(project_dir, "ws_0001")])
        before = (project_dir / "project.json").read_bytes()

        result = _repair(WorkspaceRuntimeApi(), project_dir)

        assert result["status"] == "ok"
        assert result["inconsistent"] == 0
        assert "fixed" not in result
        assert (project_dir / "project.json").read_bytes() == before

    def test_repair_without_manifest_is_not_applicable(self, tmp_path):
        plain = tmp_path / "plain"
        plain.mkdir()

        result = _repair(WorkspaceRuntimeApi(), plain)

        assert result["status"] == "not_applicable"
        assert result["findings"] == []
        assert not (plain / "project.json").exists()
