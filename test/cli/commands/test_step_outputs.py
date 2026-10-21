import json
from types import SimpleNamespace

import pytest

from chipcompiler.cli import main as cli_main
from chipcompiler.cli.inspection.step_outputs import output_records
from chipcompiler.engine.snapshot import _write_snapshot, create_engineering_snapshot


@pytest.fixture
def indexed_workspace(tmp_path):
    root = tmp_path / "workspace"
    (root / "home").mkdir(parents=True)
    steps = [{"name": "place", "tool": "dreamplace", "state": "Success"}]
    (root / "home" / "flow.json").write_text(json.dumps({"steps": steps}))
    workspace = SimpleNamespace(
        directory=root,
        flow=SimpleNamespace(data={"steps": steps}),
        parameters=SimpleNamespace(data={"design": "gcd"}),
        design=SimpleNamespace(name="gcd"),
    )
    snapshot = create_engineering_snapshot(workspace, workspace_id="workspace")
    snapshot["stepOutputs"]["steps"] = [
        {
            "step": "place",
            "tool": "dreamplace",
            "state": "Success",
            "verilog": {"path": "output.v", "exists": True},
            "def": {"path": "output.def", "exists": True},
        }
    ]
    (root / "output.def").write_text("DEF")
    _write_snapshot(root / "home" / "engineering-snapshot.json", snapshot)
    return root, snapshot


@pytest.mark.parametrize("format_option", [[], ["--plain"], ["--json"]])
def test_outputs_cli_reads_real_snapshot_without_writes(indexed_workspace, capsys, format_option):
    root, _snapshot = indexed_workspace
    before = {
        path.relative_to(root): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }
    result = cli_main.run(
        [
            "report",
            "step",
            "place",
            "--workspace",
            str(root),
            "--section",
            "outputs",
            *format_option,
        ]
    )
    captured = capsys.readouterr()
    assert result == 0
    assert "output.def" in captured.out
    assert "output.v" in captured.out
    if format_option == ["--json"]:
        records = json.loads(captured.out)
        assert records[1:] == [
            {
                "step": "placement",
                "section": "outputs",
                "kind": "artifact",
                "role": "verilog",
                "path": "output.v",
                "exists": False,
                "bytes": None,
                "availability": "missing",
                "validity": "unknown",
                "source": "home/engineering-snapshot.json",
            },
            {
                "step": "placement",
                "section": "outputs",
                "kind": "artifact",
                "role": "def",
                "path": "output.def",
                "exists": True,
                "bytes": 3,
                "availability": "available",
                "validity": "unknown",
                "source": "home/engineering-snapshot.json",
            },
        ]
    assert before == {
        path.relative_to(root): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }


def test_outputs_rejects_symlink_escape(indexed_workspace, tmp_path):
    root, _snapshot = indexed_workspace
    (root / "output.def").unlink()
    external = tmp_path / "outside.def"
    external.write_text("external")
    (root / "output.def").symlink_to(external)
    assert output_records(str(root), "placement", "success")[-1] == {
        "step": "placement",
        "section": "outputs",
        "kind": "artifact",
        "role": "def",
        "path": "output.def",
        "availability": "outside_workspace",
        "validity": "unknown",
    }


@pytest.mark.parametrize("state", ["unstart", "ongoing", "incomplete"])
def test_outputs_retained_after_rerun_are_not_current(indexed_workspace, state):
    root, _snapshot = indexed_workspace
    assert {record["validity"] for record in output_records(str(root), "placement", state)} == {
        "not_current"
    }


def test_outputs_honors_snapshot_invalidation(indexed_workspace):
    root, snapshot = indexed_workspace
    snapshot["stalePredecessor"] = {"workspaceRevision": 1, "invalidatedStepIds": ["place"]}
    _write_snapshot(root / "home" / "engineering-snapshot.json", snapshot)
    assert {record["validity"] for record in output_records(str(root), "placement", "success")} == {
        "not_current"
    }


@pytest.mark.parametrize("payload", ["{broken", '{"schemaVersion":99}', "{}"])
def test_outputs_corrupt_snapshot_is_unavailable(indexed_workspace, payload):
    root, _snapshot = indexed_workspace
    path = root / "home" / "engineering-snapshot.json"
    path.write_text(payload)
    assert output_records(str(root), "placement", "success")[0]["section_status"] == "unavailable"
    assert path.read_text() == payload


def test_outputs_legacy_snapshot_is_not_migrated(indexed_workspace):
    root, snapshot = indexed_workspace
    snapshot["schemaVersion"] = 3
    snapshot.pop("stepOutputs")
    snapshot.pop("workspaceBindings")
    path = root / "home" / "engineering-snapshot.json"
    path.write_text(json.dumps(snapshot))
    before = path.read_bytes()
    assert output_records(str(root), "placement", "success")[0]["section_status"] == "unavailable"
    assert path.read_bytes() == before


def test_outputs_check_current_files_without_trusting_cached_exists(tmp_path, monkeypatch):
    (tmp_path / "output.def").write_text("DEF")
    snapshot = {
        "stepOutputs": {
            "steps": [
                {"step": "place", "verilog": None, "def": {"path": "output.def", "exists": False}}
            ]
        }
    }
    monkeypatch.setattr(
        "chipcompiler.cli.inspection.step_outputs.read_engineering_snapshot_from_directory",
        lambda directory: snapshot,
    )
    assert output_records(str(tmp_path), "placement", "unstart") == [
        {
            "step": "placement",
            "section": "outputs",
            "kind": "artifact",
            "role": "def",
            "path": "output.def",
            "exists": True,
            "bytes": 3,
            "availability": "available",
            "validity": "not_current",
            "source": "home/engineering-snapshot.json",
        }
    ]


def test_outputs_do_not_stat_external_paths(tmp_path, monkeypatch):
    snapshot = {
        "stepOutputs": {
            "steps": [{"step": "sta", "def": {"path": "../external.def", "exists": True}}]
        }
    }
    monkeypatch.setattr(
        "chipcompiler.cli.inspection.step_outputs.read_engineering_snapshot_from_directory",
        lambda directory: snapshot,
    )
    assert output_records(str(tmp_path), "sta", "success") == [
        {
            "step": "sta",
            "section": "outputs",
            "kind": "artifact",
            "role": "def",
            "path": "../external.def",
            "availability": "outside_workspace",
            "validity": "unknown",
        }
    ]


def test_missing_snapshot_is_unavailable(tmp_path):
    records = output_records(str(tmp_path), "sta", "success")
    assert records[0]["section_status"] == "unavailable"
