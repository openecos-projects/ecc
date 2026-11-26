"""Tests for `ecc workspace create --draft` / `--preview` and draft recovery."""

import json
import os
import signal
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


def test_failed_draft_registration_keeps_the_published_workspace_for_recovery(
    fresh_project, monkeypatch, tmp_path
):
    config, manifest = (fresh_project / name for name in ("ecc.toml", "project.json"))
    original_config, original_manifest = config.read_bytes(), manifest.read_bytes()
    rtl = tmp_path / "new.v"
    rtl.write_text("module gcd(input clk); endmodule\n")
    new_rtl = fresh_project / "rtl/new.v"
    target = fresh_project / "rejected"
    target.mkdir()
    note = target / "notes.txt"

    def fail_publication(_project, _mutator):
        assert new_rtl.exists()
        assert config.read_bytes() != original_config
        note.write_text("added to the visible workspace")
        return False

    with monkeypatch.context() as failed:
        failed.setattr("chipcompiler.cli.project.draft.update_manifest_locked", fail_publication)
        assert (
            cli_main.run(
                [
                    "workspace",
                    "create",
                    str(target),
                    "--project",
                    str(fresh_project),
                    "--draft",
                    json.dumps({"rtl": [str(rtl)], "maxParallelSteps": 2}),
                ]
            )
            == 1
        )

    assert note.read_text() == "added to the visible workspace"
    assert manifest.read_bytes() == original_manifest
    assert cli_main.run(["project", "reconcile", "--project", str(fresh_project)]) == 0
    assert note.read_text() == "added to the visible workspace"
    assert new_rtl.read_bytes() == rtl.read_bytes()
    assert [entry["workspace_id"] for entry in json.loads(manifest.read_text())["workspaces"]] == [
        target.name
    ]


def test_config_edit_serializes_with_draft_publication(
    fresh_project, monkeypatch, tmp_path, minimal_ics55_pdk_factory
):
    import tomllib

    from chipcompiler.cli.command_handlers import pdk

    config = fresh_project / "ecc.toml"
    other_pdk = minimal_ics55_pdk_factory(tmp_path / "other-pdk")
    committing, edit_started, release = Event(), Event(), Event()
    replace = Path.replace
    set_root = pdk._write_pdk_root

    def pause_config_commit(path, target):
        if path.name == "ecc.toml.next" and target == config:
            committing.set()
            assert release.wait(10)
        return replace(path, target)

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

    monkeypatch.setattr(Path, "replace", pause_config_commit)
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


@pytest.mark.parametrize(
    ("user_change", "registration_fails_once"),
    [
        (None, False),
        ("content", False),
        (None, True),
        ("netlist", False),
        ("golden_netlist", False),
        ("manifest_netlist", False),
        ("malformed_config", False),
        ("invalid_encoding", False),
    ],
)
def test_recovery_records_skipped_project_changes_after_partial_rtl_publication(
    fresh_project, monkeypatch, tmp_path, capsys, user_change, registration_fails_once
):
    target = fresh_project / "draft"
    files = [tmp_path / "first.v", tmp_path / "second.v"]
    for source, module in zip(files, ("gcd", "other"), strict=True):
        source.write_text(f"module {module}; endmodule\n")
    first, second = (fresh_project / "rtl" / source.name for source in files)
    args = [
        "workspace",
        "create",
        target.name,
        "--project",
        str(fresh_project),
        "--draft",
        json.dumps({"rtl": [str(source) for source in files]}),
        "--command-id",
        "partial-import",
        "--json",
    ]
    link = Path.hardlink_to

    def stop_after_first(path, source):
        link(path, source)
        if path == first:
            os.kill(os.getpid(), signal.SIGKILL)

    with monkeypatch.context() as child:
        child.setattr(Path, "hardlink_to", stop_after_first)
        pid = os.fork()
        if pid == 0:
            try:
                cli_main.run(args)
            finally:
                os._exit(1)
        _, status = os.waitpid(pid, 0)
        assert os.WIFSIGNALED(status) and os.WTERMSIG(status) == signal.SIGKILL

    assert first.is_file()
    second.write_text("user-owned second file")
    config = fresh_project / "ecc.toml"
    manifest = fresh_project / "project.json"
    if user_change == "manifest_netlist":
        document = json.loads(manifest.read_text())
        document["base_design"]["netlist"] = "rtl/first.v"
        manifest.write_text(json.dumps(document))
    elif user_change in {"malformed_config", "invalid_encoding"}:
        original = config.read_bytes()
        invalid = original + (b"\n[\n" if user_change == "malformed_config" else b"\xff")
        config.write_bytes(invalid)
        expected_manifest = manifest.read_bytes()
        journal = fresh_project / ".workspace-draft-publish.json"
        expected_journal = journal.read_bytes()
        capsys.readouterr()
        assert (
            cli_main.run(["project", "reconcile", "--project", str(fresh_project), "--plain"]) == 1
        )
        assert "error=invalid_project_config" in capsys.readouterr().out
        assert config.read_bytes() == invalid
        assert manifest.read_bytes() == expected_manifest
        assert journal.read_bytes() == expected_journal
        assert first.read_bytes() == files[0].read_bytes()
        config.write_bytes(original)
    elif user_change == "content":
        first.write_text("user edit to the first file")
    elif user_change:
        # Resolve declarations the same way the flow does, including environment variables.
        monkeypatch.setenv("ECC_TEST_IMPORT_DIR", str(first.parent))
        assert (
            cli_main.run(
                [
                    "project",
                    "set",
                    f"design.{user_change}",
                    "$ECC_TEST_IMPORT_DIR/first.v",
                    "--project",
                    str(fresh_project),
                ]
            )
            == 0
        )
    expected_config = config.read_bytes()
    if registration_fails_once:
        with monkeypatch.context() as failed:
            failed.setattr(
                "chipcompiler.cli.project.draft.update_manifest_locked", lambda *_: False
            )
            assert cli_main.run(["project", "reconcile", "--project", str(fresh_project)]) == 1
        second.unlink()
    for _ in range(2):
        assert cli_main.run(["project", "reconcile", "--project", str(fresh_project)]) == 0
    assert (target / "home" / "flow.json").is_file()
    assert config.read_bytes() == expected_config
    if registration_fails_once:
        assert not second.exists()
    else:
        assert second.read_text() == "user-owned second file"
    if user_change == "content":
        assert first.read_text() == "user edit to the first file"
    elif user_change in {"netlist", "golden_netlist", "manifest_netlist"}:
        assert first.read_bytes() == files[0].read_bytes()
    else:
        assert not first.exists()
    if user_change == "manifest_netlist":
        assert json.loads(manifest.read_text())["base_design"]["netlist"] == "rtl/first.v"

    capsys.readouterr()
    assert cli_main.run(args) == 1
    (record,) = json.loads(capsys.readouterr().out)
    assert record["error"] == "workspace_draft_project_changes_skipped"
    assert record["workspace_created"] is True


