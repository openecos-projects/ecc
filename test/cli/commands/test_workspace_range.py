import json
from pathlib import Path

from chipcompiler.cli import main as cli_main


def _set_design_inputs(project_dir: str) -> tuple[Path, Path]:
    project = Path(project_dir)
    design_def = project / "input" / "gcd.def"
    netlist = project / "input" / "gcd.v"
    design_def.parent.mkdir()
    design_def.write_text("VERSION 5.8 ;\nDESIGN gcd ;\nEND DESIGN\n")
    netlist.write_text("module gcd; endmodule\n")
    config_path = project / "ecc.toml"
    config_path.write_text(
        config_path.read_text()
        .replace('run = "default"\n', "")
        .replace(
            'clock_port = "clk"',
            'def = "input/gcd.def"\nnetlist = "input/gcd.v"\nclock_port = "clk"',
        )
    )
    return design_def, netlist


def test_new_workspace_range_uses_ecc_toml_inputs_and_registers_after_execution(
    monkeypatch, tmp_path, capsys, create_cli_project, flow_mocks, plain_records
):
    project_dir = create_cli_project()
    design_def, netlist = _set_design_inputs(project_dir)
    monkeypatch.setattr(
        "chipcompiler.rtl2gds.builder.build_rtl2gds_flow",
        lambda *, skip=(), lec_engine=None: [("cts", "ecc", "Unstart")],
    )

    rc = cli_main.run(
        [
            "run",
            "--project",
            project_dir,
            "--workspace",
            "cts-only",
            "--from",
            "cts",
            "--to",
            "cts",
            "--plain",
        ]
    )

    assert rc == 0
    create_kwargs = flow_mocks.capture["create_kwargs"]
    assert create_kwargs["directory"] == str(Path(project_dir) / "cts-only")
    assert create_kwargs["origin_def"] == str(design_def)
    assert create_kwargs["origin_verilog"] == str(netlist)
    assert create_kwargs["parameters"]["_input_mode"] == "postSynthesis"
    assert create_kwargs["flow_config"] == {"start_step": "cts", "end_step": "cts"}
    manifest = json.loads((Path(project_dir) / "project.json").read_text())
    entry = manifest["workspaces"][0]
    assert entry["workspace_id"] == "cts-only"
    # Runtime status is derived from flow.json and the process registry; the
    # Project manifest only records durable Workspace identity.
    assert entry["status"] == "not_started"
    assert "input_snapshot" not in entry
    result = plain_records(capsys.readouterr().out)[0]
    assert result["workspace_id"] == "cts-only"
    assert result["status"] == "success"


def test_fresh_workspace_requires_a_complete_flow_range(
    tmp_path, capsys, create_cli_project, plain_records
):
    project_dir = create_cli_project()

    rc = cli_main.run(
        ["run", "--project", project_dir, "--workspace", "cts-only", "--from", "cts", "--plain"]
    )

    assert rc == 1
    assert plain_records(capsys.readouterr().out) == [
        {"kind": "error", "error": "flow_range_requires_pair"}
    ]
    assert not (Path(project_dir) / "project.json").exists()


def test_flow_range_rejects_overwrite(tmp_path, capsys, create_cli_project, plain_records):
    project_dir = create_cli_project()

    rc = cli_main.run(
        [
            "run",
            "--project",
            project_dir,
            "--workspace",
            "cts-only",
            "--from",
            "cts",
            "--to",
            "cts",
            "--overwrite",
            "--plain",
        ]
    )

    assert rc == 1
    assert plain_records(capsys.readouterr().out) == [
        {"kind": "error", "error": "selector_conflict"}
    ]


def test_unknown_from_step_is_reported_as_unknown_step(
    tmp_path, capsys, create_cli_project, plain_records
):
    project_dir = create_cli_project()

    rc = cli_main.run(
        ["run", "--project", project_dir, "--workspace", "cts-only", "--from", "bogus", "--plain"]
    )

    assert rc == 1
    [record] = plain_records(capsys.readouterr().out)
    assert record["error"] == "unknown_step"
    assert "bogus" in record["reason"]
    assert "cts" in record["reason"]
    assert not (Path(project_dir) / "project.json").exists()


