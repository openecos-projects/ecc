import queue
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from chipcompiler.runtime import signoff_export
from chipcompiler.runtime.requests import (
    WorkspaceExportSignoffRequest,
    WorkspaceInspectSignoffRequest,
)
from chipcompiler.runtime.sessions import WorkspaceSessionRegistry
from chipcompiler.runtime.workspace_api import RuntimeApiError, WorkspaceRuntimeApi


def test_workspace_export_signoff_returns_exact_output_path(monkeypatch, tmp_path):
    workspace = SimpleNamespace(directory=tmp_path / "workspace")
    sessions = WorkspaceSessionRegistry()
    session = sessions.open_session(workspace.directory, workspace=workspace)
    output_path = tmp_path / "exports" / "custom name.tar.gz"
    calls = []

    def fake_export(active_workspace, requested_output):
        calls.append((active_workspace, requested_output))
        return str(output_path)

    monkeypatch.setattr(
        "chipcompiler.runtime.signoff_export.export_signoff_package_archive",
        fake_export,
    )
    api = WorkspaceRuntimeApi(sessions=sessions)

    result = api.export_signoff(
        WorkspaceExportSignoffRequest(
            workspace_id=session.workspace_id,
            output_path=str(output_path),
        )
    )

    assert result == {"outputPath": str(output_path)}
    assert calls == [(workspace, str(output_path))]


def test_workspace_export_signoff_waits_for_session_mutation_lock(monkeypatch, tmp_path):
    workspace = SimpleNamespace(directory=tmp_path / "workspace")
    sessions = WorkspaceSessionRegistry()
    session = sessions.open_session(workspace.directory, workspace=workspace)
    output_path = tmp_path / "export.tar.gz"
    entered = threading.Event()
    results = queue.Queue()

    def fake_export(_workspace, requested_output):
        entered.set()
        return requested_output

    monkeypatch.setattr(
        "chipcompiler.runtime.signoff_export.export_signoff_package_archive",
        fake_export,
    )
    api = WorkspaceRuntimeApi(sessions=sessions)

    def run_export():
        try:
            results.put(
                api.export_signoff(
                    WorkspaceExportSignoffRequest(
                        workspace_id=session.workspace_id,
                        output_path=str(output_path),
                    )
                )
            )
        except BaseException as error:  # pragma: no cover - re-raised below
            results.put(error)

    with session.mutation_lock:
        worker = threading.Thread(target=run_export)
        worker.start()
        assert not entered.wait(0.1)
        assert worker.is_alive()

    worker.join(timeout=2)
    assert not worker.is_alive()
    result = results.get_nowait()
    if isinstance(result, BaseException):
        raise result
    assert result == {"outputPath": str(output_path)}
    assert entered.is_set()


