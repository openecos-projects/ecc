import json
from pathlib import Path

from chipcompiler.data import OriginDesign, Parameters, StateEnum, Workspace
from chipcompiler.engine import EngineFlow
from chipcompiler.engine.signoff import SignoffPackageOptions

STA_REPORT_NAMES = (
    "qor_summary.rpt",
    "timing_max.rpt",
    "power.rpt",
)


def _write(path: Path, text: str = "data") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _write_json(path: Path, data: dict) -> None:
    _write(path, json.dumps(data, indent=2))


def _qor_summary(*gates: dict) -> dict:
    return {
        "schema_version": 4,
        "analysis_revision": "quality-gates-v4",
        "analysis_status": "valid",
        "quality_status": "pass",
        "gates": list(gates),
        "missing_metrics": [],
    }


def _qor_gate(gate_id: str, title: str) -> dict:
    return {
        "id": gate_id,
        "title": title,
        "state": "pass",
        "blocking": True,
        "metrics": [],
        "evidence": [],
    }


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
                {"name": "lvs", "tool": "ecc", "state": StateEnum.Success.value},
                {"name": "filler", "tool": "ecc", "state": StateEnum.Success.value},
                {"name": "RCX", "tool": "ecc", "state": StateEnum.Success.value},
                {"name": "sta", "tool": "ecc", "state": StateEnum.Success.value},
                {"name": "Harden", "tool": "ecc", "state": StateEnum.Success.value},
            ],
        },
    )
    _write_json(workspace_dir / "home" / "checklist.json", {"checklist": []})

    _write_json(
        workspace_dir / "config" / "sta_ecc.json",
        {
            "liberty": [{"corner": "MAX", "temperature": 125, "path": ["max.lib"]}],
            "signoff": [{"MAX": ["RCworst"]}],
        },
    )
    for config_name in ("db_ecc.json", "rcx_ecc.json"):
        _write_json(workspace_dir / "config" / config_name, {})

    _write(workspace_dir / "Harden_ecc" / "output" / f"{design}_Harden.gds")
    _write(workspace_dir / "Harden_ecc" / "output" / f"{design}_Harden.lef")
    _write(workspace_dir / "Harden_ecc" / "output" / f"{design}_Harden.lib")
    _write(workspace_dir / "Synthesis_yosys" / "output" / f"{design}_Synthesis.v.gz")
    _write(workspace_dir / "filler_ecc" / "output" / f"{design}_filler.v.gz")
    _write(workspace_dir / "filler_ecc" / "output" / f"{design}_filler.def.gz")
    _write(workspace_dir / "filler_ecc" / "output" / f"{design}_filler.gds")
    _write(workspace_dir / "filler_ecc" / "output" / f"{design}_filler.png")
    _write(workspace_dir / "RCX_ecc" / "output" / f"{top_module}_RCworst_125C.spef")

    sta_dir = workspace_dir / "sta_ecc" / "report" / "MAX_125" / "RCworst"
    for report_name in STA_REPORT_NAMES:
        _write(sta_dir / report_name, f"{report_name}\n")
    _write_json(
        workspace_dir / "sta_ecc" / "feature" / "MAX_125" / "RCworst" / "qor_summary.json",
        {"path_groups": [], "summary": {"setup": {}, "hold": {}}},
    )
    _write_json(
        workspace_dir / "sta_ecc" / "feature" / "MAX_125" / "RCworst" / "timing_paths.json",
        {"schema_version": 1, "corner": "MAX_125/RCworst", "path_limit": 20, "paths": []},
    )

    _write_json(
        workspace_dir / "route_ecc" / "analysis" / "qor_metrics.json",
        {
            "schema_version": 3,
            "metrics": [],
            "details": [],
            "sources": [],
        },
    )
    _write_json(
        workspace_dir / "drc_ecc" / "analysis" / "qor_metrics.json",
        {
            "schema_version": 3,
            "metrics": [
                {
                    "id": "drc_count",
                    "value": 0,
                    "unit": "count",
                }
            ],
            "details": [],
            "sources": [],
        },
    )
    _write_json(
        workspace_dir / "drc_ecc" / "analysis" / "qor_summary.json",
        _qor_summary(_qor_gate("qor.drc.clean", "Final DRC clean")),
    )
    _write_json(
        workspace_dir / "lvs_ecc" / "analysis" / "qor_summary.json",
        _qor_summary(_qor_gate("qor.lvs.clean", "Final LVS clean")),
    )
    _write_json(
        workspace_dir / "RCX_ecc" / "analysis" / "qor_summary.json",
        _qor_summary(
            _qor_gate("qor.rcx.corner_coverage", "RCX corner coverage"),
            _qor_gate("qor.rcx.spef_parse_health", "RCX SPEF integrity"),
        ),
    )
    _write_json(
        workspace_dir / "sta_ecc" / "analysis" / "qor_summary.json",
        _qor_summary(
            _qor_gate("qor.sta.setup_closed", "STA setup closure"),
            _qor_gate("qor.sta.hold_closed", "STA hold closure"),
        ),
    )
    _write(workspace_dir / "route_ecc" / "report" / "route.db.rpt")
    return workspace_dir


