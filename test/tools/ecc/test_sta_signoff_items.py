"""STA corner items: where each corner's SPEF comes from and which corners run."""

import json
from pathlib import Path

import pytest

from chipcompiler.data import PDK, OriginDesign, Workspace
from chipcompiler.data.handshake import load_request
from chipcompiler.data.types import AnalysisData
from chipcompiler.tools.ecc import runner as ecc_runner
from test.flow_fixture import step_fields
from test.tools.ecc.sta_requests import sta_step_with_request


def test_sta_signoff_items_use_top_module_for_rcx_spef(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    sta_config = config_dir / "sta_ecc.json"
    rcx_config = config_dir / "rcx_ecc.json"
    sta_config.write_text(
        json.dumps(
            {
                "liberty": [{"corner": "MAX", "temperature": 125, "path": ["max.lib"]}],
                "signoff": [{"MAX": ["Cworst"]}],
            }
        )
    )
    rcx_config.write_text(json.dumps({"output": str(tmp_path / "rcx_ecc" / "data")}))
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="project_gcd_ws_0002", top_module="gcd"),
        config={"sta": sta_config, "rcx": rcx_config},
    )
    step = sta_step_with_request(tmp_path, {AnalysisData.PARASITICS: "rcx_ecc"})

    items = ecc_runner.collect_sta_signoff_items(workspace, step)

    assert items[0]["spef_file"] == str(tmp_path / "rcx_ecc" / "output" / "gcd_Cworst_125C.spef")


def test_sta_entry_workspace_uses_declared_spef(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    sta_config = config_dir / "sta_ecc.json"
    sta_config.write_text(
        json.dumps(
            {
                "liberty": [{"corner": "MAX", "temperature": 125, "path": ["max.lib"]}],
                "signoff": [{"MAX": ["Cworst"]}],
            }
        )
    )
    declared_spef = tmp_path / "origin" / "gcd.spef"
    declared_spef.parent.mkdir()
    declared_spef.write_text("*SPEF\n", encoding="utf-8")
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
        config={"sta": sta_config},
    )
    workspace.pdk.spef = declared_spef
    # An STA-entry flow has no RCX step upstream.
    step = sta_step_with_request(tmp_path, {})

    items = ecc_runner.collect_sta_signoff_items(workspace, step)

    assert [item["spef_file"] for item in items] == [str(declared_spef)]
    workspace.pdk.spef = None
    with pytest.raises(ValueError, match="no parasitics"):
        ecc_runner.collect_sta_signoff_items(workspace, step)


def test_derived_sta_workspace_reads_the_rcx_outputs_it_inherited(tmp_path):
    from chipcompiler.data.handshake import missing_design_data

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    sta_config = config_dir / "sta_ecc.json"
    sta_config.write_text(
        json.dumps(
            {
                "liberty": [{"corner": "MAX", "temperature": 125, "path": ["max.lib"]}],
                "signoff": [{"MAX": ["Cworst"]}],
            }
        )
    )
    # Derived with --from sta: the ledger dropped RCX, the copy kept its outputs.
    spef = tmp_path / "19_rcx_ecc" / "output" / "gcd_Cworst_125C.spef"
    spef.parent.mkdir(parents=True)
    spef.write_text("*SPEF\n", encoding="utf-8")
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "flow.json").write_text(
        json.dumps(
            {
                "schema_version": 3,
                "steps": [
                    {
                        "name": "sta",
                        "tool": "ecc",
                        "state": "Unstart",
                        **step_fields("sta", "ecc"),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
        config={"sta": sta_config},
    )
    workspace.flow.path = tmp_path / "home" / "flow.json"
    step = sta_step_with_request(tmp_path, {})

    items = ecc_runner.collect_sta_signoff_items(workspace, step)

    assert [item["spef_file"] for item in items] == [str(spef)]
    assert step.directory is not None
    request = load_request(step.directory)
    assert AnalysisData.PARASITICS not in missing_design_data(request, step, declared_spef=None)


def test_default_sta_signoff_items_use_typ_and_min_corners(tmp_path):
    template = Path(__file__).parents[2] / "pdk" / "fixtures" / "tool_defaults.json"
    sta_config = tmp_path / "config" / "sta_ecc.json"
    sta_config.parent.mkdir()
    sta_config.write_text(
        json.dumps(json.loads(template.read_text(encoding="utf-8"))["sta"]), encoding="utf-8"
    )
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
        pdk=PDK(spef=tmp_path / "design.spef"),
    )

    step = sta_step_with_request(tmp_path, {})
    items = ecc_runner.collect_sta_signoff_items(workspace, step)

    assert [(item["corner"], item["rcx_corner"]) for item in items] == [
        ("TYP", "TYPICAL"),
        ("MIN", "Cworst"),
        ("MIN", "RCworst"),
        ("MIN", "Cbest"),
        ("MIN", "RCbest"),
    ]