def test_inspect_signoff_package_returns_grouped_review_with_actionable_details(
    monkeypatch,
):
    class FakeFlow:
        def __init__(self, workspace):
            assert workspace == "workspace"

        def collect_signoff_package(self, options):
            assert options.archive is False
            assert options.materialize is False
            return SimpleNamespace(
                copied=[
                    {
                        "destination": "initial/gcd.v",
                        "size_bytes": 10,
                    },
                    {
                        "destination": "config/sta.json",
                        "size_bytes": 20,
                    },
                    {
                        "destination": "final/timing/sta/MAX_125/RCworst/qor_summary.rpt",
                        "size_bytes": 30,
                    },
                ],
                missing_required=["harden/gcd.gds", "flow step RCX is Failed"],
                missing_optional=["final/design/gcd.png"],
                warnings=["home checklist contains failed or warning items"],
                issues=[
                    SimpleNamespace(
                        kind="resource",
                        label="harden.gds",
                        location="Harden_ecc/output/gcd_Harden.gds",
                        reason="Required file is missing or empty",
                        required=True,
                        destination="harden/gcd.gds",
                    ),
                    SimpleNamespace(
                        kind="flow",
                        label="RCX flow step",
                        location="RCX",
                        reason="State is Failed",
                        required=True,
                        destination="flow step RCX",
                    ),
                    SimpleNamespace(
                        kind="resource",
                        label="final.design.image",
                        location="filler_ecc/output/gcd_filler.png",
                        reason="Optional file is missing or empty",
                        required=False,
                        destination="final/design/gcd.png",
                    ),
                    SimpleNamespace(
                        kind="checklist",
                        label="check setup slack",
                        location="STA / Timing / check setup slack",
                        reason="Failed: WNS is negative",
                        required=False,
                        destination="final/reports/checklist.json",
                    ),
                ],
            )

    monkeypatch.setattr(signoff_export, "EngineFlow", FakeFlow)

    review = signoff_export.inspect_signoff_package("workspace")

    assert review["status"] == "blocked"
    assert [group["id"] for group in review["groups"]] == [
        "initial",
        "config",
        "harden",
        "final_design",
        "sta",
        "spef",
        "reports",
    ]
    assert review["groups"][2] == {
        "id": "harden",
        "label": "Harden",
        "status": "blocked",
        "available": 0,
        "expected": 1,
        "summary": "1 required resource missing",
    }
    assert review["groups"][3]["status"] == "attention"
    assert [risk["severity"] for risk in review["risks"]] == [
        "blocked",
        "blocked",
        "warning",
        "warning",
    ]
    harden_risk = next(
        risk for risk in review["risks"] if risk["title"] == "Harden resources missing"
    )
    assert harden_risk["details"] == [
        {
            "kind": "resource",
            "label": "harden.gds",
            "location": "Harden_ecc/output/gcd_Harden.gds",
            "reason": "Required file is missing or empty",
        }
    ]
    flow_risk = next(
        risk for risk in review["risks"] if risk["title"] == "Flow requirements not complete"
    )
    assert flow_risk["details"] == [
        {
            "kind": "flow",
            "label": "RCX flow step",
            "location": "RCX",
            "reason": "State is Failed",
        }
    ]
    checklist_risk = next(
        risk for risk in review["risks"] if risk["title"] == "Checklist attention"
    )
    assert checklist_risk["details"] == [
        {
            "kind": "checklist",
            "label": "check setup slack",
            "location": "STA / Timing / check setup slack",
            "reason": "Failed: WNS is negative",
        }
    ]
    assert all(
        not detail["location"].startswith("/")
        for risk in review["risks"]
        for detail in risk["details"]
    )


def test_inspect_signoff_package_groups_current_qor_analysis_risks(monkeypatch):
    class FakeFlow:
        def __init__(self, workspace):
            assert workspace == "workspace"

        def collect_signoff_package(self, options):
            assert options.archive is False
            assert options.materialize is False
            return SimpleNamespace(
                copied=[],
                missing_required=["analysis/Harden/qor_summary.json"],
                missing_optional=["analysis/place/qor_summary.json"],
                warnings=["current QoR analysis requires attention"],
                issues=[
                    SimpleNamespace(
                        kind="analysis",
                        label="final_package_complete",
                        location="Harden_ecc/analysis/qor_summary.json",
                        reason="harden_artifact_missing_count actual=1 does not satisfy 0",
                        required=True,
                        destination="analysis/Harden/qor_summary.json",
                    ),
                    SimpleNamespace(
                        kind="freshness",
                        label="place_overflow",
                        location="place_dreamplace/analysis/qor_summary.json",
                        reason="The required current QoR metric is unavailable.",
                        required=False,
                        destination="analysis/place/qor_summary.json",
                    ),
                ],
            )

    monkeypatch.setattr(signoff_export, "EngineFlow", FakeFlow)

    review = signoff_export.inspect_signoff_package("workspace")

    assert review["status"] == "blocked"
    harden = next(group for group in review["groups"] if group["id"] == "harden")
    assert harden["status"] == "blocked"
    assert harden["available"] == 0
    assert harden["expected"] == 0
    assert harden["summary"] == "Current QoR analysis blocks signoff"
    blocked = next(risk for risk in review["risks"] if risk["severity"] == "blocked")
    assert blocked["details"] == [
        {
            "kind": "analysis",
            "label": "final_package_complete",
            "location": "Harden_ecc/analysis/qor_summary.json",
            "reason": "harden_artifact_missing_count actual=1 does not satisfy 0",
        }
    ]
    report_warning = next(
        risk
        for risk in review["risks"]
        if risk["title"] == "Reports QoR analysis requires attention"
    )
    assert report_warning["details"][0]["kind"] == "freshness"


