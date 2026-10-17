import json
from types import SimpleNamespace

import pytest

from chipcompiler.cli import main as cli_main
from chipcompiler.engine.snapshot import create_engineering_snapshot, read_engineering_snapshot_file


@pytest.fixture
def snapshot_project(tmp_path, manifest_stubs):
    project = tmp_path / "project"
    project.mkdir()
    root = project / "baseline"
    (root / "home").mkdir(parents=True)
    workspace = SimpleNamespace(
        directory=root,
        flow=SimpleNamespace(data={"steps": []}),
        parameters=SimpleNamespace(data={"design": "gcd"}),
        design=SimpleNamespace(name="gcd"),
    )
    snapshot = create_engineering_snapshot(workspace, workspace_id="snapshot-gcd")
    manifest_stubs.write(project, [manifest_stubs.entry(project, "baseline")])
    return project, root, snapshot


def _arguments(project, output, *options):
    return ["report", "snapshot", "--project", str(project), "--output", str(output), *options]


def _files(root):
    return {
        path.relative_to(root): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }


@pytest.mark.parametrize("selector", [[], ["--workspace", "baseline"]])
def test_json_export_is_read_only_and_uses_managed_workspace(
    snapshot_project, tmp_path, monkeypatch, capsys, selector
):
    project, root, snapshot = snapshot_project
    output = tmp_path / "before.json"
    before = _files(project)

    def unexpected(*args, **kwargs):
        pytest.fail("snapshot export must not load, migrate, generate snapshots, or execute EDA")

    monkeypatch.setattr("chipcompiler.data.load_workspace", unexpected)
    monkeypatch.setattr("chipcompiler.engine.snapshot.create_engineering_snapshot", unexpected)
    monkeypatch.setattr("chipcompiler.engine.flow.EngineFlow.run_steps", unexpected)

    assert cli_main.run(_arguments(project, output, *selector, "--json")) == 0

    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == [
        {
            "report": "snapshot",
            "path": str(output),
            "source": str(root / "home" / "engineering-snapshot.json"),
            "bytes": output.stat().st_size,
            "schema_version": snapshot["schemaVersion"],
            "workspace_id": snapshot["workspaceId"],
            "workspace_revision": snapshot["workspaceRevision"],
            "status": "written",
        }
    ]
    assert read_engineering_snapshot_file(output) == snapshot
    assert _files(project) == before


@pytest.mark.parametrize("options", [[], ["--plain"]])
def test_text_and_plain_export(snapshot_project, tmp_path, options, capsys, plain_records):
    project, _root, _snapshot = snapshot_project
    output = tmp_path / "saved snapshot.json"

    assert cli_main.run(_arguments(project, output, *options)) == 0

    captured = capsys.readouterr()
    assert captured.err == ""
    if options:
        record = plain_records(captured.out)[0]
        assert record["report"] == "snapshot"
        assert record["path"] == str(output)
        assert record["status"] == "written"
    else:
        assert "snapshot" in captured.out
        assert "written" in captured.out


def test_saved_results_work_with_compare(snapshot_project, tmp_path, capsys):
    project, root, snapshot = snapshot_project
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    assert cli_main.run(_arguments(project, before, "--json")) == 0
    capsys.readouterr()
    snapshot["workspaceRevision"] += 1
    (root / "home" / "engineering-snapshot.json").write_text(json.dumps(snapshot))
    assert cli_main.run(_arguments(project, after, "--json")) == 0
    capsys.readouterr()

    assert (
        cli_main.run(
            ["compare", "run", "--baseline", str(before), "--current", str(after), "--json"]
        )
        == 0
    )

    record = json.loads(capsys.readouterr().out)[0]
    assert record["record"] == "run_comparison"
    assert record["baseline"]["workspace_revision"] == 1
    assert record["current"]["workspace_revision"] == 2


@pytest.mark.parametrize("payload", [None, "{", "[]"])
def test_invalid_snapshot_has_structured_error(snapshot_project, tmp_path, capsys, payload):
    project, root, _snapshot = snapshot_project
    source = root / "home" / "engineering-snapshot.json"
    if payload is None:
        source.unlink()
    else:
        source.write_text(payload)
    before = _files(project)
    output = tmp_path / "saved.json"

    assert cli_main.run(_arguments(project, output, "--json")) == 1

    assert json.loads(capsys.readouterr().out)[0]["error"] == "snapshot_read_failed"
    assert _files(project) == before
    assert not output.exists()