@pytest.mark.parametrize("when", ["before_build", "before_link", "after_crash"])
def test_draft_rtl_parent_conflict_does_not_block_the_project(
    fresh_project, monkeypatch, tmp_path, capsys, when
):
    source_dir = tmp_path / "sources"
    (source_dir / "nested").mkdir(parents=True)
    (source_dir / "nested/top.v").write_text("module gcd; endmodule\n")
    filelist = source_dir / "draft.f"
    filelist.write_text("nested/top.v\n")
    parent = fresh_project / "rtl/nested"
    first = fresh_project / "rtl/draft.f"
    args = [
        "workspace",
        "create",
        "nested",
        "--project",
        str(fresh_project),
        "--draft",
        json.dumps({"filelist": str(filelist), "maxParallelSteps": 2}),
        "--command-id",
        "parent-conflict",
        "--json",
    ]
    original = (fresh_project / "ecc.toml").read_bytes()
    link = Path.hardlink_to

    def occupy_parent():
        parent.parent.mkdir(exist_ok=True)
        parent.write_text("user-owned file")

    def link_and_interrupt(path, source):
        link(path, source)
        if path == first:
            if when == "after_crash":
                os.kill(os.getpid(), signal.SIGKILL)
            else:
                occupy_parent()

    capsys.readouterr()
    if when == "before_build":
        occupy_parent()
        assert cli_main.run(args) == 1
        assert not (fresh_project / "nested").exists()
    elif when == "before_link":
        with monkeypatch.context() as child:
            child.setattr(Path, "hardlink_to", link_and_interrupt)
            assert cli_main.run(args) == 1
        assert (fresh_project / "nested/home/flow.json").is_file()
        assert "workspace_draft_project_changes_skipped" in capsys.readouterr().out
    else:
        with monkeypatch.context() as child:
            child.setattr(Path, "hardlink_to", link_and_interrupt)
            pid = os.fork()
            if pid == 0:
                try:
                    cli_main.run(args)
                finally:
                    os._exit(1)
            _, status = os.waitpid(pid, 0)
            assert os.WIFSIGNALED(status) and os.WTERMSIG(status) == signal.SIGKILL
        assert first.is_file()
        occupy_parent()
        assert cli_main.run(["project", "reconcile", "--project", str(fresh_project)]) == 0
        assert (fresh_project / "nested/home/flow.json").is_file()

    assert not first.exists()
    assert not (fresh_project / ".workspace-draft-publish.json").exists()
    assert parent.read_text() == "user-owned file"
    assert (fresh_project / "ecc.toml").read_bytes() == original
    assert (
        cli_main.run(
            ["workspace", "create", "next", "--project", str(fresh_project), "--draft", "{}"]
        )
        == 0
    )