def _make_engine_flow(
    workspace_dir: Path,
    design: str = "gcd",
    top_module: str = "gcd",
) -> EngineFlow:
    workspace = Workspace()
    workspace.directory = str(workspace_dir)
    workspace.design = OriginDesign(
        name=design,
        top_module=top_module,
        origin_verilog=workspace_dir / "origin" / f"{top_module}.v",
    )
    workspace.pdk.sdc = workspace_dir / "origin" / f"{top_module}.sdc"
    workspace.config = {
        "db": workspace_dir / "config" / "db_ecc.json",
        "RCX": workspace_dir / "config" / "rcx_ecc.json",
        "sta": workspace_dir / "config" / "sta_ecc.json",
    }
    workspace.flow.path = workspace_dir / "home" / "flow.json"
    workspace.flow.data = json.loads(workspace.flow.path.read_text(encoding="utf-8"))
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
    assert (package_dir / "synthesis" / "gcd.v.gz").is_file()
    assert (package_dir / "final" / "design" / "gcd.v.gz").is_file()
    assert (package_dir / "final" / "design" / "gcd.def.gz").is_file()
    assert (package_dir / "final" / "design" / "gcd.gds").is_file()
    assert (package_dir / "final" / "design" / "gcd.png").is_file()
    assert (package_dir / "final" / "timing" / "spef" / "gcd_RCworst_125C.spef").is_file()
    assert (package_dir / "final" / "reports" / "flow.json").is_file()
    assert not (package_dir / "signoff").exists()
    assert not (package_dir / "final" / "final").exists()

    summary = json.loads((package_dir / "summary.json").read_text())
    assert summary["initial"]["verilog"] == "initial/gcd.v"
    assert summary["synthesis"]["verilog"] == "synthesis/gcd.v.gz"
    assert summary["final"]["verilog"] == "final/design/gcd.v.gz"
    assert summary["qor_metrics"]["schema_version"] == 3
    assert (
        summary["sta_matrix"][0]["report"]
        == "final/timing/sta/MAX_125/RCworst/report/qor_summary.rpt"
    )
    assert summary["sta_matrix"][0]["qor_summary"] == (
        "final/timing/sta/MAX_125/RCworst/feature/qor_summary.json"
    )
    assert summary["sta_matrix"][0]["timing_paths"] == (
        "final/timing/sta/MAX_125/RCworst/feature/timing_paths.json"
    )

    manifest = json.loads((package_dir / "manifest.json").read_text())
    destinations = {item["destination"] for item in manifest["files"]}
    assert "synthesis/gcd.v.gz" in destinations
    roles = {item["destination"]: item["role"] for item in manifest["files"]}
    assert roles["synthesis/gcd.v.gz"] == "synthesis.verilog"
    assert "final/design/gcd.def.gz" in destinations
    assert "final/reports/route/analysis/qor_metrics.json" in destinations
    assert {
        f"final/timing/sta/MAX_125/RCworst/report/{report_name}" for report_name in STA_REPORT_NAMES
    }.issubset(destinations)
    assert {
        "final/timing/sta/MAX_125/RCworst/feature/qor_summary.json",
        "final/timing/sta/MAX_125/RCworst/feature/timing_paths.json",
    }.issubset(destinations)
    assert all(".tsv" not in destination for destination in destinations)


