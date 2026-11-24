"""Project CLI integration for the canonical no-clock policy."""

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import chipcompiler.data as data_api
from chipcompiler.cli import main as cli_main
from chipcompiler.cli.command_handlers.project import (
    _preflight_environment,
    _preflight_flow_range,
)
from chipcompiler.cli.core.types import CommandContext, CommandResult, OutputMode
from chipcompiler.cli.project.config import (
    ProjectNoClockDecisionResolver,
    load_project_config,
    to_parameters,
    validate_project_config,
)
from chipcompiler.cli.project.effective_config import (
    attach_project_no_clock,
    resolve_effective_config,
)
from chipcompiler.cli.project.flow_selection import effective_insert_steps, effective_skip_steps
from chipcompiler.data.workspace.sdc_inputs import SdcInputs
from chipcompiler.rtl2gds import NoClockDecision, resolve_skip_steps

_DEFAULT_SKIPS = resolve_skip_steps(None)
_NO_CLOCK_SKIPS = ("preplace", "diff_opt", "diff_sizing", "cts", "timing_optimization")
_NO_CLOCK_ADDED_SKIPS = frozenset(_NO_CLOCK_SKIPS).difference(_DEFAULT_SKIPS)
_CLOCK_ERRORS = ("design.clock_port", "design.frequency_mhz")


@pytest.fixture(autouse=True)
def _pdk_contents_are_valid(monkeypatch):
    monkeypatch.setattr(
        "chipcompiler.cli.project.config._validate_pdk_contents",
        lambda name, root, overrides=None: None,
    )


def _load_config(
    project_dir,
    *,
    no_clock=None,
    clock='""',
    frequency=0,
    skip_steps=None,
    insert_steps=None,
):
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "pdk").mkdir(exist_ok=True)
    flow = ['preset = "rtl2gds"']
    if no_clock is not None:
        flow.append(f"no_clock = {no_clock}")
    if skip_steps is not None:
        flow.append(f"skip_steps = {skip_steps}")
    if insert_steps is not None:
        flow.append(f"insert_steps = {insert_steps}")
    (project_dir / "ecc.toml").write_text(
        "[design]\n"
        'name = "gcd"\n'
        'top = "gcd"\n'
        'rtl = ["rtl/gcd.v"]\n'
        f"clock_port = {clock}\n"
        f"frequency_mhz = {frequency}\n"
        "\n[pdk]\n"
        'name = "ics55"\n'
        f'root = "{project_dir / "pdk"}"\n'
        "\n[flow]\n" + "\n".join(flow) + "\n"
    )
    return load_project_config(str(project_dir / "ecc.toml"))


def _timing_errors(cfg):
    return [error for error in validate_project_config(cfg) if error.startswith(_CLOCK_ERRORS)]


def _capture_preflight_steps(monkeypatch):
    captured = []

    def capture(steps):
        captured.append(tuple(getattr(step, "value", str(step)) for step, _tool, _state in steps))
        return ()

    monkeypatch.setattr("chipcompiler.cli.inspection.env_probe.probe_components_for_steps", capture)
    return captured


@pytest.mark.parametrize(
    ("literal", "clock", "flag", "source", "skips"),
    [
        ("true", '""', True, "explicit", _NO_CLOCK_SKIPS),
        ("true", '"clk"', True, "explicit", _NO_CLOCK_SKIPS),
        ("false", '""', False, "off", _DEFAULT_SKIPS),
    ],
)
def test_explicit_no_clock_precedence(tmp_path, literal, clock, flag, source, skips):
    cfg = _load_config(tmp_path, no_clock=literal, clock=clock, frequency=100)

    decision = ProjectNoClockDecisionResolver(cfg).resolve()

    assert cfg.flow_no_clock is flag
    assert "flow.no_clock" in cfg._explicit_keys
    assert decision == NoClockDecision(enabled=flag, source=source)
    assert effective_skip_steps(cfg, None) == skips