def test_unknown_from_with_resume_reports_selector_conflict(
    capsys, create_cli_project, plain_records
):
    project_dir = create_cli_project()

    rc = cli_main.run(
        [
            "run",
            "--project",
            project_dir,
            "--workspace",
            "ws",
            "--from",
            "bogus",
            "--resume",
            "--plain",
        ]
    )

    assert rc == 1
    assert plain_records(capsys.readouterr().out) == [
        {"kind": "error", "error": "selector_conflict"}
    ]


def _bounded_existing_workspace(
    run_dir: Path, step_count: int = 2, *, skip_steps: list[str] | None = None
) -> list[str]:
    from chipcompiler.data.workspace.config import save_workspace_config
    from chipcompiler.rtl2gds.builder import build_rtl2gds_flow
    from test.flow_fixture import step_fields

    chain = [
        (step.value if hasattr(step, "value") else str(step), str(tool))
        for step, tool, _state in build_rtl2gds_flow()
    ]
    names = [name for name, _tool in chain]
    tools = dict(chain)
    steps = [
        {
            "name": name,
            "tool": tools[name],
            "state": "Success",
            "runtime": "",
            "peak memory (mb)": 0,
            "info": {},
            **step_fields(name, tools[name]),
        }
        for name in names[:step_count]
    ]
    home = run_dir / "home"
    home.mkdir(parents=True, exist_ok=True)
    (home / "flow.json").write_text(json.dumps({"schema_version": 3, "steps": steps}))
    params: dict[str, object] = {
        "pdk": "ics55",
        "pdk_root": str(run_dir / "pdk"),
        "design": "gcd",
        "top_module": "gcd",
        "clock": "clk",
    }
    flow_sec: dict[str, object] = {"start": names[0], "end": names[step_count - 1]}
    if skip_steps is not None:
        flow_sec["skip_steps"] = skip_steps
    assert save_workspace_config(run_dir, params, flow_sec)
    return names


def test_reconcile_extend_to_handles_later_case_sensitive_and_skipped_steps(tmp_path):
    from chipcompiler.engine.reconcile import classify_workspace, reconcile_workspace_locked

    run_dir = tmp_path / "ws"
    names = _bounded_existing_workspace(run_dir, step_count=2)
    later = names[3]

    # Uppercase or unknown extend_to does not mutate or report pending_mutation.
    assert classify_workspace(run_dir, extend_to=later.upper()).outcome == "no_op"
    assert classify_workspace(run_dir, extend_to="nope").outcome == "no_op"
    assert classify_workspace(run_dir, extend_to=names[1]).outcome == "no_op"
    assert classify_workspace(run_dir, extend_to=later).outcome == "pending_mutation"

    result = reconcile_workspace_locked(run_dir, extend_to=later)
    assert result.outcome == "extended"
    assert result.appended == tuple(names[2:4])
    flow = json.loads((run_dir / "home" / "flow.json").read_text())
    assert [s["name"] for s in flow["steps"]] == names[:4]
    assert [s["state"] for s in flow["steps"]][:2] == ["Success", "Success"]


def test_skipped_extend_to_does_not_fail_as_non_canonical(tmp_path):
    from chipcompiler.engine.reconcile import classify_workspace
    from chipcompiler.rtl2gds.builder import rtl2gds_step_names

    all_steps = rtl2gds_step_names()
    skipped_step = "diff_opt"
    end_index = all_steps.index(skipped_step) - 1
    run_dir = tmp_path / "ws_skip"
    _bounded_existing_workspace(run_dir, step_count=end_index + 1, skip_steps=[skipped_step])

    probe = classify_workspace(run_dir, extend_to=skipped_step)
    assert probe.outcome == "no_op"


