from chipcompiler.cli.inspection.artifact_evidence import inspect_artifact


def test_inspect_artifact_reports_size_and_hash(tmp_path):
    path = tmp_path / "final.gds"
    path.write_bytes(b"gds")

    result = inspect_artifact(tmp_path, "final.gds", include_hash=True)

    assert result["availability"] == "available"
    assert result["path"] == "final.gds"
    assert result["exists"] is True
    assert result["bytes"] == 3
    assert result["sha256"] == "8261e1a4f86abe76f7a1e8a66ae713e37dc9e651408b95b7db70ea062d5fc071"


def test_inspect_artifact_rejects_external_and_traversal_paths(tmp_path):
    outside = tmp_path.parent / "outside.gds"
    outside.write_bytes(b"x")

    assert inspect_artifact(tmp_path, "../outside.gds")["availability"] == "outside_workspace"
    assert inspect_artifact(tmp_path, outside)["availability"] == "outside_workspace"


def test_inspect_artifact_distinguishes_missing_and_empty(tmp_path):
    assert inspect_artifact(tmp_path, "missing.gds")["availability"] == "missing"
    (tmp_path / "empty.gds").touch()
    result = inspect_artifact(tmp_path, "empty.gds")
    assert result["availability"] == "available"
    assert result["bytes"] == 0