def test_collect_signoff_package_requires_synthesis_verilog(tmp_path):
    workspace_dir = _make_signoff_workspace(tmp_path)
    (workspace_dir / "Synthesis_yosys" / "output" / "gcd_Synthesis.v.gz").unlink()

    result = _make_engine_flow(workspace_dir).collect_signoff_package(
        SignoffPackageOptions(archive=False, materialize=False)
    )

    assert result.ok is False
    assert "package.synthesis.gcd.v.gz" in result.missing_required
    assert any(
        issue.label == "synthesis.verilog"
        and issue.location == "Synthesis_yosys/output/gcd_Synthesis.v.gz"
        and issue.destination == "synthesis/gcd.v.gz"
        and issue.required
        for issue in result.issues
    )


def test_collect_signoff_package_uses_origin_rtl_for_floorplan_start(tmp_path):
    workspace_dir = _make_signoff_workspace(tmp_path)
    (workspace_dir / "Synthesis_yosys" / "output" / "gcd_Synthesis.v.gz").unlink()
    _write(
        workspace_dir / "origin" / "gcd.v",
        "module gcd; // original imported RTL\nendmodule\n",
    )
    flow = json.loads((workspace_dir / "home" / "flow.json").read_text())
    flow["steps"].insert(
        0,
        {"name": "Floorplan", "tool": "ecc", "state": StateEnum.Success.value},
    )
    _write_json(workspace_dir / "home" / "flow.json", flow)
    engine_flow = _make_engine_flow(workspace_dir)
    external_rtl = tmp_path / "external" / "gcd.v"
    _write(external_rtl, "module gcd; // outside the workspace\nendmodule\n")
    engine_flow.workspace.design.origin_verilog = external_rtl

    result = engine_flow.collect_signoff_package(SignoffPackageOptions(archive=True))

    assert result.ok is True
    package_dir = Path(result.package_dir)
    assert (package_dir / "initial" / "gcd.v").read_text() == (
        "module gcd; // original imported RTL\nendmodule\n"
    )
    assert not (package_dir / "synthesis" / "gcd.v.gz").exists()
    summary = json.loads((package_dir / "summary.json").read_text())
    assert summary["initial"]["verilog"] == "initial/gcd.v"
    assert "synthesis" not in summary


def test_collect_signoff_package_tolerates_missing_sta_power_report(tmp_path):
    # Workspaces completed before power collection have no per-corner power.rpt;
    # it is packaged when present but must not be required for export.
    workspace_dir = _make_signoff_workspace(tmp_path)
    (workspace_dir / "sta_ecc" / "report" / "MAX_125" / "RCworst" / "power.rpt").unlink()
    engine_flow = _make_engine_flow(workspace_dir)

    result = engine_flow.collect_signoff_package(SignoffPackageOptions(archive=True))

    assert result.ok is True
    manifest = json.loads((Path(result.package_dir) / "manifest.json").read_text())
    destinations = {item["destination"] for item in manifest["files"]}
    assert "final/timing/sta/MAX_125/RCworst/report/power.rpt" not in destinations


def test_collect_signoff_package_uses_top_module_for_rcx_spef(tmp_path):
    design = "project_gcd_ws_0002"
    top_module = "gcd"
    workspace_dir = _make_signoff_workspace(tmp_path, design, top_module)
    engine_flow = _make_engine_flow(workspace_dir, design, top_module)

    result = engine_flow.collect_signoff_package(SignoffPackageOptions(archive=False))

    package_dir = Path(result.package_dir)
    assert result.ok is True
    assert (package_dir / "final" / "timing" / "spef" / "gcd_RCworst_125C.spef").is_file()


