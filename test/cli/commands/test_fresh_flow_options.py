"""A freshly built ledger carries the options projection (#424).

`EngineFlow.add_step` saves the ledger with its steps only. The fresh-run
path therefore writes the options projection once the ledger is complete;
otherwise the first workspace load, even from a query, rewrites flow.json.
"""

import json
import os
import signal
from multiprocessing import Event, Process

import pytest

from chipcompiler.cli import main as cli_main
from chipcompiler.data import load_workspace
from chipcompiler.engine import EngineFlow


class LedgerOnlyFlow(EngineFlow):
    """The real flow ledger, without step workspaces or tool execution."""

    def create_step_workspaces(self, **_kwargs):
        self.workspace_steps = list(self.workspace.flow.data.get("steps", []))

    def run_steps(self, **_kwargs):
        return True


@pytest.fixture
def fresh_project(tmp_path, monkeypatch, minimal_ics55_pdk_factory):
    """A project whose fresh runs build a real workspace and a real ledger."""
    monkeypatch.setattr("chipcompiler.engine.EngineFlow", LedgerOnlyFlow)
    monkeypatch.setattr(
        "chipcompiler.rtl2gds.builder.build_rtl2gds_flow",
        lambda *, skip=(), lec_engine=None: [
            ("synthesis", "yosys", "Unstart"),
            ("pre_floorplan", "ecc", "Unstart"),
            ("placement", "dreamplace", "Unstart"),
        ],
    )
    monkeypatch.setattr(
        "chipcompiler.cli.project.config._validate_pdk_contents",
        lambda name, root, overrides=None: None,
    )
    project = tmp_path / "project"
    assert cli_main.run(["init", str(project), "--design-name", "gcd"]) == 0
    pdk = minimal_ics55_pdk_factory(tmp_path / "pdk")
    (project / "gcd.v").write_text("module gcd(input clk); endmodule\n")
    assert cli_main.run(["project", "set", "design.rtl", "gcd.v", "--project", str(project)]) == 0
    config = project / "ecc.toml"
    config.write_text(config.read_text().replace('root = ""', f'root = "{pdk}"'))
    return project


@pytest.mark.parametrize(
    "command",
    [
        pytest.param(["run", "--workspace", "fresh"], id="run"),
        pytest.param(["workspace", "create", "fresh"], id="workspace-create"),
    ],
)
def test_fresh_workspace_ledger_carries_the_options_projection(fresh_project, command):
    assert cli_main.run([*command, "--project", str(fresh_project)]) == 0

    # Read the file as the command left it: nothing has loaded the workspace yet.
    flow_json = fresh_project / "fresh" / "home" / "flow.json"
    persisted = flow_json.read_bytes()
    assert json.loads(persisted)["options"] == {"geometry": {"clock_tree": False}}

    assert load_workspace(fresh_project / "fresh") is not None
    assert flow_json.read_bytes() == persisted


def test_fresh_run_requests_one_persisted_projection(create_cli_project, flow_mocks):
    assert cli_main.run(["run", "--project", create_cli_project()]) == 0

    assert flow_mocks.capture["options_projections"] == [{"persist": True}]


def test_workspace_flow_plan_reads_the_selected_ledger(fresh_project, capsys):
    assert cli_main.run(["workspace", "create", "trimmed", "--project", str(fresh_project)]) == 0
    assert cli_main.run(["workspace", "create", "other", "--project", str(fresh_project)]) == 0
    flow_json = fresh_project / "trimmed" / "home" / "flow.json"
    info = json.loads(flow_json.read_text())
    info["steps"] = [
        {"name": "filler", "tool": "ecc", "category": "PNR"},
        {"name": "rcx", "tool": "ecc", "category": "CHECKER"},
        {"name": "drc", "tool": "ecc", "category": "CHECKER", "input_step": "rcx"},
    ]
    for index, step in enumerate(info["steps"]):
        step.update(state="Unstart", directory=f"{index}_{step['name']}")
    flow_json.write_text(json.dumps(info))
    original = flow_json.read_bytes()
    capsys.readouterr()

    assert (
        cli_main.run(["flow", "workspace", "trimmed", "--project", str(fresh_project), "--json"])
        == 0
    )
    header, *steps = json.loads(capsys.readouterr().out)
    assert header["workspace_id"] == "trimmed"
    assert [(row["step"], row["stage"], row["design_source"]) for row in steps] == [
        ("filler", 1, None),
        ("rcx", 2, "filler"),
        ("drc", 3, "rcx"),
    ]
    assert steps[1]["needs"]["filled"] == "filler"
    assert flow_json.read_bytes() == original


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


def test_failed_draft_publication_rolls_back_project_config_and_rtl(
    fresh_project, monkeypatch, tmp_path
):
    config, manifest = (fresh_project / name for name in ("ecc.toml", "project.json"))
    original_config, original_manifest = config.read_bytes(), manifest.read_bytes()
    rtl = tmp_path / "new.v"
    rtl.write_text("module gcd(input clk); endmodule\n")
    new_rtl = fresh_project / "rtl/new.v"

    def fail_publication(_project, _mutator):
        assert new_rtl.exists()
        assert config.read_bytes() != original_config
        return False

    monkeypatch.setattr("chipcompiler.cli.project.draft.update_manifest_locked", fail_publication)
    assert (
        cli_main.run(
            [
                "workspace",
                "create",
                "rejected",
                "--project",
                str(fresh_project),
                "--draft",
                json.dumps({"rtl": [str(rtl)], "maxParallelSteps": 2}),
            ]
        )
        != 0
    )
    assert config.read_bytes() == original_config
    assert manifest.read_bytes() == original_manifest
    assert not new_rtl.exists()
    assert not (fresh_project / "rejected").exists()


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
