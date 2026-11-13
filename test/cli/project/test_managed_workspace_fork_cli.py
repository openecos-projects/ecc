"""Real CLI forks preserve the selected output and managed identity."""

import gzip
import json
from pathlib import Path

import pytest

from chipcompiler.cli import main as cli_main
from chipcompiler.data import EccStep, load_workspace
from chipcompiler.engine import create_workspace_from_spec
from chipcompiler.engine.snapshot import (
    create_engineering_snapshot,
    read_engineering_snapshot_from_directory,
)
from chipcompiler.engine.workspace_reset import build_flow_for_workspace
from chipcompiler.project import load_project_manifest, mutate_project_manifest


@pytest.fixture
def completed_source(tmp_path, minimal_ics55_pdk_factory):
    project = tmp_path / "project"
    assert cli_main.run(["init", str(project), "--design-name", "gcd"]) == 0
    fixture = Path(__file__).parents[2] / "fixtures" / "workspace_spec" / "valid.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    bindings = payload["workspaceBindings"]
    bindings["inputs"] = {
        key: str(fixture.parent / value) for key, value in bindings["inputs"].items()
    }
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    source = project / "source"
    workspace = create_workspace_from_spec(source, payload["workspaceSpec"], bindings)
    flow = build_flow_for_workspace(workspace)
    for record in workspace.flow.steps():
        record["state"] = "Success"
    assert flow.save()
    for step in flow.workspace_steps:
        (step.output.dir / "retained-output").write_text(step.name, encoding="utf-8")
        if step.output.verilog is not None:
            step.output.verilog.write_bytes(
                gzip.compress(f"// {step.name}\nmodule gcd(); endmodule\n".encode())
            )
        if step.output.def_ is not None:
            step.output.def_.write_bytes(gzip.compress(f"# {step.name}\nVERSION 5.8 ;\n".encode()))
    create_engineering_snapshot(workspace, workspace_id="source")
    mutate_project_manifest(
        project,
        {
            "type": "register_workspace",
            "workspace_id": "source",
            "workspace_path": str(source),
        },
    )
    return project, source, flow.workspace_steps


@pytest.mark.parametrize("continuation", ["preFloorplan", "floorplan"])
# ECOS Studio's pinned runtime integration still runs the former name.
@pytest.mark.parametrize("name", ["fork", "derive"])
def test_cli_fork_can_open_preserves_outputs_and_retries(completed_source, continuation, name):
    project, source, steps = completed_source
    before = {
        path.relative_to(source): path.read_bytes()
        for directory in ("home", "config")
        for path in (source / directory).rglob("*")
        if path.is_file()
    }
    command = [
        "workspace",
        name,
        "source",
        "branch",
        "--project",
        str(project),
        "--from",
        continuation,
        "--command-id",
        "fork-1",
        "--no-wait",
        "--plain",
    ]
    assert cli_main.run(command) == 0
    target = project / "branch"
    snapshot = read_engineering_snapshot_from_directory(target)
    assert (snapshot["workspaceId"], snapshot["workspaceRevision"]) == ("branch", 1)
    assert str(source) not in json.dumps(snapshot)
    synthesis_netlist = steps[0].output.verilog.relative_to(source)
    assert (target / synthesis_netlist).read_bytes() == (source / synthesis_netlist).read_bytes()
    assert [step["state"] for step in snapshot["flow"]["steps"]] == [
        "Success",
        *["Unstart"] * (len(steps) - 1),
    ]
    for index, step in enumerate(steps):
        relative = step.output.dir.relative_to(source) / "retained-output"
        assert (target / relative).exists() == (index == 0)
        assert (source / relative).read_text(encoding="utf-8") == step.name
    assert all((source / path).read_bytes() == content for path, content in before.items())
    assert cli_main.run(command) == 0
    assert read_engineering_snapshot_from_directory(target) == snapshot
    manifest = load_project_manifest(project)
    assert [entry["workspace_id"] for entry in manifest["workspaces"]] == ["source", "branch"]


