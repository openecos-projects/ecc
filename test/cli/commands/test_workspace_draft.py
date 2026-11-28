"""Tests for `ecc workspace create --draft` and `--preview`."""

import json
from multiprocessing import Event, Process
from pathlib import Path

import pytest

from chipcompiler.cli import main as cli_main


def test_workspace_preview_create_and_retry_use_one_draft(fresh_project, capsys):
    import tomllib

    from chipcompiler.cli.project.toml_edit import set_scoped_key

    path = fresh_project / "ecc.toml"
    path.write_text(set_scoped_key(path.read_text(), "flow", "insert_steps", ["lec@synthesis"]))
    original_config = path.read_bytes()
    original_manifest = (fresh_project / "project.json").read_bytes()
    draft = json.dumps({"remove": ["lec@synthesis"], "maxParallelSteps": 3})
    args = [
        "workspace",
        "create",
        "draft",
        "--project",
        str(fresh_project),
        "--from",
        "synthesis",
        "--to",
        "pre_floorplan",
        "--draft",
        draft,
        "--command-id",
        "draft-test",
        "--json",
    ]
    capsys.readouterr()
    assert cli_main.run([*args, "--preview"]) == 0
    preview = json.loads(capsys.readouterr().out)[0]
    assert preview == {
        "record": "workspace_preview",
        "steps": ["synthesis", "pre_floorplan"],
        "max_parallel_steps": 3,
    }
    assert path.read_bytes() == original_config
    assert (fresh_project / "project.json").read_bytes() == original_manifest
    assert not (fresh_project / "draft").exists()

    assert cli_main.run(args) == 0
    flow = json.loads((fresh_project / "draft" / "home" / "flow.json").read_text())
    assert [step["name"] for step in flow["steps"]] == preview["steps"]
    config = tomllib.loads(path.read_text())["flow"]
    assert (config["insert_steps"], config["max_parallel_steps"]) == ([], 3)
    assert cli_main.run(args) == 0


def test_config_edit_serializes_with_draft_publication(
    fresh_project, monkeypatch, tmp_path, minimal_ics55_pdk_factory
):
    import tomllib

    from chipcompiler.cli.command_handlers import pdk
    from chipcompiler.cli.project import draft as draft_module

    config = fresh_project / "ecc.toml"
    other_pdk = minimal_ics55_pdk_factory(tmp_path / "other-pdk")
    committing, edit_started, release = Event(), Event(), Event()
    write_atomic = draft_module.write_text_atomic
    set_root = pdk._write_pdk_root

    def pause_config_commit(path, text):
        if Path(path) == config:
            committing.set()
            assert release.wait(10)
        return write_atomic(path, text)

    def start_pdk_write(*args):
        edit_started.set()
        set_root(*args)

    def create():
        raise SystemExit(
            cli_main.run(
                [
                    "workspace",
                    "create",
                    "draft",
                    "--project",
                    str(fresh_project),
                    "--draft",
                    '{"maxParallelSteps":2}',
                ]
            )
        )

    def edit():
        raise SystemExit(
            cli_main.run(
                [
                    "pdk",
                    "set-root",
                    str(other_pdk),
                    "--project",
                    str(fresh_project),
                ]
            )
        )

    monkeypatch.setattr(draft_module, "write_text_atomic", pause_config_commit)
    monkeypatch.setattr(pdk, "_write_pdk_root", start_pdk_write)
    creator, editor = Process(target=create), Process(target=edit)
    creator.start()
    try:
        assert committing.wait(10)
        editor.start()
        assert edit_started.wait(10)
        editor.join(0.5)
    finally:
        release.set()
        creator.join(10)
        if editor.pid is not None:
            editor.join(10)
    assert creator.exitcode == editor.exitcode == 0
    data = tomllib.loads(config.read_text())
    assert data["pdk"]["root"] == str(other_pdk)
    assert data["flow"]["max_parallel_steps"] == 2


def test_draft_no_wait_does_not_block_during_publication(fresh_project, monkeypatch):
    from chipcompiler.cli.project.draft import CreationDraft
    from chipcompiler.project.manifest_write import manifest_lock

    before_publish, locked, release = Event(), Event(), Event()
    publish = CreationDraft.publish

    def publish_while_contended(self, *args, **kwargs):
        before_publish.set()
        assert locked.wait(10)
        return publish(self, *args, **kwargs)

    def hold_manifest_lock():
        assert before_publish.wait(10)
        with manifest_lock(fresh_project):
            locked.set()
            assert release.wait(10)

    def create():
        raise SystemExit(
            cli_main.run(
                [
                    "workspace",
                    "create",
                    "contended",
                    "--project",
                    str(fresh_project),
                    "--draft",
                    "{}",
                    "--no-wait",
                ]
            )
        )

    monkeypatch.setattr(CreationDraft, "publish", publish_while_contended)
    holder, worker = Process(target=hold_manifest_lock), Process(target=create)
    holder.start()
    worker.start()
    try:
        assert locked.wait(10)
        worker.join(3)
        assert worker.exitcode == 20
        assert not (fresh_project / "contended").exists()
    finally:
        release.set()
        holder.join(10)
        worker.join(10)


def test_published_draft_can_refresh_until_a_managed_file_is_edited(fresh_project, capsys):
    project = ["--project", str(fresh_project), "--plain"]
    assert cli_main.run(["workspace", "create", "draft", "--draft", "{}", *project]) == 0
    refresh = ["workspace", "refresh", "draft", *project]
    assert cli_main.run(refresh) == 0
    config = fresh_project / "draft" / "config" / "db_ecc.json"
    config.write_text(config.read_text() + "\n")
    capsys.readouterr()
    assert cli_main.run(refresh) == 1
    message = capsys.readouterr().out
    assert "derived_configs_modified" in message
    assert "files=db_ecc.json" in message


