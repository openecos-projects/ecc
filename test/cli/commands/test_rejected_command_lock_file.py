"""A command rejected by workspace selection must not leave a lock file (#419)."""

from pathlib import Path

import pytest

from chipcompiler.cli import main as cli_main


@pytest.fixture
def manifest_project(create_cli_project, manifest_stubs):
    """A manifest project that declares one workspace, ``baseline``."""
    project = Path(create_cli_project())
    manifest_stubs.write(project, [manifest_stubs.entry(project, "baseline")])
    return project


def _lock_files(project: Path) -> list[str]:
    return sorted(path.name for path in project.glob("*.lock"))


def _handoff(tmp_path: Path) -> str:
    handoff = tmp_path / "macro_location.tcl"
    handoff.write_text("placeInstance u0 1.0 2.0 R0\n")
    return str(handoff)


def test_macro_import_into_undeclared_workspace_leaves_no_lock_file(
    capsys, manifest_project, plain_records, tmp_path
):
    before = _lock_files(manifest_project)

    rc = cli_main.run(
        [
            "macro",
            "import",
            _handoff(tmp_path),
            "--project",
            str(manifest_project),
            "--workspace",
            "nosuch",
            "--plain",
        ]
    )

    assert rc == 1
    assert plain_records(capsys.readouterr().out)[0]["error"] == "workspace_not_declared"
    assert _lock_files(manifest_project) == before


def test_signoff_export_from_undeclared_workspace_leaves_no_lock_file(
    capsys, manifest_project, plain_records, tmp_path
):
    before = _lock_files(manifest_project)

    rc = cli_main.run(
        [
            "signoff",
            "export",
            "-o",
            str(tmp_path / "pkg.tar.gz"),
            "--project",
            str(manifest_project),
            "--workspace",
            "nosuch",
            "--plain",
        ]
    )

    assert rc == 1
    assert plain_records(capsys.readouterr().out)[0]["error"] == "workspace_not_declared"
    assert _lock_files(manifest_project) == before


def test_signoff_export_without_selectable_workspace_leaves_no_lock_file(
    capsys, manifest_project, manifest_stubs, plain_records, tmp_path
):
    manifest_stubs.write(
        manifest_project,
        [
            manifest_stubs.entry(manifest_project, "baseline"),
            manifest_stubs.entry(manifest_project, "second"),
        ],
    )
    before = _lock_files(manifest_project)

    rc = cli_main.run(
        [
            "signoff",
            "export",
            "-o",
            str(tmp_path / "pkg.tar.gz"),
            "--project",
            str(manifest_project),
            "--plain",
        ]
    )

    assert rc == 1
    assert plain_records(capsys.readouterr().out)[0]["error"] == "workspace_required"
    assert _lock_files(manifest_project) == before


@pytest.mark.parametrize("command", ["macro-import", "signoff-export"])
def test_corrupt_manifest_leaves_no_lock_file(
    capsys, manifest_project, plain_records, tmp_path, command
):
    (manifest_project / "project.json").write_text("{not-json")
    before = _lock_files(manifest_project)
    arguments = {
        "macro-import": ["macro", "import", _handoff(tmp_path)],
        "signoff-export": ["signoff", "export", "-o", str(tmp_path / "pkg.tar.gz")],
    }[command]

    rc = cli_main.run(
        [*arguments, "--project", str(manifest_project), "--workspace", "baseline", "--plain"]
    )

    assert rc == 1
    assert plain_records(capsys.readouterr().out)[0]["error"] == "manifest_invalid"
    assert _lock_files(manifest_project) == before