@pytest.mark.parametrize("kind", ["existing", "workspace", "missing_parent"])
def test_destination_error_is_structured(snapshot_project, tmp_path, capsys, kind):
    project, root, _snapshot = snapshot_project
    if kind == "existing":
        output = tmp_path / "saved.json"
        output.write_text("keep")
    elif kind == "workspace":
        output = root / "saved.json"
    else:
        output = tmp_path / "missing" / "saved.json"
    before = _files(project)

    assert cli_main.run(_arguments(project, output, "--json")) == 1

    error = json.loads(capsys.readouterr().out)[0]
    assert error["error"] == (
        "report_destination_exists" if kind == "existing" else "report_destination_invalid"
    )
    assert error["path"] == str(output)
    assert _files(project) == before
    if kind == "existing":
        assert output.read_text() == "keep"


def test_write_failure_is_structured(snapshot_project, tmp_path, monkeypatch, capsys):
    project, _root, _snapshot = snapshot_project
    output = tmp_path / "saved.json"

    def fail(*args, **kwargs):
        raise OSError("write denied")

    monkeypatch.setattr("chipcompiler.engine.snapshot_export.tempfile.mkstemp", fail)

    assert cli_main.run(_arguments(project, output, "--json")) == 1

    assert json.loads(capsys.readouterr().out) == [
        {
            "kind": "error",
            "error": "report_write_failed",
            "path": str(output),
            "reason": "write denied",
        }
    ]
    assert not output.exists()


@pytest.mark.parametrize("kind", ["unknown", "ambiguous", "corrupt"])
def test_manifest_errors_do_not_export(snapshot_project, tmp_path, manifest_stubs, capsys, kind):
    project, _root, _snapshot = snapshot_project
    selector = []
    expected = "workspace_not_declared"
    if kind == "unknown":
        selector = ["--workspace", "unknown"]
    elif kind == "ambiguous":
        manifest_stubs.write(
            project,
            [manifest_stubs.entry(project, "baseline"), manifest_stubs.entry(project, "candidate")],
        )
        expected = "workspace_required"
    else:
        (project / "project.json").write_text("{")
        expected = "manifest_invalid"
    output = tmp_path / "saved.json"
    before = _files(project)

    assert cli_main.run(_arguments(project, output, *selector, "--json")) == 1

    assert json.loads(capsys.readouterr().out)[0]["error"] == expected
    assert _files(project) == before
    assert not output.exists()


def test_external_workspace_selection(snapshot_project, tmp_path, manifest_stubs, capsys):
    project, root, snapshot = snapshot_project
    external = tmp_path / "external"
    root.rename(external)
    entry = manifest_stubs.entry(project, "baseline")
    entry["workspace_path"] = str(external)
    manifest_stubs.write(project, [entry])
    output = tmp_path / "saved.json"

    assert cli_main.run(_arguments(project, output, "--workspace", str(external), "--json")) == 0

    assert json.loads(capsys.readouterr().out)[0]["source"] == str(
        external / "home" / "engineering-snapshot.json"
    )
    assert read_engineering_snapshot_file(output) == snapshot


@pytest.mark.parametrize(
    ("options", "expected"),
    [([], "--output"), (["--output", "saved.json", "--plain", "--json"], "--plain")],
)
def test_invalid_cli_options_exit_two(snapshot_project, options, expected, capsys):
    project, _root, _snapshot = snapshot_project

    assert cli_main.run(["report", "snapshot", "--project", str(project), *options]) == 2

    assert expected in capsys.readouterr().err


def test_output_alias_and_relative_path(snapshot_project, tmp_path, monkeypatch, capsys):
    project, _root, snapshot = snapshot_project
    monkeypatch.chdir(tmp_path)

    assert (
        cli_main.run(
            ["report", "snapshot", "--project", str(project), "-o", "saved.json", "--json"]
        )
        == 0
    )

    assert json.loads(capsys.readouterr().out)[0]["path"] == str(tmp_path / "saved.json")
    assert read_engineering_snapshot_file(tmp_path / "saved.json") == snapshot