def test_unrecorded_config_baseline_cannot_be_published(fresh_project, monkeypatch, capsys):
    args = [
        "workspace",
        "create",
        "draft",
        "--draft",
        '{"maxParallelSteps":2}',
        "--project",
        str(fresh_project),
        "--plain",
    ]
    files = [fresh_project / name for name in ("ecc.toml", "project.json")]
    before = [path.read_bytes() for path in files]
    with monkeypatch.context() as failed:
        failed.setattr(
            "chipcompiler.data.workspace.config_manifest.record_derived_config",
            lambda _workspace: False,
        )
        assert cli_main.run(args) == 1
    assert "error=workspace_failed" in capsys.readouterr().out
    assert [path.read_bytes() for path in files] == before
    assert not (fresh_project / "draft").exists()
    assert cli_main.run(args) == 0


def test_draft_duplicate_rtl_basenames_fail_cleanly_in_preview_and_create(
    fresh_project, tmp_path, capsys
):
    left = tmp_path / "left" / "top.v"
    right = tmp_path / "right" / "top.v"
    left.parent.mkdir()
    right.parent.mkdir()
    left.write_text("module gcd; endmodule\n")
    right.write_text("module gcd; endmodule\n")
    args = [
        "workspace",
        "create",
        "draft",
        "--project",
        str(fresh_project),
        "--draft",
        json.dumps({"rtl": [str(left), str(right)]}),
        "--json",
    ]

    for extra in (["--preview"], []):
        capsys.readouterr()
        assert cli_main.run([*args, *extra]) == 1
        (record,) = json.loads(capsys.readouterr().out)
        assert record["kind"] == "error"
        assert record["error"] == "rtl_target_collision"
        assert not (fresh_project / "draft").exists()


def test_workspace_preview_rejects_occupied_target_like_create(fresh_project, capsys):
    occupied = fresh_project / "occupied"
    occupied.mkdir()
    (occupied / "notes.txt").write_text("existing user note\n")

    for selector in (occupied.name, str(occupied)):
        args = [
            "workspace",
            "create",
            selector,
            "--project",
            str(fresh_project),
            "--draft",
            "{}",
            "--json",
        ]
        for extra in (["--preview"], []):
            capsys.readouterr()
            assert cli_main.run([*args, *extra]) == 1
            (record,) = json.loads(capsys.readouterr().out)
            assert record["kind"] == "error"
            assert record["error"] == "run_exists"

    empty = fresh_project / "empty_explicit"
    empty.mkdir()
    capsys.readouterr()
    assert (
        cli_main.run(
            [
                "workspace",
                "create",
                str(empty),
                "--project",
                str(fresh_project),
                "--draft",
                "{}",
                "--preview",
                "--json",
            ]
        )
        == 0
    )
    (preview,) = json.loads(capsys.readouterr().out)
    assert preview["record"] == "workspace_preview"


@pytest.mark.parametrize("import_rtl", [False, True])
def test_draft_via_project_symlink_can_publish_and_retry(fresh_project, tmp_path, import_rtl):
    alias = tmp_path / "project-link"
    alias.symlink_to(fresh_project, target_is_directory=True)
    rtl = tmp_path / "top.v"
    rtl.write_text("module gcd; endmodule\n")
    args = [
        "workspace",
        "create",
        "draft",
        "--draft",
        json.dumps({"rtl": [str(rtl)]} if import_rtl else {}),
        "--command-id",
        "linked-project",
        "--project",
    ]
    assert cli_main.run([*args, str(alias), "--preview"]) == 0
    assert cli_main.run([*args, str(alias)]) == 0
    assert (fresh_project / "draft/home/flow.json").is_file()
    if import_rtl:
        assert (fresh_project / "rtl/top.v").read_bytes() == rtl.read_bytes()
    assert cli_main.run([*args, str(fresh_project)]) == 0


@pytest.mark.parametrize("explicit", [False, True])
def test_draft_workspace_symlink_is_rejected(fresh_project, explicit):
    empty = fresh_project / "empty"
    empty.mkdir()
    link = fresh_project / "linked"
    link.symlink_to(empty, target_is_directory=True)
    args = [
        "workspace",
        "create",
        str(link) if explicit else link.name,
        "--draft",
        "{}",
        "--project",
        str(fresh_project),
    ]
    assert cli_main.run([*args, "--preview"]) == 1
    assert cli_main.run(args) == 1
    assert link.is_symlink() and list(empty.iterdir()) == []


@pytest.mark.parametrize("occupied", ["file", "parent", "same_source"])
def test_draft_rtl_preview_reports_same_conflict_as_create(
    fresh_project, tmp_path, capsys, occupied
):
    source = tmp_path / "top.v"
    source.write_text("module gcd; endmodule\n")
    target = fresh_project / "rtl/top.v"
    conflict = target.parent if occupied == "parent" else target
    conflict.parent.mkdir(exist_ok=True)
    if occupied == "same_source":
        conflict.hardlink_to(source)
    else:
        conflict.write_text("existing project input\n")
    args = [
        "workspace",
        "create",
        "draft",
        "--project",
        str(fresh_project),
        "--draft",
        json.dumps({"rtl": [str(source)]}),
        "--json",
    ]
    capsys.readouterr()
    assert cli_main.run([*args, "--preview"]) == 1
    (preview,) = json.loads(capsys.readouterr().out)
    assert cli_main.run(args) == 1
    (creation,) = json.loads(capsys.readouterr().out)
    assert creation == preview
    assert creation["error"] == "run_exists"
    assert str(conflict) in creation["reason"]
    assert conflict.read_text() == (
        source.read_text() if occupied == "same_source" else "existing project input\n"
    )
    assert not (fresh_project / "draft").exists()
