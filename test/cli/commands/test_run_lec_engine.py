"""[flow] lec_engine threading through `ecc run` creation and preflight."""

import os

from chipcompiler.cli import main as cli_main


def _declare_lec_engine(project_dir, value):
    toml_path = os.path.join(project_dir, "ecc.toml")
    with open(toml_path) as f:
        toml = f.read()
    toml += f'\nlec_engine = "{value}"\n'
    with open(toml_path, "w") as f:
        f.write(toml)


def _lec_chain(monkeypatch):
    chain = [
        ("Synthesis", "yosys", "Unstart"),
        ("postRouteLec", "kepler_formal", "Unstart"),
        ("Harden", "ecc", "Unstart"),
    ]
    monkeypatch.setattr(
        "chipcompiler.rtl2gds.builder.build_rtl2gds_flow",
        lambda *, skip=(), lec_engine=None: [entry for entry in chain if entry[0] not in set(skip)],
    )
    return chain


def test_run_threads_declared_lec_engine_into_the_ledger(
    tmp_path, monkeypatch, create_cli_project, flow_mocks
):
    project_dir = create_cli_project()
    _declare_lec_engine(project_dir, "yosys_lec")
    _lec_chain(monkeypatch)

    rc = cli_main.run(["run", "--project", project_dir])

    assert rc == 0
    added = flow_mocks.flow.instances[0].added_steps
    assert [tool for step, tool, _state in added if step == "postRouteLec"] == ["yosys_lec"]
    flow_config = flow_mocks.capture["create_kwargs"]["flow_config"]
    assert flow_config["lec_engine"] == "yosys_lec"


def test_run_rejects_an_invalid_lec_engine(tmp_path, capsys, create_cli_project, flow_mocks):
    project_dir = create_cli_project()
    _declare_lec_engine(project_dir, "bogus")

    rc = cli_main.run(["run", "--project", project_dir])

    assert rc == 1
    assert "unknown LEC engine" in capsys.readouterr().out
    assert flow_mocks.capture["create_kwargs"] is None


def test_preset_override_preserves_the_declared_lec_engine(
    tmp_path, monkeypatch, create_cli_project, flow_mocks
):
    project_dir = create_cli_project()
    _declare_lec_engine(project_dir, "yosys_lec")
    _lec_chain(monkeypatch)

    rc = cli_main.run(["run", "--project", project_dir, "--preset", "rtl2gds"])

    assert rc == 0
    flow_config = flow_mocks.capture["create_kwargs"]["flow_config"]
    assert flow_config["lec_engine"] == "yosys_lec"
    added = flow_mocks.flow.instances[0].added_steps
    assert [tool for step, tool, _state in added if step == "postRouteLec"] == ["yosys_lec"]


def test_range_override_preserves_the_declared_lec_engine(
    tmp_path, monkeypatch, create_cli_project, flow_mocks
):
    project_dir = create_cli_project()
    _declare_lec_engine(project_dir, "yosys_lec")
    _lec_chain(monkeypatch)

    rc = cli_main.run(["run", "--project", project_dir, "--from", "Synthesis", "--to", "Harden"])

    assert rc == 0
    flow_config = flow_mocks.capture["create_kwargs"]["flow_config"]
    assert flow_config["lec_engine"] == "yosys_lec"
    added = flow_mocks.flow.instances[0].added_steps
    assert [tool for step, tool, _state in added if step == "postRouteLec"] == ["yosys_lec"]


def test_preflight_applies_the_configured_engine(monkeypatch):
    from chipcompiler.cli.inspection import env_probe

    _lec_chain(monkeypatch)

    # kepler-formal is visited for a kepler ledger (the default engine)...
    assert env_probe.probe_components_for_preset("rtl2gds") == (
        "ecc-tools",
        "yosys",
        "kepler-formal",
    )
    # ...and dual fans out to the composite component.
    assert env_probe.probe_components_for_preset("rtl2gds", lec_engine="lec_dual") == (
        "ecc-tools",
        "yosys",
        "lec-dual",
    )


def test_probe_components_for_steps_includes_kepler_formal():
    from chipcompiler.cli.inspection import env_probe

    assert env_probe.probe_components_for_steps([("postRouteLec", "kepler_formal", "Unstart")]) == (
        "kepler-formal",
    )