def test_collect_signoff_package_requires_qor_summary_for_each_sta_corner(tmp_path):
    workspace_dir = _make_signoff_workspace(tmp_path)
    (workspace_dir / "sta_ecc" / "report" / "MAX_125" / "RCworst" / "qor_summary.rpt").unlink()
    engine_flow = _make_engine_flow(workspace_dir)

    result = engine_flow.collect_signoff_package(SignoffPackageOptions(archive=False))

    assert result.ok is False
    assert any(
        issue.location == "sta_ecc/report/MAX_125/RCworst/qor_summary.rpt" and issue.required
        for issue in result.issues
    )


def test_collect_signoff_package_requires_each_sta_path_report(tmp_path):
    workspace_dir = _make_signoff_workspace(tmp_path)
    report_name = "timing_max.rpt"
    (workspace_dir / "sta_ecc" / "report" / "MAX_125" / "RCworst" / report_name).unlink()

    result = _make_engine_flow(workspace_dir).collect_signoff_package(
        SignoffPackageOptions(archive=False, materialize=False)
    )

    assert result.ok is False
    assert any(
        issue.location == f"sta_ecc/report/MAX_125/RCworst/{report_name}" and issue.required
        for issue in result.issues
    )


def test_collect_signoff_package_requires_each_sta_structured_artifact(tmp_path):
    workspace_dir = _make_signoff_workspace(tmp_path)
    timing_paths = (
        workspace_dir / "sta_ecc" / "feature" / "MAX_125" / "RCworst" / "timing_paths.json"
    )
    timing_paths.unlink()

    result = _make_engine_flow(workspace_dir).collect_signoff_package(
        SignoffPackageOptions(archive=False, materialize=False)
    )

    assert result.ok is False
    assert any(
        issue.location == "sta_ecc/feature/MAX_125/RCworst/timing_paths.json" and issue.required
        for issue in result.issues
    )


def test_collect_signoff_package_rejects_obsolete_sta_output_directory(tmp_path):
    workspace_dir = _make_signoff_workspace(tmp_path)
    report_root = workspace_dir / "sta_ecc" / "report"
    output_root = workspace_dir / "sta_ecc" / "output"
    report_root.rename(output_root)

    result = _make_engine_flow(workspace_dir).collect_signoff_package(
        SignoffPackageOptions(archive=False, materialize=False)
    )

    assert result.ok is False
    assert any(
        issue.location == "sta_ecc/report/MAX_125/RCworst/qor_summary.rpt" and issue.required
        for issue in result.issues
    )


def test_collect_signoff_package_ignores_harden_tsv_resource(tmp_path):
    workspace_dir = _make_signoff_workspace(tmp_path)

    result = _make_engine_flow(workspace_dir).collect_signoff_package(
        SignoffPackageOptions(archive=False, materialize=False)
    )

    assert result.ok is True
    assert all(".tsv" not in destination for destination in result.missing_optional)
    assert all(".tsv" not in issue.destination for issue in result.issues)


def test_collect_signoff_package_inspection_does_not_materialize_resources(tmp_path):
    workspace_dir = _make_signoff_workspace(tmp_path)

    result = _make_engine_flow(workspace_dir).collect_signoff_package(
        SignoffPackageOptions(archive=False, materialize=False)
    )

    assert result.ok is True
    assert result.copied[0]["size_bytes"] > 0
    assert result.copied[0]["sha256"] is None
    assert not Path(result.package_dir).exists()


def test_collect_signoff_package_inspection_records_missing_optional_resource(tmp_path):
    workspace_dir = _make_signoff_workspace(tmp_path)
    (workspace_dir / "filler_ecc" / "output" / "gcd_filler.png").unlink()

    result = _make_engine_flow(workspace_dir).collect_signoff_package(
        SignoffPackageOptions(archive=False, materialize=False)
    )

    assert result.ok is True
    assert "package.final.design.gcd.png" in result.missing_optional


