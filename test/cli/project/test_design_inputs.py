from chipcompiler.cli.project.config import ProjectConfig
from chipcompiler.cli.project.design_inputs import validate_entry_inputs


def _config(tmp_path, **fields):
    return ProjectConfig(project_dir=str(tmp_path), **fields)


def test_physical_entry_requires_def_and_netlist(tmp_path):
    cfg = _config(tmp_path)

    assert validate_entry_inputs(cfg, "CTS") == [
        "step_input_missing: CTS requires design.def",
        "step_input_missing: CTS requires design.netlist",
    ]


def test_sta_entry_requires_spef_and_accepts_declared_files(tmp_path):
    def_path = tmp_path / "gcd.def"
    netlist = tmp_path / "gcd.v"
    spef = tmp_path / "gcd.spef"
    for path in (def_path, netlist, spef):
        path.write_text("input\n")
    cfg = _config(
        tmp_path,
        design_def=def_path.name,
        design_netlist=netlist.name,
        design_spef=spef.name,
    )

    assert validate_entry_inputs(cfg, "sta") == []


def test_lec_entry_requires_a_golden_netlist(tmp_path):
    netlist = tmp_path / "gcd.v"
    netlist.write_text("module gcd; endmodule\n")
    cfg = _config(tmp_path, design_netlist=netlist.name)

    assert validate_entry_inputs(cfg, "lec") == [
        "step_input_missing: lec requires design.golden_netlist"
    ]


def test_flow_run_key_is_rejected_as_unsupported(tmp_path):
    from chipcompiler.cli.project.config import load_project_config, validate_project_config

    config_path = tmp_path / "ecc.toml"
    config_path.write_text('[flow]\nrun = "default"\n')

    errors = validate_project_config(load_project_config(str(config_path)))

    assert "unsupported_flow_run: [flow].run is not supported ('default')" in errors