def test_workspace_inspect_signoff_waits_for_session_mutation_lock(monkeypatch, tmp_path):
    workspace = SimpleNamespace(directory=tmp_path / "workspace")
    sessions = WorkspaceSessionRegistry()
    session = sessions.open_session(workspace.directory, workspace=workspace)
    entered = threading.Event()
    results = queue.Queue()

    def fake_inspect(active_workspace):
        assert active_workspace is workspace
        entered.set()
        return {"status": "ready", "groups": [], "risks": []}

    monkeypatch.setattr(signoff_export, "inspect_signoff_package", fake_inspect)
    api = WorkspaceRuntimeApi(sessions=sessions)
    def run_inspection():
        try:
            results.put(api.inspect_signoff(WorkspaceInspectSignoffRequest(workspace_id=session.workspace_id)))
        except BaseException as error:  # pragma: no cover - re-raised below
            results.put(error)

    with session.mutation_lock:
        worker = threading.Thread(target=run_inspection)
        worker.start()
        assert not entered.wait(0.1)
        assert worker.is_alive()

    worker.join(timeout=2)
    assert not worker.is_alive()
    result = results.get_nowait()
    if isinstance(result, BaseException):
        raise result
    assert result == {"status": "ready", "groups": [], "risks": []}


def test_export_signoff_package_archive_collects_temporarily_and_replaces_atomically(
    monkeypatch,
    tmp_path,
):
    from chipcompiler.runtime.signoff_export import export_signoff_package_archive

    output_path = tmp_path / "nested" / "chosen.tar.gz"
    captured_output_dirs = []

    class FakeFlow:
        def __init__(self, workspace):
            assert workspace == "workspace"

        def collect_signoff_package(self, options):
            captured_output_dirs.append(options.output_dir)
            archive = Path(options.output_dir) / "design_signoff_package.tar.gz"
            archive.write_bytes(b"archive")
            return SimpleNamespace(
                ok=True,
                archive_path=str(archive),
                missing_required=[],
            )

    monkeypatch.setattr(
        "chipcompiler.runtime.signoff_export.EngineFlow",
        FakeFlow,
    )

    result = export_signoff_package_archive("workspace", str(output_path))

    assert result == str(output_path.resolve())
    assert output_path.read_bytes() == b"archive"
    assert captured_output_dirs
    assert not Path(captured_output_dirs[0]).exists()
    assert not list(output_path.parent.glob(f".{output_path.name}.*"))


def test_export_signoff_package_archive_preserves_existing_target_on_incomplete_result(
    monkeypatch,
    tmp_path,
):
    from chipcompiler.runtime.signoff_export import export_signoff_package_archive

    output_path = tmp_path / "existing.tar.gz"
    output_path.write_bytes(b"old")

    class FakeFlow:
        def __init__(self, workspace):
            pass

        def collect_signoff_package(self, options):
            return SimpleNamespace(
                ok=False,
                archive_path=None,
                missing_required=["harden/design.gds", "harden/design.lef"],
            )

    monkeypatch.setattr(
        "chipcompiler.runtime.signoff_export.EngineFlow",
        FakeFlow,
    )

    with pytest.raises(RuntimeApiError) as exc_info:
        export_signoff_package_archive("workspace", str(output_path))

    assert exc_info.value.code == "command_failed"
    assert "harden/design.gds" in exc_info.value.message
    assert "harden/design.lef" in exc_info.value.message
    assert output_path.read_bytes() == b"old"


def test_export_signoff_package_archive_replaces_symlink_entry_not_target(
    monkeypatch,
    tmp_path,
):
    from chipcompiler.runtime.signoff_export import export_signoff_package_archive

    target = tmp_path / "target.tar.gz"
    target.write_bytes(b"target")
    output_path = tmp_path / "chosen.tar.gz"
    try:
        output_path.symlink_to(target.name)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable")

    class FakeFlow:
        def __init__(self, workspace):
            pass

        def collect_signoff_package(self, options):
            archive = Path(options.output_dir) / "archive.tar.gz"
            archive.write_bytes(b"new")
            return SimpleNamespace(ok=True, archive_path=str(archive), missing_required=[])

    monkeypatch.setattr(
        "chipcompiler.runtime.signoff_export.EngineFlow",
        FakeFlow,
    )

    export_signoff_package_archive("workspace", str(output_path))

    assert not output_path.is_symlink()
    assert output_path.read_bytes() == b"new"
    assert target.read_bytes() == b"target"
