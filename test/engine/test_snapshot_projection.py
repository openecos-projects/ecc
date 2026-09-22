from pathlib import Path
from types import SimpleNamespace

from chipcompiler.engine.snapshot import commit_engineering_snapshot, create_engineering_snapshot


def test_engineering_snapshot_is_a_bounded_projection(tmp_path):
    image = tmp_path / "Synthesis_yosys" / "output" / "gcd_Synthesis.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"layout")
    workspace = SimpleNamespace(
        directory=Path(tmp_path),
        flow=SimpleNamespace(
            data={"steps": [{"name": "Synthesis", "tool": "ecc", "state": "Success"}]}
        ),
        home=SimpleNamespace(data={}),
        parameters=SimpleNamespace(data={"design": "gcd"}),
        design=SimpleNamespace(name="gcd"),
    )

    snapshot = create_engineering_snapshot(workspace, workspace_id="workspace-gcd")

    assert snapshot["schemaVersion"] == 4
    assert "metrics" in snapshot
    assert "metrics" not in snapshot["qorAssessment"]
    assert snapshot["analysis"]["steps"]
    layout_artifact = next(
        artifact for artifact in snapshot["artifacts"] if artifact["kind"] == "layout_image"
    )
    assert layout_artifact["integrity"] == "unverified"
    assert "sha256" not in layout_artifact
    for step in snapshot["analysis"]["steps"]:
        for field in ("metrics", "summary", "hotspots", "timingIssues"):
            value = step.get(field)
            if value is not None:
                assert value["data"] is None


def test_incremental_commit_only_reads_the_changed_step(tmp_path, monkeypatch):
    workspace = SimpleNamespace(
        directory=Path(tmp_path),
        flow=SimpleNamespace(
            data={
                "steps": [
                    {"name": "Synthesis", "tool": "ecc", "state": "Success"},
                    {"name": "Place", "tool": "ecc", "state": "Unstart"},
                ]
            }
        ),
        home=SimpleNamespace(data={}),
        parameters=SimpleNamespace(data={"design": "gcd"}),
        design=SimpleNamespace(name="gcd"),
    )
    create_engineering_snapshot(workspace, workspace_id="workspace-gcd")

    import chipcompiler.engine.analysis as analysis_module

    seen: list[str] = []
    original = analysis_module._analysis_file

    def track(path, *args, **kwargs):
        seen.append(path.as_posix())
        return original(path, *args, **kwargs)

    monkeypatch.setattr(analysis_module, "_analysis_file", track)
    committed = commit_engineering_snapshot(
        workspace,
        workspace_id="workspace-gcd",
        cause="flow_step.success",
        changed_step="Synthesis",
    )

    assert committed["workspaceRevision"] == 2
    assert seen
    assert all("Synthesis" in path for path in seen)
    assert all("Place" not in path for path in seen)


def test_incremental_commit_does_not_rebuild_full_qor_until_flow_finishes(tmp_path, monkeypatch):
    workspace = SimpleNamespace(
        directory=Path(tmp_path),
        flow=SimpleNamespace(
            data={
                "steps": [
                    {"name": "Synthesis", "tool": "ecc", "state": "Success"},
                    {"name": "Place", "tool": "ecc", "state": "Unstart"},
                ]
            }
        ),
        home=SimpleNamespace(data={}),
        parameters=SimpleNamespace(data={"design": "gcd"}),
        design=SimpleNamespace(name="gcd"),
    )
    create_engineering_snapshot(workspace, workspace_id="workspace-gcd")

    calls = []

    def track(_workspace):
        calls.append(True)
        raise AssertionError("full QoR rebuild should wait for terminal flow")

    monkeypatch.setattr("chipcompiler.analysis.qor.build_qor_analysis", track)
    committed = commit_engineering_snapshot(
        workspace,
        workspace_id="workspace-gcd",
        cause="flow_step.success",
        changed_step="Synthesis",
    )

    assert committed["qorSnapshotExtension"]["status"] == "unavailable"
    assert calls == []
