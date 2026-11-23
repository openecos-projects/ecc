import json
import tomllib

import tomli_w

from chipcompiler.cli.core.inputs import InitInput, output_options
from chipcompiler.cli.project.config import load_project_config
from chipcompiler.cli.project.project_init import create_project
from chipcompiler.cli.project.rtl_import import import_project_rtl
from chipcompiler.pdk.clone import clone_with_pdk


def test_clone_preserves_rtl_but_replaces_pdk_and_discards_results(tmp_path):
    roots = [tmp_path / "first", tmp_path / "second"]
    for index, root in enumerate(roots):
        root.mkdir()
        (root / "ecc-pdk.json").write_text(json.dumps({"family_id": f"vendor{index}"}))
    source = create_project(
        InitInput(name=str(tmp_path / "source"), pdk_root=str(roots[0]), output=output_options())
    )
    rtl = tmp_path / "input.v"
    rtl.write_text("module top(input a, output y); assign y=a; endmodule")
    import_project_rtl(str(source), verilog=(str(rtl),))
    (source / "old-workspace").mkdir()
    config_path = source / "ecc.toml"
    config = tomllib.loads(config_path.read_text())
    config["design"].update(top="my_top", clock_port="clock", frequency_mhz=73)
    config["params"]["sdc"]["clock_list"] = ""
    config_path.write_text(tomli_w.dumps(config))
    before = config_path.read_bytes()
    target = clone_with_pdk(source, tmp_path / "clone", roots[1])
    assert config_path.read_bytes() == before
    assert not (target / "pdk.lock.json").exists()
    assert load_project_config(str(target / "ecc.toml")).pdk_name == "vendor1"
    assert not (target / "old-workspace").exists()
    assert any(path.read_text() == rtl.read_text() for path in (target / "rtl").rglob("*.v"))
    assert str(source) not in (target / "ecc.toml").read_text()

    cloned = load_project_config(str(target / "ecc.toml"))
    assert cloned.design_clock_port == "clock"
    assert cloned.design_top == "my_top"
    assert cloned.design_frequency_mhz == 73
    metadata = json.loads((target / "project.json").read_text())["base_design"]
    assert metadata["clock"] == "clock"
    assert metadata["parameters"]["frequency_max"] == 73