def test_cli_fork_and_batch_parameters_keep_identity_and_source(completed_source):
    project, source, _steps = completed_source
    before = read_engineering_snapshot_from_directory(source)
    assert (
        cli_main.run(
            [
                "workspace",
                "fork",
                "source",
                "branch",
                "--project",
                str(project),
                "--from",
                "sta",
                "--plain",
            ]
        )
        == 0
    )
    assert (
        cli_main.run(
            [
                "param",
                "apply",
                "--project",
                str(project),
                "--workspace",
                "branch",
                "--set",
                "sta.max_parallel_corners=13",
                "--set",
                "sta.max_paths=17",
                "--plain",
            ]
        )
        == 0
    )
    target = project / "branch"
    snapshot = read_engineering_snapshot_from_directory(target)
    assert snapshot["workspaceId"] == "branch"
    workspace = load_workspace(target)
    assert workspace.parameters.data["config_overrides"]["sta"]["max_parallel_corners"] == 13
    assert workspace.parameters.data["sta_max_paths"] == 17
    assert read_engineering_snapshot_from_directory(source) == before


def test_cli_fork_rejects_unknown_continuation_without_registering(completed_source):
    project, _source, _steps = completed_source
    before = load_project_manifest(project)
    assert (
        cli_main.run(
            [
                "workspace",
                "fork",
                "source",
                "branch",
                "--project",
                str(project),
                "--from",
                "unknown-step",
                "--plain",
            ]
        )
        == 1
    )
    assert not (project / "branch").exists()
    assert load_project_manifest(project) == before


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        ("floorplan", "macroPlacement", ["preFloorplan", "macroPlacement"]),
        ("placement", "CTS", ["place", "diff_sizing", "CTS"]),
        ("place", "place", ["place"]),
    ],
)
def test_cli_fork_bounds_flow_and_freezes_entry_inputs(completed_source, start, end, expected):
    from chipcompiler.rtl2gds import normalize_flow_step

    project, source, steps = completed_source
    source_snapshot = read_engineering_snapshot_from_directory(source)
    source_entry = next(step for step in steps if step.name == normalize_flow_step(start))
    command = [
        "workspace",
        "fork",
        "source",
        "bounded",
        "--project",
        str(project),
        "--from",
        start,
        "--to",
        end,
        "--command-id",
        "fork-range-1",
        "--plain",
    ]
    assert cli_main.run(command) == 0
    target = project / "bounded"
    workspace = load_workspace(target)
    assert [record["name"] for record in workspace.flow.steps()] == expected
    assert [record["state"] for record in workspace.flow.steps()] == ["Unstart"] * len(expected)
    assert workspace.design.origin_verilog is not None
    assert workspace.design.origin_def is not None
    assert workspace.design.origin_verilog.parent == target / "origin"
    assert workspace.design.origin_verilog.read_bytes() == source_entry.input.verilog.read_bytes()
    assert workspace.design.origin_def.read_bytes() == source_entry.input.def_.read_bytes()
    assert workspace.parameters.data["_flow"]["start"] == expected[0]
    assert workspace.parameters.data["_flow"]["end"] == expected[-1]
    assert workspace.parameters.data["_input_mode"] == "postSynthesis"
    rebuilt = build_flow_for_workspace(workspace)
    assert rebuilt.workspace_steps[0].input.verilog == workspace.design.origin_verilog
    assert rebuilt.workspace_steps[0].input.def_ == workspace.design.origin_def
    snapshot = read_engineering_snapshot_from_directory(target)
    assert snapshot["workspaceSpec"]["flow"]["fromStepId"] == expected[0]
    assert snapshot["workspaceSpec"]["flow"]["throughStepId"] == expected[-1]
    assert snapshot["workspaceBindings"]["inputs"]["netlist"] == str(
        workspace.design.origin_verilog
    )
    manifest = load_project_manifest(project)
    branch = manifest["workspaces"][-1]
    assert normalize_flow_step(branch["start_step"]) == expected[0]
    assert normalize_flow_step(branch["end_step"]) == expected[-1]
    assert cli_main.run(command) == 0
    assert read_engineering_snapshot_from_directory(target) == snapshot
    changed_range = command.copy()
    changed_range[changed_range.index("--to") + 1] = "route"
    assert cli_main.run(changed_range) == 1
    assert read_engineering_snapshot_from_directory(target) == snapshot
    assert read_engineering_snapshot_from_directory(source) == source_snapshot


