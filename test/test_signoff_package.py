import json
from pathlib import Path

from chipcompiler.data import OriginDesign, Parameters, StateEnum, Workspace
from chipcompiler.engine import EngineFlow
from chipcompiler.engine.signoff import SignoffPackageOptions


def _write(path: Path, text: str = "data") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _write_json(path: Path, data: dict) -> None:
    _write(path, json.dumps(data, indent=2))


def _make_signoff_workspace(
    tmp_path: Path,
    design: str = "gcd",
    top_module: str = "gcd",
) -> Path:
    workspace_dir = tmp_path / "gcd_workspace"

    _write(workspace_dir / "origin" / f"{top_module}.v", "module gcd; endmodule\n")
    _write(
        workspace_dir / "origin" / f"{top_module}.sdc",
        "create_clock -period 10 clk\n",
    )
    _write_json(
        workspace_dir / "home" / "parameters.json",
        {"Design": design, "Top module": top_module, "PDK": "ics55"},
    )
    _write_json(
        workspace_dir / "home" / "flow.json",
        {
            "steps": [
                {"name": "route", "tool": "ecc", "state": StateEnum.Success.value},
                {"name": "drc", "tool": "ecc", "state": StateEnum.Success.value},
                {"name": "filler", "tool": "ecc", "state": StateEnum.Success.value},
                {"name": "RCX", "tool": "ecc", "state": StateEnum.Success.value},
                {"name": "sta", "tool": "ecc", "state": StateEnum.Success.value},
                {"name": "Harden", "tool": "ecc", "state": StateEnum.Success.value},
            ],
        },
    )
    _write_json(workspace_dir / "home" / "checklist.json", {"checklist": []})

    _write_json(
        workspace_dir / "config" / "sta.json",
        {
            "liberty": [{"corner": "MAX", "temperature": 125, "path": ["max.lib"]}],
            "signoff": [{"MAX": ["RCworst"]}],
        },
    )
    for config_name in ("db_default_config.json", "flow_config.json", "rcx.json"):
        _write_json(workspace_dir / "config" / config_name, {})

    _write(workspace_dir / "Harden_ecc" / "output" / f"{design}_Harden.gds")
    _write(workspace_dir / "Harden_ecc" / "output" / f"{design}_Harden.lef")
    _write(workspace_dir / "Harden_ecc" / "output" / f"{design}_Harden.lib")
    _write(workspace_dir / "filler_ecc" / "output" / f"{design}_filler.v.gz")
    _write(workspace_dir / "filler_ecc" / "output" / f"{design}_filler.def.gz")
    _write(workspace_dir / "filler_ecc" / "output" / f"{design}_filler.gds")
    _write(workspace_dir / "filler_ecc" / "output" / f"{design}_filler.png")
    _write(
        workspace_dir / "RCX_ecc" / "output" / f"{top_module}_RCworst_125C.spef"
    )

    sta_dir = workspace_dir / "sta_ecc" / "output" / "MAX_125" / "RCworst"
    _write(sta_dir / "qor_summary.rpt", "qor summary\n")
    _write(sta_dir / "timing_max_reg2reg.rpt", "max paths\n")
    _write(sta_dir / "timing_min_reg2reg.rpt", "min paths\n")

    _write_json(workspace_dir / "route_ecc" / "analysis" / "route_metrics.json", {})
    _write(workspace_dir / "route_ecc" / "report" / "route.db.rpt")
    return workspace_dir


def _make_engine_flow(
    workspace_dir: Path,
    design: str = "gcd",
    top_module: str = "gcd",
) -> EngineFlow:
    workspace = Workspace()
    workspace.directory = str(workspace_dir)
    workspace.design = OriginDesign(name=design, top_module=top_module)
    workspace.flow.path = str(workspace_dir / "home" / "flow.json")
    workspace.parameters = Parameters(
        path=str(workspace_dir / "home" / "parameters.json"),
        data={"Design": design, "Top module": top_module, "PDK": "ics55"},
    )
    return EngineFlow(workspace=workspace)


def test_collect_signoff_package_uses_final_design_layout(tmp_path):
    workspace_dir = _make_signoff_workspace(tmp_path)
    engine_flow = _make_engine_flow(workspace_dir)

    result = engine_flow.collect_signoff_package(SignoffPackageOptions(archive=True))

    package_dir = Path(result.package_dir)
    assert result.ok is True
    assert (package_dir / "final" / "design" / "gcd.v.gz").is_file()
    assert (package_dir / "final" / "design" / "gcd.def.gz").is_file()
    assert (package_dir / "final" / "design" / "gcd.gds").is_file()
    assert (package_dir / "final" / "design" / "gcd.png").is_file()
    assert (package_dir / "final" / "timing" / "spef" / "gcd_RCworst_125C.spef").is_file()
    assert (package_dir / "final" / "reports" / "flow.json").is_file()
    assert not (package_dir / "signoff").exists()
    assert not (package_dir / "final" / "final").exists()

    summary = json.loads((package_dir / "summary.json").read_text())
    assert summary["final"]["verilog"] == "final/design/gcd.v.gz"
    assert summary["sta_matrix"][0]["report"] == (
        "final/timing/sta/MAX_125/RCworst/qor_summary.rpt"
    )

    manifest = json.loads((package_dir / "manifest.json").read_text())
    destinations = {item["destination"] for item in manifest["files"]}
    assert "final/design/gcd.def.gz" in destinations
    assert "final/reports/route/analysis/route_metrics.json" in destinations
    assert "final/timing/sta/MAX_125/RCworst/qor_summary.rpt" in destinations
    assert "final/timing/sta/MAX_125/RCworst/timing_max_reg2reg.rpt" in destinations
    assert "final/timing/sta/MAX_125/RCworst/timing_min_reg2reg.rpt" in destinations


def test_collect_signoff_package_uses_top_module_for_rcx_spef(tmp_path):
    design = "project_gcd_ws_0002"
    top_module = "gcd"
    workspace_dir = _make_signoff_workspace(tmp_path, design, top_module)
    engine_flow = _make_engine_flow(workspace_dir, design, top_module)

    result = engine_flow.collect_signoff_package(SignoffPackageOptions(archive=False))

    package_dir = Path(result.package_dir)
    assert result.ok is True
    assert (
        package_dir / "final" / "timing" / "spef" / "gcd_RCworst_125C.spef"
    ).is_file()


def test_collect_signoff_package_requires_qor_summary_for_each_sta_corner(tmp_path):
    workspace_dir = _make_signoff_workspace(tmp_path)
    (
        workspace_dir
        / "sta_ecc"
        / "output"
        / "MAX_125"
        / "RCworst"
        / "qor_summary.rpt"
    ).unlink()
    engine_flow = _make_engine_flow(workspace_dir)

    result = engine_flow.collect_signoff_package(SignoffPackageOptions(archive=False))

    assert result.ok is False
    assert (
        "final/timing/sta/MAX_125/RCworst/qor_summary.rpt"
        in result.missing_required
    )