def test_collect_signoff_package_reports_actionable_inspection_issues(tmp_path):
    workspace_dir = _make_signoff_workspace(tmp_path)
    (workspace_dir / "Harden_ecc" / "output" / "gcd_Harden.gds").unlink()
    _write_json(
        workspace_dir / "home" / "flow.json",
        {"steps": [{"name": "RCX", "state": "Failed"}]},
    )
    result = _make_engine_flow(workspace_dir).collect_signoff_package(
        SignoffPackageOptions(archive=False, materialize=False)
    )

    assert {issue.kind for issue in result.issues} == {
        "resource",
        "flow",
    }
    assert any(
        issue.location == "Harden_ecc/output/gcd_Harden.gds"
        and issue.reason == "Required file is missing or empty"
        and issue.required
        for issue in result.issues
    )
    assert any(
        issue.location == "RCX" and issue.reason == "State is Failed" for issue in result.issues
    )
    assert all(str(workspace_dir) not in issue.location for issue in result.issues)


def test_collect_signoff_package_accepts_systemverilog_origin(tmp_path):
    # load_workspace restores neither input_filelist nor .sv sources, so the
    # collector must rediscover the RTL by globbing the origin directory.
    workspace_dir = _make_signoff_workspace(tmp_path)
    (workspace_dir / "origin" / "gcd.v").unlink()
    _write(workspace_dir / "origin" / "gcd.sv", "module gcd; endmodule\n")
    engine_flow = _make_engine_flow(workspace_dir)
    engine_flow.workspace.design.origin_verilog = None

    result = engine_flow.collect_signoff_package(SignoffPackageOptions(archive=True))

    assert result.ok is True
    package_dir = Path(result.package_dir)
    assert (package_dir / "initial" / "gcd.sv").is_file()
    summary = json.loads((package_dir / "summary.json").read_text())
    assert summary["initial"]["verilog"] == "initial/gcd.sv"


def test_collect_signoff_package_bundles_filelist_sources(tmp_path):
    workspace_dir = _make_signoff_workspace(tmp_path)
    (workspace_dir / "origin" / "gcd.v").unlink()
    _write(workspace_dir / "origin" / "gcd.f", "rtl/gcd.sv\ngcd_pkg.sv\n")
    _write(workspace_dir / "origin" / "rtl" / "gcd.sv", "module gcd; endmodule\n")
    _write(workspace_dir / "origin" / "gcd_pkg.sv", "package gcd_pkg; endpackage\n")
    engine_flow = _make_engine_flow(workspace_dir)
    engine_flow.workspace.design.origin_verilog = None

    result = engine_flow.collect_signoff_package(SignoffPackageOptions(archive=True))

    assert result.ok is True
    package_dir = Path(result.package_dir)
    assert (package_dir / "initial" / "gcd.f").is_file()
    assert (package_dir / "initial" / "rtl" / "gcd.sv").is_file()
    assert (package_dir / "initial" / "gcd_pkg.sv").is_file()
    summary = json.loads((package_dir / "summary.json").read_text())
    assert summary["initial"]["verilog"] == "initial/gcd.f"
    manifest = json.loads((package_dir / "manifest.json").read_text())
    roles = {item["destination"]: item["role"] for item in manifest["files"]}
    assert roles["initial/gcd.f"] == "initial.filelist"
    assert roles["initial/rtl/gcd.sv"] == "initial.verilog"
    assert roles["initial/gcd_pkg.sv"] == "initial.verilog"


def test_collect_signoff_package_blocks_missing_origin_rtl(tmp_path):
    workspace_dir = _make_signoff_workspace(tmp_path)
    (workspace_dir / "origin" / "gcd.v").unlink()

    result = _make_engine_flow(workspace_dir).collect_signoff_package(
        SignoffPackageOptions(archive=False, materialize=False)
    )

    assert result.ok is False
    assert "package.initial.gcd.v" in result.missing_required
    assert any(
        issue.label == "Origin RTL"
        and issue.location == "origin/gcd.v"
        and issue.destination == "initial/gcd.v"
        and issue.required
        for issue in result.issues
    )