@pytest.mark.parametrize(("start", "end"), [("place", "unknown"), ("CTS", "place")])
def test_cli_fork_invalid_range_rolls_back(completed_source, start, end):
    project, source, _steps = completed_source
    manifest = load_project_manifest(project)
    snapshot = read_engineering_snapshot_from_directory(source)
    assert (
        cli_main.run(
            [
                "workspace",
                "fork",
                "source",
                "invalid",
                "--project",
                str(project),
                "--from",
                start,
                "--to",
                end,
                "--plain",
            ]
        )
        == 1
    )
    assert not (project / "invalid").exists()
    assert load_project_manifest(project) == manifest
    assert read_engineering_snapshot_from_directory(source) == snapshot


def test_cli_fork_endpoint_without_start_uses_first_source_step(completed_source):
    project, source, _steps = completed_source
    assert (
        cli_main.run(
            [
                "workspace",
                "fork",
                "source",
                "prefix",
                "--project",
                str(project),
                "--to",
                "floorplan",
                "--plain",
            ]
        )
        == 0
    )
    workspace = load_workspace(project / "prefix")
    assert [step["name"] for step in workspace.flow.steps()] == ["Synthesis", "preFloorplan"]
    source_workspace = load_workspace(source)
    assert workspace.design.origin_verilog is not None
    assert source_workspace.design.origin_verilog is not None
    assert (
        workspace.design.origin_verilog.read_bytes()
        == source_workspace.design.origin_verilog.read_bytes()
    )


def test_cli_fork_missing_entry_output_does_not_fall_back_to_original_rtl(completed_source):
    project, _source, steps = completed_source
    steps[0].output.verilog.unlink()
    before = load_project_manifest(project)
    assert (
        cli_main.run(
            [
                "workspace",
                "fork",
                "source",
                "missing-input",
                "--project",
                str(project),
                "--from",
                "preFloorplan",
                "--to",
                "macroPlacement",
                "--plain",
            ]
        )
        == 1
    )
    assert not (project / "missing-input").exists()
    assert load_project_manifest(project) == before


def _sta_signoff_items(workspace):
    """The STA corner items of *workspace*'s sta step, run from its req.json."""
    from chipcompiler.data.handshake import build_step_request, write_request
    from chipcompiler.tools.ecc.runner import collect_sta_signoff_items

    flow = build_flow_for_workspace(workspace)
    step = flow.get_workspace_step("sta")
    assert isinstance(step, EccStep)
    write_request(
        build_step_request(
            Path(workspace.directory),
            workspace.flow.steps(),
            step,
            attempt_id="attempt-sta",
            layout_image=False,
        )
    )
    return collect_sta_signoff_items(workspace, step)