@pytest.mark.parametrize("clock", [None, '""', '"   "'])
def test_absent_empty_and_whitespace_clocks_infer_no_clock(tmp_path, clock):
    cfg = _load_config(tmp_path, clock='""' if clock is None else clock)
    if clock is None:
        config_path = Path(cfg.config_path)
        config_path.write_text(config_path.read_text().replace('clock_port = ""\n', ""))
        cfg = load_project_config(str(config_path))

    assert ProjectNoClockDecisionResolver(cfg).resolve() == NoClockDecision(
        enabled=True, source="inferred"
    )
    assert effective_skip_steps(cfg, None) == _NO_CLOCK_SKIPS
    assert _timing_errors(cfg) == []


def test_missing_project_config_does_not_infer_no_clock():
    assert ProjectNoClockDecisionResolver(None).resolve() == NoClockDecision(
        enabled=False, source="off"
    )


@pytest.mark.parametrize("literal", ['"yes"', "1", "0", "[]", "{ value = true }"])
def test_invalid_no_clock_types_are_structured_config_errors(tmp_path, literal):
    cfg = _load_config(tmp_path, no_clock=literal, clock='"clk"', frequency=100)

    errors = validate_project_config(cfg)

    assert any(error.startswith("no_clock must be a boolean") for error in errors)


def test_manifest_retained_clock_rejects_boolean_frequency(
    tmp_path, manifest_stubs, capsys, plain_records
):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    manifest_stubs.write(
        project_dir,
        [manifest_stubs.entry(project_dir, "ws_0001")],
        base_design={
            "pdk": "ics55",
            "pdk_root": str(project_dir / "pdk"),
            "top_module": "gcd",
            "clock": "clk",
            "rtl_list": ["rtl/gcd.v"],
            "frequency_mhz": True,
        },
    )
    capsys.readouterr()

    assert cli_main.run(["check", "--project", str(project_dir), "--plain"]) == 1

    records = plain_records(capsys.readouterr().out)
    assert any(
        "design.frequency_mhz must be greater than 0" in record.get("reason", "")
        for record in records
    )


@pytest.mark.parametrize("literal", ["42", "true", '["clk"]', '{ name = "clk" }'])
def test_invalid_clock_material_types_are_rejected(tmp_path, literal):
    cfg = _load_config(tmp_path, clock=literal, frequency=100)

    errors = validate_project_config(cfg)

    assert any(error.startswith("clock_port clock material must be a string") for error in errors)


def test_explicit_empty_skip_policy_is_preserved(tmp_path):
    cfg = _load_config(
        tmp_path,
        no_clock="false",
        clock='"clk"',
        frequency=100,
        skip_steps="[]",
    )

    assert effective_skip_steps(cfg, None) == ()
    assert effective_skip_steps(cfg, {"skip_steps": [], "no_clock": True}) == _NO_CLOCK_SKIPS


@pytest.mark.parametrize(
    ("clock", "no_clock", "expect_clock_steps"),
    [
        ('""', None, False),
        ('"   "', None, False),
        ('"clk"', None, True),
        ('""', False, True),
    ],
)
def test_preflight_paths_apply_inferred_and_explicit_no_clock(
    tmp_path, monkeypatch, clock, no_clock, expect_clock_steps
):
    literal = None if no_clock is None else str(no_clock).lower()
    cfg = _load_config(tmp_path, no_clock=literal, clock=clock, frequency=100)
    captured = _capture_preflight_steps(monkeypatch)
    flow_config = {"start_step": "synthesis", "end_step": "harden"}
    if no_clock is not None:
        flow_config["no_clock"] = no_clock

    assert _preflight_flow_range(flow_config, None, cfg) is None
    assert _preflight_environment("rtl2gds", None, flow_config, cfg) is None
    expected = _NO_CLOCK_ADDED_SKIPS if expect_clock_steps else frozenset()
    assert [set(steps) & _NO_CLOCK_ADDED_SKIPS for steps in captured] == [expected, expected]


def test_preflight_paths_without_config_keep_no_material_behavior(monkeypatch):
    captured = _capture_preflight_steps(monkeypatch)
    flow_config = {"start_step": "synthesis", "end_step": "harden"}

    assert _preflight_flow_range(flow_config, None) is None
    assert _preflight_environment("rtl2gds", None, flow_config) is None
    assert [set(steps) & _NO_CLOCK_ADDED_SKIPS for steps in captured] == [
        _NO_CLOCK_ADDED_SKIPS,
        _NO_CLOCK_ADDED_SKIPS,
    ]


