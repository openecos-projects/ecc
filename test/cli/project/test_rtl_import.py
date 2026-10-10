import json
from pathlib import Path

from chipcompiler.cli.project.rtl_import import import_project_rtl


def _project(root: Path) -> None:
    (root / "rtl").mkdir()
    (root / "ecc.toml").write_text(
        '[design]\nname = "demo"\ntop = "demo"\nrtl = ["rtl/demo.v"]\n',
        encoding="utf-8",
    )
    (root / "project.json").write_text(
        json.dumps({"schema_version": 1, "name": "demo", "base_design": {}, "workspaces": []}),
        encoding="utf-8",
    )


def test_import_filelist_preserves_layout_and_rewrites_paths(tmp_path):
    project = tmp_path / "project"
    _project(project)
    source_root = tmp_path / "sources"
    (source_root / "top").mkdir(parents=True)
    (source_root / "common").mkdir()
    (source_root / "top" / "demo.v").write_text("module demo; endmodule\n")
    (source_root / "common" / "defs.vh").write_text("`define DEMO 1\n")
    filelist = source_root / "sources.f"
    filelist.write_text("top/demo.v\ncommon/defs.vh\n")

    result = import_project_rtl(str(project), filelist=str(filelist))

    assert (project / "rtl/sources.f").read_text() == "top/demo.v\ncommon/defs.vh\n"
    assert (project / "rtl/top/demo.v").is_file()
    assert (project / "rtl/common/defs.vh").is_file()
    assert result["filelist"] == "rtl/sources.f"
    assert 'rtl = ["rtl/sources.f"]' in (project / "ecc.toml").read_text()
    manifest = json.loads((project / "project.json").read_text())
    assert manifest["base_design"]["rtl_list"] == ["rtl/top/demo.v", "rtl/common/defs.vh"]


def test_import_verilog_updates_project_inputs(tmp_path):
    project = tmp_path / "project"
    _project(project)
    source = tmp_path / "demo.v"
    source.write_text("module demo; endmodule\n")

    import_project_rtl(str(project), verilog=(str(source),))

    assert (project / "rtl/demo.v").is_file()
    assert 'rtl = ["rtl/demo.v"]' in (project / "ecc.toml").read_text()