def test_execute_workspace_run_uppercase_to_fails_without_mutating_disk(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from chipcompiler.cli.core.inputs import OutputOptions, ProjectOptions, RunInput
    from chipcompiler.cli.project.run_workspace import execute_workspace_run
    from chipcompiler.rtl2gds.builder import rtl2gds_step_names

    names = rtl2gds_step_names()
    run_dir = tmp_path / "ws_upper"
    _bounded_existing_workspace(run_dir, step_count=2)
    flow_before = (run_dir / "home" / "flow.json").read_text()
    params_before = (run_dir / "home" / "params.toml").read_text()

    class StubFlow:
        def __init__(self, workspace):
            self.workspace = workspace

        def has_init(self):
            return True

    monkeypatch.setattr("chipcompiler.data.load_workspace", lambda _p: SimpleNamespace(name="gcd"))
    monkeypatch.setattr("chipcompiler.engine.EngineFlow", StubFlow)
    monkeypatch.setattr(
        "chipcompiler.engine.rerun.selected_step_names",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("unknown step")),
    )

    request = RunInput(
        output=OutputOptions(),
        project=ProjectOptions(),
        from_step=names[0],
        to_step=names[3].upper(),
    )
    res = execute_workspace_run(request, str(run_dir))

    assert res.exit_code == 1
    assert res.records[0]["error"] == "unknown_step"
    assert (run_dir / "home" / "flow.json").read_text() == flow_before
    assert (run_dir / "home" / "params.toml").read_text() == params_before


def test_existing_workspace_allows_from_inserted_lec_step(
    tmp_path, capsys, create_cli_project, minimal_ics55_pdk_factory, plain_records, monkeypatch
):
    from chipcompiler.data.workspace.config import save_workspace_config
    from chipcompiler.engine.rerun import StepRunResult
    from test.flow_fixture import step_fields

    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    project_dir = create_cli_project(pdk_root=pdk_root)
    _set_design_inputs(project_dir)
    config_path = Path(project_dir) / "ecc.toml"
    text = config_path.read_text()
    config_path.write_text(
        text.replace('preset = "rtl2gds"', 'preset = "synthesis_lec"')
        if 'preset = "rtl2gds"' in text
        else f'{text}\n[flow]\npreset = "synthesis_lec"\n'
    )
    ws_dir = Path(project_dir) / "ws"
    (ws_dir / "home").mkdir(parents=True)
    (ws_dir / "home" / "flow.json").write_text(
        json.dumps(
            {
                "schema_version": 3,
                "steps": [
                    {
                        "name": "synthesis",
                        "tool": "yosys",
                        "state": "Success",
                        "info": {},
                        **step_fields("synthesis", "yosys"),
                    },
                    {
                        "name": "lec@synthesis",
                        "tool": "kepler_formal",
                        "state": "Unstart",
                        "info": {},
                        **step_fields("lec@synthesis", "kepler_formal"),
                    },
                ],
            }
        )
    )
    assert save_workspace_config(
        ws_dir,
        {
            "pdk": "ics55",
            "pdk_root": str(pdk_root),
            "design": "gcd",
            "top_module": "gcd",
            "clock": "clk",
        },
        {"preset": "synthesis_lec"},
    )
    seen: list[str] = []
    monkeypatch.setattr(
        "chipcompiler.cli.project.run_preflight.build_run_preflight",
        lambda _flow, selected, **_kw: seen.extend(selected) or [],
    )
    monkeypatch.setattr(
        "chipcompiler.cli.project.run_preflight.preflight_failure",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "chipcompiler.engine.EngineFlow.create_step_workspaces",
        lambda _self, **_kwargs: None,
    )
    monkeypatch.setattr(
        "chipcompiler.engine.rerun.run_from",
        lambda _flow, from_step, through=None: StepRunResult(ok=True, executed=(from_step,)),
    )

    rc = cli_main.run(
        ["run", "--project", project_dir, "--workspace", "ws", "--from", "lec@synthesis", "--plain"]
    )

    assert rc == 0
    assert seen == ["lec@synthesis"]
    records = plain_records(capsys.readouterr().out)
    assert records[-1]["executed_steps"] == "[lec@synthesis]"