@pytest.mark.parametrize(
    ("registered", "edit_after_crash"),
    [(False, None), (True, None), (False, "set"), (False, "restore")],
)
def test_killed_draft_publication_is_recovered(
    fresh_project, monkeypatch, tmp_path, registered, edit_after_crash
):
    from chipcompiler.cli.project import draft

    rtl = tmp_path / "new.v"
    rtl.write_text("module gcd(input clk); endmodule\n")
    config = fresh_project / "ecc.toml"
    original_config = config.read_bytes()
    update = draft.update_manifest_locked

    def kill_publication(project, mutate):
        if registered:
            assert update(project, mutate)
        os.kill(os.getpid(), signal.SIGKILL)

    with monkeypatch.context() as child:
        child.setattr(draft, "update_manifest_locked", kill_publication)
        pid = os.fork()
        if pid == 0:
            try:
                cli_main.run(
                    [
                        "workspace",
                        "create",
                        "interrupted",
                        "--project",
                        str(fresh_project),
                        "--draft",
                        json.dumps({"rtl": [str(rtl)], "maxParallelSteps": 2}),
                    ]
                )
            finally:
                os._exit(1)
        _, status = os.waitpid(pid, 0)
        assert os.WIFSIGNALED(status) and os.WTERMSIG(status) == signal.SIGKILL

    assert config.read_bytes() != original_config
    if edit_after_crash == "set":
        assert (
            cli_main.run(
                ["project", "set", "design.frequency_mhz", "99", "--project", str(fresh_project)]
            )
            == 0
        )
    elif edit_after_crash == "restore":
        config.write_bytes(original_config)
    expected_config = config.read_bytes()
    for _ in range(2):
        assert cli_main.run(["project", "reconcile", "--project", str(fresh_project)]) == 0
    assert config.read_bytes() == expected_config
    manifest = json.loads((fresh_project / "project.json").read_text())
    assert [item["workspace_id"] for item in manifest["workspaces"]] == ["interrupted"]
    assert (fresh_project / "rtl" / "new.v").read_bytes() == rtl.read_bytes()


def test_reconcile_discards_unpublished_draft_if_target_was_populated(
    fresh_project, monkeypatch, capsys
):
    from chipcompiler.cli.project import draft

    target = fresh_project / "interrupted"
    target.mkdir()
    args = [
        "workspace",
        "create",
        str(target),
        "--project",
        str(fresh_project),
        "--draft",
        '{"maxParallelSteps":2}',
    ]
    config = fresh_project / "ecc.toml"
    original_config = config.read_bytes()
    write = draft.write_text_atomic

    def kill_after_journal(path, text):
        write(path, text)
        if path == fresh_project / ".workspace-draft-publish.json":
            os.kill(os.getpid(), signal.SIGKILL)

    with monkeypatch.context() as child:
        child.setattr(draft, "write_text_atomic", kill_after_journal)
        pid = os.fork()
        if pid == 0:
            try:
                cli_main.run(args)
            finally:
                os._exit(1)
        _, status = os.waitpid(pid, 0)
        assert os.WIFSIGNALED(status) and os.WTERMSIG(status) == signal.SIGKILL

    assert not list(target.iterdir())
    capsys.readouterr()
    assert (
        cli_main.run(
            ["run", "--workspace", str(target), "--project", str(fresh_project), "--plain"]
        )
        == 1
    )
    assert "error=workspace_draft_pending" in capsys.readouterr().out

    note = target / "notes.txt"
    note.write_text("added after workspace creation stopped")
    assert cli_main.run(["project", "reconcile", "--project", str(fresh_project)]) == 0
    assert config.read_bytes() == original_config
    assert note.read_text() == "added after workspace creation stopped"
    assert not (fresh_project / ".workspace-draft-publish.json").exists()
    note.unlink()
    assert cli_main.run(args) == 0


@pytest.mark.parametrize(
    ("reuse_empty", "add_user_file"), [(False, False), (True, False), (True, True)]
)
def test_killed_draft_build_is_discarded_and_can_be_retried(
    fresh_project, monkeypatch, reuse_empty, add_user_file
):
    from chipcompiler.cli.project.draft import CreationDraft

    target = fresh_project / "interrupted"
    selector = str(target) if reuse_empty else target.name
    if reuse_empty:
        target.mkdir()
    args = [
        "workspace",
        "create",
        selector,
        "--project",
        str(fresh_project),
        "--draft",
        json.dumps({"maxParallelSteps": 2}),
        "--command-id",
        "interrupted-build",
    ]
    config = fresh_project / "ecc.toml"
    original = config.read_bytes()

    def kill_before_publication(*_args, **_kwargs):
        os.kill(os.getpid(), signal.SIGKILL)

    with monkeypatch.context() as child:
        child.setattr(CreationDraft, "publish", kill_before_publication)
        pid = os.fork()
        if pid == 0:
            try:
                cli_main.run(args)
            finally:
                os._exit(1)
        _, status = os.waitpid(pid, 0)
        assert os.WIFSIGNALED(status) and os.WTERMSIG(status) == signal.SIGKILL

    notes = target / "notes.txt"
    if add_user_file:
        notes.write_text("written after the crash")
    assert cli_main.run(["project", "reconcile", "--project", str(fresh_project)]) == 0
    assert target.exists() == reuse_empty
    assert config.read_bytes() == original
    if add_user_file:
        assert notes.read_text() == "written after the crash"
        notes.unlink()
    assert not reuse_empty or not list(target.iterdir())
    assert cli_main.run(args) == 0
    assert (target / "home" / "flow.json").is_file()


def test_draft_no_wait_does_not_block_during_publication_or_cleanup(fresh_project, monkeypatch):
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
