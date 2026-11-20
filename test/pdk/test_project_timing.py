import json

from chipcompiler.cli.core.inputs import InitInput, output_options
from chipcompiler.cli.project.config import load_project_config
from chipcompiler.cli.project.project_init import create_project


def test_new_project_clock_template_uses_package_corners(tmp_path):
    pdk = tmp_path / "pdk"
    pdk.mkdir()
    (pdk / "ecc-pdk.json").write_text(
        json.dumps(
            {
                "family_id": "arbitrary",
                "tools": {
                    "configs": {
                        "sta": {
                            "liberty": [
                                {"corner": "slow_custom", "temperature": 90, "path": []},
                                {"corner": "fast_custom", "temperature": 0, "path": []},
                            ]
                        }
                    }
                },
            }
        )
    )
    project = create_project(
        InitInput(
            name=str(tmp_path / "project"),
            pdk_root=str(pdk),
            output=output_options(),
        )
    )
    text = (project / "ecc.toml").read_text()
    assert "clk slow_custom:100 fast_custom:100" in text
    assert "MAX:100" not in text
    config = load_project_config(str(project / "ecc.toml"))
    assert config._timing_input_error is None
    assert config.design_clock_port == "clk"
    assert config.design_frequency_mhz == 100