def test_cli_fork_sta_range_preserves_all_inherited_corner_spefs(completed_source):
    project, source, _steps = completed_source
    source_items = _sta_signoff_items(load_workspace(source))
    assert len(source_items) > 1
    for item in source_items:
        path = Path(item["spef_file"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"*SPEF {path.name}\n", encoding="utf-8")
    assert (
        cli_main.run(
            [
                "workspace",
                "fork",
                "source",
                "sta-only",
                "--project",
                str(project),
                "--from",
                "sta",
                "--to",
                "sta",
                "--plain",
            ]
        )
        == 0
    )
    target = project / "sta-only"
    workspace = load_workspace(target)
    rebuilt = build_flow_for_workspace(workspace)
    assert [step.name for step in rebuilt.workspace_steps] == ["sta"]
    expected = [
        {**item, "spef_file": str(target / Path(item["spef_file"]).relative_to(source))}
        for item in source_items
    ]
    assert _sta_signoff_items(workspace) == expected
    assert all(Path(item["spef_file"]).is_file() for item in expected)


@pytest.mark.parametrize("corrupt_ledger", [False, True])
def test_bounded_fork_run_preserves_range_with_explicit_project_preset(
    completed_source, corrupt_ledger, capsys, plain_records
):
    project, source, _steps = completed_source
    pdk_root = load_workspace(source).pdk.root
    assert pdk_root is not None
    assert (
        cli_main.run(
            [
                "project",
                "apply",
                "--project",
                str(project),
                "--set",
                "flow.preset=rtl2gds",
                "--set",
                f"pdk.root={pdk_root}",
            ]
        )
        == 0
    )
    assert (
        cli_main.run(
            [
                "workspace",
                "fork",
                "source",
                "bounded",
                "--project",
                str(project),
                "--from",
                "preFloorplan",
                "--to",
                "macroPlacement",
            ]
        )
        == 0
    )
    path = project / "bounded" / "home" / "flow.json"
    ledger = json.loads(path.read_text())
    for step in ledger["steps"]:
        step["state"] = "Success"
    if corrupt_ledger:
        ledger["steps"][0]["tool"] = "foreign_tool"
    path.write_text(json.dumps(ledger))
    before = path.read_bytes()
    capsys.readouterr()
    result = cli_main.run(["run", "--project", str(project), "--workspace", "bounded", "--plain"])
    records = plain_records(capsys.readouterr().out)
    if corrupt_ledger:
        assert result == 1
        assert any(record.get("error") == "flow_mismatch" for record in records)
    else:
        assert result == 0
        assert any(record.get("no_op") == "True" for record in records)
    assert path.read_bytes() == before
    if not corrupt_ledger:
        # An explicit invocation target still overrides the saved range.
        assert (
            cli_main.run(
                [
                    "run",
                    "--project",
                    str(project),
                    "--workspace",
                    "bounded",
                    "--preset",
                    "rtl2gds",
                    "--plain",
                ]
            )
            == 1
        )
        records = plain_records(capsys.readouterr().out)
        assert any(record.get("error") == "flow_mismatch" for record in records)
        assert path.read_bytes() == before


_ENTER = "\r"
_DOWN = "\x1b[B"
_CLEAR = "\x15"


def _place_index(steps):
    return next(index for index, step in enumerate(steps) if step.name == "place")


def test_a_fork_chosen_in_the_terminal_is_registered_with_its_lineage(
    completed_source, scripted_terminal
):
    project, _source, steps = completed_source
    place = _place_index(steps)
    # The only source, rerun from place, the suggested name, fork.
    scripted_terminal([_ENTER, _DOWN * place, _ENTER, _ENTER, "y"])

    assert cli_main.run(["workspace", "fork", "--project", str(project)]) == 0

    entry = load_project_manifest(project)["workspaces"][-1]
    assert (entry["workspace_id"], entry["branch_from"]) == (
        "source-1",
        {"source_workspace_id": "source", "source_step": "place"},
    )
    snapshot = read_engineering_snapshot_from_directory(project / "source-1")
    assert [step["state"] for step in snapshot["flow"]["steps"]] == [
        *["Success"] * place,
        *["Unstart"] * (len(steps) - place),
    ]


def test_a_fork_can_open_its_parameters_right_away(completed_source, scripted_terminal, capsys):
    project, _source, steps = completed_source
    scripted_terminal([_DOWN * _place_index(steps), _ENTER, _CLEAR, "trial", _ENTER, "e", "q"])

    assert cli_main.run(["workspace", "fork", "source", "--project", str(project)]) == 0

    assert (project / "trial" / "home").is_dir()
    assert "cancelled" in capsys.readouterr().out


def test_a_fork_offers_only_the_parameters_of_the_steps_it_reruns(completed_source):
    from chipcompiler.cli.command_handlers.param_edit import workspace_rows
    from chipcompiler.cli.core.types import CommandContext, OutputMode
    from chipcompiler.data.parameter_schema import lookup_schema
    from chipcompiler.data.workspace_parameters import workspace_param_step

    project, _source, _steps = completed_source
    fork = ["workspace", "fork", "source", "branch", "--project", str(project), "--from", "place"]
    assert cli_main.run(fork) == 0
    ctx = CommandContext(
        project_dir=str(project),
        project=str(project),
        run_dir=str(project / "branch"),
        run_id="branch",
        output_mode=OutputMode.TEXT,
        project_state="manifest",
    )

    rows = workspace_rows(ctx, steps=["place", "CTS"])

    assert isinstance(rows, list)
    affected = {workspace_param_step(lookup_schema(row.param)) for row in rows}
    assert affected <= {"place", "CTS", None}
    assert {"place.target_density", "cts.max_fanout"} <= {row.param for row in rows}


def test_workspace_parameters_edited_in_the_terminal_change_only_that_workspace(
    completed_source, scripted_terminal
):
    from chipcompiler.data.workspace_parameters import workspace_param_diff

    project, source, _steps = completed_source
    fork = ["workspace", "fork", "source", "branch", "--project", str(project), "--from", "place"]
    assert cli_main.run(fork) == 0
    scripted_terminal(["/", "target_density", _ENTER, _ENTER, _CLEAR, "0.65", _ENTER, "s", "y"])

    edit = ["param", "edit", "--project", str(project), "--workspace", "branch", "--step", "place"]
    assert cli_main.run(edit) == 0

    branch = workspace_param_diff(load_workspace(project / "branch"))
    assert [(record["key"], record["value"]) for record in branch] == [
        ("place.target_density", 0.65)
    ]
    assert workspace_param_diff(load_workspace(source)) == []


@pytest.mark.parametrize(
    ("args", "error"),
    [
        ([], "workspace_fork_requires_terminal"),
        (["source"], "workspace_fork_requires_terminal"),
        (["source", "--from", "place"], "workspace_fork_requires_target"),
    ],
)
def test_a_fork_without_target_is_chosen_only_in_a_terminal(completed_source, capsys, args, error):
    project, _source, _steps = completed_source

    assert cli_main.run(["workspace", "fork", *args, "--project", str(project)]) == 1
    assert error in capsys.readouterr().out


def test_without_source_the_picker_offers_every_workspace(completed_source, scripted_terminal):
    project, _source, steps = completed_source
    place = _place_index(steps)
    fork = ["workspace", "fork", "source", "branch", "--project", str(project), "--from", "place"]
    assert cli_main.run(fork) == 0
    # Two workspaces and none selected: fork the second one, branch, from place.
    scripted_terminal([_DOWN, _ENTER, _DOWN * place, _ENTER, _ENTER, "y"])

    assert cli_main.run(["workspace", "fork", "--project", str(project)]) == 0

    entry = load_project_manifest(project)["workspaces"][-1]
    assert (entry["workspace_id"], entry["branch_from"]) == (
        "branch-1",
        {"source_workspace_id": "branch", "source_step": "place"},
    )


def test_a_project_without_workspaces_has_nothing_to_fork(tmp_path, capsys):
    project = tmp_path / "project"
    assert cli_main.run(["init", str(project)]) == 0
    capsys.readouterr()

    assert cli_main.run(["workspace", "fork", "--project", str(project)]) == 1
    assert "workspace_fork_no_source" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("removed", "reason"),
    [
        ("flow.json", "source cannot be forked: it has no flow steps"),
        ("engineering-snapshot.json", "source cannot be forked: it has no Engineering Snapshot"),
    ],
)
def test_a_source_given_on_the_command_line_is_refused_as_the_picker_would(
    completed_source, scripted_terminal, capsys, removed, reason
):
    project, source, _steps = completed_source
    (source / "home" / removed).unlink()
    scripted_terminal([])

    assert cli_main.run(["workspace", "fork", "source", "--project", str(project)]) == 1

    out = capsys.readouterr().out
    assert "workspace_fork_source_unavailable" in out, out
    assert reason in out, out
    assert [entry["workspace_id"] for entry in load_project_manifest(project)["workspaces"]] == [
        "source"
    ]


def test_without_source_a_fork_still_opens_its_parameters(
    completed_source, scripted_terminal, capsys
):
    project, _source, steps = completed_source
    fork = ["workspace", "fork", "source", "branch", "--project", str(project), "--from", "place"]
    assert cli_main.run(fork) == 0
    capsys.readouterr()
    # Two workspaces and none selected: fork source from Synthesis, open its parameters, cancel.
    scripted_terminal([_ENTER, _ENTER, _ENTER, "e", "q"])

    assert cli_main.run(["workspace", "fork", "--project", str(project)]) == 0

    out = capsys.readouterr().out
    assert "workspace id: source-1" in out
    assert "record: param_edit\n  status: cancelled" in out