def test_collect_signoff_package_bundles_suffixless_filelist(tmp_path):
    # WorkspaceRuntimeApi writes generated filelists as origin/filelist with no
    # suffix; the configured attribute, not the suffix, marks it as a filelist.
    workspace_dir = _make_signoff_workspace(tmp_path)
    (workspace_dir / "origin" / "gcd.v").unlink()
    _write(workspace_dir / "origin" / "filelist", "rtl/gcd.sv\n")
    _write(workspace_dir / "origin" / "rtl" / "gcd.sv", "module gcd; endmodule\n")
    engine_flow = _make_engine_flow(workspace_dir)
    engine_flow.workspace.design.origin_verilog = None
    engine_flow.workspace.design.input_filelist = workspace_dir / "origin" / "filelist"

    result = engine_flow.collect_signoff_package(SignoffPackageOptions(archive=True))

    assert result.ok is True
    package_dir = Path(result.package_dir)
    assert (package_dir / "initial" / "gcd").is_file()
    assert (package_dir / "initial" / "rtl" / "gcd.sv").is_file()
    manifest = json.loads((package_dir / "manifest.json").read_text())
    roles = {item["destination"]: item["role"] for item in manifest["files"]}
    assert roles["initial/gcd"] == "initial.filelist"
    assert roles["initial/rtl/gcd.sv"] == "initial.verilog"


def test_collect_signoff_package_blocks_unparseable_filelist(tmp_path):
    workspace_dir = _make_signoff_workspace(tmp_path)
    (workspace_dir / "origin" / "gcd.v").unlink()
    _write(workspace_dir / "origin" / "gcd.f", "-f nested.f\n")
    engine_flow = _make_engine_flow(workspace_dir)
    engine_flow.workspace.design.origin_verilog = None

    result = engine_flow.collect_signoff_package(
        SignoffPackageOptions(archive=False, materialize=False)
    )

    assert result.ok is False
    assert any(issue.label == "Origin RTL sources" and issue.required for issue in result.issues)


def test_collect_signoff_package_blocks_escaping_filelist_entries(tmp_path):
    # The source exists outside origin/, so without the containment guard the
    # entry would be copied to an escaped destination and the export would pass.
    workspace_dir = _make_signoff_workspace(tmp_path)
    (workspace_dir / "origin" / "gcd.v").unlink()
    _write(workspace_dir / "origin" / "gcd.f", "../escape.sv\n")
    _write(workspace_dir / "escape.sv", "module escape; endmodule\n")
    engine_flow = _make_engine_flow(workspace_dir)
    engine_flow.workspace.design.origin_verilog = None

    result = engine_flow.collect_signoff_package(SignoffPackageOptions(archive=True))

    assert result.ok is False
    assert any(issue.label == "Origin RTL sources" and issue.required for issue in result.issues)
    assert not (Path(result.package_dir) / "escape.sv").exists()


def test_collect_signoff_package_rewrites_absolute_filelist_entries(tmp_path):
    # Creation copies absolute-entry sources into origin/ by basename; the
    # packaged filelist must reference those basenames to stay resolvable.
    workspace_dir = _make_signoff_workspace(tmp_path)
    (workspace_dir / "origin" / "gcd.v").unlink()
    external = tmp_path / "external" / "gcd.sv"
    _write(external, "module gcd; endmodule\n")
    _write(workspace_dir / "origin" / "gcd.f", f'"{external}"  # top\n')
    _write(workspace_dir / "origin" / "gcd.sv", "module gcd; endmodule\n")
    engine_flow = _make_engine_flow(workspace_dir)
    engine_flow.workspace.design.origin_verilog = None

    result = engine_flow.collect_signoff_package(SignoffPackageOptions(archive=True))

    assert result.ok is True
    package_dir = Path(result.package_dir)
    assert (package_dir / "initial" / "gcd.sv").is_file()
    packaged_filelist = (package_dir / "initial" / "gcd.f").read_text(encoding="utf-8")
    assert packaged_filelist == '"gcd.sv"  # top\n'