@pytest.mark.parametrize(
    ("start_step", "end_step"),
    [("preplace", "harden"), ("synthesis", "cts"), ("diff_sizing", "cts")],
    ids=["skipped-start", "skipped-end", "clock-steps-only"],
)
def test_no_clock_flow_range_with_skipped_boundaries_degrades_to_no_preflight(
    tmp_path, monkeypatch, start_step, end_step
):
    cfg = _load_config(tmp_path)
    captured = _capture_preflight_steps(monkeypatch)

    assert (
        _preflight_flow_range({"start_step": start_step, "end_step": end_step}, None, cfg) is None
    )
    assert captured == []


@pytest.mark.parametrize(
    ("no_clock", "clock", "frequency", "expected"),
    [
        ("true", '""', 0, []),
        (
            "false",
            '""',
            0,
            [
                "design.clock_port is required",
                "design.frequency_mhz must be greater than 0",
            ],
        ),
        ("true", '"clk"', 0, ["design.frequency_mhz must be greater than 0"]),
        (None, '"clk"', 100, []),
        (None, '"   "', 0, []),
    ],
)
def test_no_clock_timing_validation(tmp_path, no_clock, clock, frequency, expected):
    cfg = _load_config(tmp_path, no_clock=no_clock, clock=clock, frequency=frequency)

    assert _timing_errors(cfg) == expected


@pytest.mark.parametrize("frequency", [-1, 0, "nan", "inf", "-inf", "true", '"fast"', "[]"])
def test_retained_clock_requires_a_positive_finite_numeric_frequency(tmp_path, frequency):
    cfg = _load_config(tmp_path, clock='"clk"', frequency=frequency)

    assert _timing_errors(cfg) == ["design.frequency_mhz must be greater than 0"]


def test_to_parameters_trims_nonempty_clock_and_normalizes_whitespace(tmp_path):
    retained = _load_config(tmp_path / "retained", clock='" clk "', frequency=100)
    inferred = _load_config(tmp_path / "inferred", clock='"   "')

    assert to_parameters(retained)["clock"] == "clk"
    assert to_parameters(inferred)["clock"] == ""
    assert (
        SdcInputs.from_parameters(to_parameters(inferred)).clocks(to_parameters(inferred), "TYP")
        == ()
    )


def test_attach_project_no_clock_materializes_inference_and_explicit_false(tmp_path):
    inferred = _load_config(tmp_path / "inferred", insert_steps='["lec@routing"]')
    disabled = _load_config(tmp_path / "disabled", no_clock="false")
    original = {"insert_steps": ["lec@routing"]}

    assert attach_project_no_clock(original, inferred) == {
        "insert_steps": ["lec@routing"],
        "no_clock": True,
    }
    assert original == {"insert_steps": ["lec@routing"]}
    assert attach_project_no_clock(None, disabled) == {"no_clock": False}
    assert effective_insert_steps(inferred, attach_project_no_clock(original, inferred)) == (
        "lec@routing",
    )


def test_virgin_project_passes_explicit_no_clock_to_workspace_creation(
    create_cli_project, flow_mocks
):
    project_dir = create_cli_project()
    with Path(project_dir, "ecc.toml").open("a") as config_file:
        config_file.write("no_clock = true\n")

    assert cli_main.run(["run", "--project", project_dir]) == 0

    assert flow_mocks.capture["create_kwargs"]["flow_config"]["no_clock"] is True


@pytest.mark.parametrize("clock", ["", "   "])
def test_virgin_project_persists_inferred_policy_and_filters_initial_ledger(
    monkeypatch, create_cli_project, flow_mocks, clock
):
    from chipcompiler.rtl2gds import build_rtl2gds_flow

    monkeypatch.setattr("chipcompiler.rtl2gds.builder.build_rtl2gds_flow", build_rtl2gds_flow)
    fake_create = data_api.create_workspace

    def create_with_parameters(**kwargs):
        workspace = fake_create(**kwargs)
        workspace.parameters = SimpleNamespace(data={})
        return workspace

    monkeypatch.setattr(data_api, "create_workspace", create_with_parameters)
    monkeypatch.setattr("chipcompiler.data.parameter.save_parameter", lambda _parameters: True)
    project_dir = create_cli_project(freq=0)
    config_path = Path(project_dir, "ecc.toml")
    config_path.write_text(
        config_path.read_text().replace('clock_port = "clk"', f'clock_port = "{clock}"')
    )

    assert cli_main.run(["run", "--project", project_dir]) == 0

    (flow,) = flow_mocks.flow.instances
    step_names = [str(step) for step, _tool, _state in flow.added_steps]
    assert set(step_names).isdisjoint(_NO_CLOCK_SKIPS)
    assert flow.workspace.parameters.data["_flow"] == {
        "preset": "rtl2gds",
        "no_clock": True,
        "skip_steps": list(_NO_CLOCK_SKIPS),
    }
    manifest = json.loads(Path(project_dir, "project.json").read_text())
    assert manifest["base_design"].get("clock", "").strip() == ""
    assert {key: manifest["workspaces"][0][key] for key in ("start_step", "end_step")} == {
        "start_step": "synthesis",
        "end_step": "harden",
    }


def test_effective_config_carries_no_clock_without_losing_inserts(tmp_path, manifest_stubs):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    manifest_stubs.write(project_dir, [manifest_stubs.entry(project_dir, "ws_0001")])
    cfg = _load_config(
        project_dir,
        no_clock="true",
        clock='"clk"',
        frequency=100,
        skip_steps="[]",
        insert_steps='["lec@routing"]',
    )
    ctx = CommandContext(
        project_dir=str(project_dir),
        project=str(project_dir),
        run_dir=str(project_dir / "ws_0001"),
        run_id="ws_0001",
        output_mode=OutputMode.PLAIN,
        config=cfg,
        project_state="manifest",
    )

    resolved = resolve_effective_config(ctx, "ws_0001", cfg)

    assert not isinstance(resolved, CommandResult)
    effective, flow_config, _warnings = resolved
    assert effective is cfg
    assert flow_config == {
        "skip_steps": [],
        "no_clock": True,
        "insert_steps": ["lec@routing"],
    }


@pytest.mark.parametrize(
    ("flow_line", "clock_line", "frequency_line", "reason"),
    [
        ('no_clock = "yes"', 'clock_port = ""', "frequency_mhz = 0", "no_clock must be a boolean"),
        ("", 'clock_port = ["clk"]', "frequency_mhz = 100", "clock material must be a string"),
        ("", 'clock_port = "clk"', "frequency_mhz = true", "frequency_mhz must be greater than 0"),
    ],
)
def test_invalid_project_values_fail_before_workspace_creation(
    create_cli_project,
    flow_mocks,
    capsys,
    plain_records,
    flow_line,
    clock_line,
    frequency_line,
    reason,
):
    project_dir = create_cli_project()
    config = Path(project_dir, "ecc.toml")
    text = config.read_text().replace('clock_port = "clk"', clock_line)
    text = text.replace("frequency_mhz = 100.0", frequency_line)
    if flow_line:
        text += flow_line + "\n"
    config.write_text(text)
    capsys.readouterr()

    assert cli_main.run(["run", "--project", project_dir, "--plain"]) == 1

    records = plain_records(capsys.readouterr().out)
    assert any(reason in record.get("reason", "") for record in records)
    assert flow_mocks.capture["create_kwargs"] is None


@pytest.mark.parametrize(
    ("start_step", "end_step"),
    [("preplace", "harden"), ("synthesis", "cts"), ("diff_sizing", "cts")],
    ids=["skipped-start", "skipped-end", "no-runnable-steps"],
)
def test_no_clock_cli_range_rejects_skipped_boundaries_before_creation(
    monkeypatch, create_cli_project, flow_mocks, capsys, plain_records, start_step, end_step
):
    from chipcompiler.rtl2gds import build_rtl2gds_flow

    monkeypatch.setattr("chipcompiler.rtl2gds.builder.build_rtl2gds_flow", build_rtl2gds_flow)
    project_dir = create_cli_project(freq=0)
    config = Path(project_dir, "ecc.toml")
    config.write_text(config.read_text().replace('clock_port = "clk"', 'clock_port = ""'))
    capsys.readouterr()

    rc = cli_main.run(
        [
            "run",
            "--project",
            project_dir,
            "--from",
            start_step,
            "--to",
            end_step,
            "--plain",
        ]
    )

    assert rc == 1
    records = plain_records(capsys.readouterr().out)
    assert any(record.get("error") == "flow_range_invalid" for record in records)
    assert flow_mocks.capture["create_kwargs"] is None


def test_existing_no_clock_workspace_reloads_without_resurrecting_clock_steps(
    tmp_path, create_cli_project, minimal_ics55_pdk_factory, monkeypatch, capsys, plain_records
):
    from chipcompiler.data.workspace.config import (
        flow_section_from_flow_config,
        load_workspace_config,
        save_workspace_config,
    )
    from test.cli.commands.test_flow_continuation import (
        RTL2GDS_NAMES,
        _write_existing_workspace,
    )

    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    project_dir = create_cli_project(pdk_root=pdk_root, freq=0)
    config = Path(project_dir, "ecc.toml")
    config.write_text(config.read_text().replace('clock_port = "clk"', 'clock_port = ""'))
    run_dir = os.path.join(project_dir, "default")
    kept = [name for name in RTL2GDS_NAMES if name not in _NO_CLOCK_SKIPS]
    _write_existing_workspace(
        run_dir,
        kept,
        pdk_root=pdk_root,
        extra={"clock": "", "frequency_max": 0},
    )
    flow_section = flow_section_from_flow_config(
        {"preset": "rtl2gds", "no_clock": True}, materials={"clock_port": ""}
    )
    assert save_workspace_config(
        run_dir,
        {
            "pdk": "ics55",
            "pdk_root": str(pdk_root),
            "design": "gcd",
            "top_module": "gcd",
            "clock": "",
            "frequency_max": 0,
        },
        flow_section,
    )

    class Flow:
        def __init__(self, workspace):
            self.workspace = workspace

        def create_step_workspaces(self, **_kwargs):
            raise AssertionError("a no-op reload must not rebuild step workspaces")

    monkeypatch.setattr("chipcompiler.engine.EngineFlow", Flow)
    before_names = [
        step["name"] for step in json.loads(Path(run_dir, "home", "flow.json").read_text())["steps"]
    ]
    capsys.readouterr()

    assert cli_main.run(["run", "--project", project_dir, "--plain"]) == 0

    records = plain_records(capsys.readouterr().out)
    assert records[0]["no_op"] == "True"
    after_names = [
        step["name"] for step in json.loads(Path(run_dir, "home", "flow.json").read_text())["steps"]
    ]
    assert after_names == before_names == kept
    assert set(after_names).isdisjoint(_NO_CLOCK_SKIPS)
    assert load_workspace_config(run_dir)["_flow"] == flow_section


def test_project_set_and_show_no_clock_uses_strict_boolean_values(
    create_cli_project, capsys, plain_records
):
    project_dir = create_cli_project()

    assert (
        cli_main.run(
            ["project", "set", "flow.no_clock", "true", "--project", project_dir, "--plain"]
        )
        == 0
    )
    assert plain_records(capsys.readouterr().out)[0]["value"] == "True"
    assert (
        cli_main.run(["project", "show", "flow.no_clock", "--project", project_dir, "--plain"]) == 0
    )
    assert plain_records(capsys.readouterr().out)[0]["value"] == "True"

    assert (
        cli_main.run(
            ["project", "set", "flow.no_clock", "yes", "--project", project_dir, "--plain"]
        )
        == 1
    )
    records = plain_records(capsys.readouterr().out)
    assert records[0]["error"] == "invalid_project_value"
    assert "no_clock = true" in Path(project_dir, "ecc.toml").read_text()
