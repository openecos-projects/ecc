import json
from pathlib import Path

import pytest

from chipcompiler.cli.project.rtl_import import RtlImportError, import_project_rtl


def _project(root: Path) -> None:
    (root / "rtl").mkdir(parents=True)
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


def _files(root: Path) -> list[str]:
    return sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file())


def test_import_filelist_brings_its_include_directories_along(tmp_path):
    project = tmp_path / "project"
    _project(project)
    source_root = tmp_path / "sources"
    (source_root / "inc" / "bus").mkdir(parents=True)
    (source_root / "demo.v").write_text('`include "defs.vh"\nmodule demo; endmodule\n')
    (source_root / "inc" / "defs.vh").write_text("`define DEMO 1\n")
    (source_root / "inc" / "bus" / "axi.vh").write_text("`define AXI 1\n")
    filelist = source_root / "sources.f"
    filelist.write_text("+incdir+inc  // headers\ndemo.v\n")

    result = import_project_rtl(str(project), filelist=str(filelist))

    assert _files(project / "rtl") == ["demo.v", "inc/bus/axi.vh", "inc/defs.vh", "sources.f"]
    # The directive already names the project-local directory: kept as written.
    assert (project / "rtl/sources.f").read_text() == "+incdir+inc  // headers\ndemo.v\n"
    assert result["include_dirs"] == ["rtl/inc"]
    # Headers are not sources.
    assert result["rtl"] == ["rtl/demo.v"]
    manifest = json.loads((project / "project.json").read_text())
    assert manifest["base_design"]["rtl_list"] == ["rtl/demo.v"]


def test_import_filelist_localizes_include_directories_outside_its_directory(tmp_path):
    project = tmp_path / "project"
    _project(project)
    source_root = tmp_path / "sources"
    (source_root / "top").mkdir(parents=True)
    (source_root / "shared").mkdir()
    vendor = tmp_path / "vendor" / "include"
    vendor.mkdir(parents=True)
    (source_root / "top" / "demo.v").write_text("module demo; endmodule\n")
    (source_root / "shared" / "defs.vh").write_text("`define DEMO 1\n")
    (vendor / "cells.vh").write_text("`define CELLS 1\n")
    filelist = source_root / "top" / "sources.f"
    filelist.write_text(f'+incdir+../shared\n+incdir+"{vendor}"  # vendor\ndemo.v\n')

    result = import_project_rtl(str(project), filelist=str(filelist))

    assert _files(project / "rtl") == [
        "demo.v",
        "include/cells.vh",
        "shared/defs.vh",
        "sources.f",
    ]
    assert (project / "rtl/sources.f").read_text() == (
        '+incdir+shared\n+incdir+"include"  # vendor\ndemo.v\n'
    )
    assert result["include_dirs"] == ["rtl/shared", "rtl/include"]


def test_import_filelist_copies_a_header_once_when_it_is_also_listed(tmp_path):
    project = tmp_path / "project"
    _project(project)
    source_root = tmp_path / "sources"
    (source_root / "common").mkdir(parents=True)
    (source_root / "demo.v").write_text("module demo; endmodule\n")
    (source_root / "common" / "defs.vh").write_text("`define DEMO 1\n")
    filelist = source_root / "sources.f"
    filelist.write_text("+incdir+common\n+incdir+./common\ndemo.v\ncommon/defs.vh\n")

    result = import_project_rtl(str(project), filelist=str(filelist))

    assert _files(project / "rtl") == ["common/defs.vh", "demo.v", "sources.f"]
    assert result["include_dirs"] == ["rtl/common"]
    assert result["rtl"] == ["rtl/demo.v", "rtl/common/defs.vh"]


def test_import_filelist_with_its_own_directory_as_include_directory(tmp_path):
    # `+incdir+.` takes the whole source directory; a project created inside
    # it must not be copied into itself.
    source_root = tmp_path / "sources"
    project = source_root / "project"
    _project(project)
    (source_root / "demo.v").write_text("module demo; endmodule\n")
    (source_root / "defs.vh").write_text("`define DEMO 1\n")
    filelist = source_root / "sources.f"
    filelist.write_text("+incdir+.\ndemo.v\n")

    result = import_project_rtl(str(project), filelist=str(filelist))

    assert _files(project / "rtl") == ["defs.vh", "demo.v", "sources.f"]
    assert (project / "rtl/sources.f").read_text() == "+incdir+.\ndemo.v\n"
    assert result["include_dirs"] == ["rtl"]


def test_import_filelist_rejects_a_missing_include_directory(tmp_path):
    project = tmp_path / "project"
    _project(project)
    source_root = tmp_path / "sources"
    source_root.mkdir()
    (source_root / "demo.v").write_text("module demo; endmodule\n")
    filelist = source_root / "sources.f"
    filelist.write_text("+incdir+missing\ndemo.v\n")
    config = (project / "ecc.toml").read_text()

    with pytest.raises(RtlImportError) as error:
        import_project_rtl(str(project), filelist=str(filelist))

    assert error.value.code == "rtl_incdir_not_found"
    assert error.value.path == str(source_root / "missing")
    # Nothing was imported.
    assert _files(project / "rtl") == []
    assert (project / "ecc.toml").read_text() == config


def test_import_filelist_rejects_include_directories_that_would_merge(tmp_path):
    project = tmp_path / "project"
    _project(project)
    source_root = tmp_path / "sources"
    source_root.mkdir()
    (source_root / "demo.v").write_text("module demo; endmodule\n")
    for owner in ("a", "b"):
        (tmp_path / owner / "include").mkdir(parents=True)
        (tmp_path / owner / "include" / "defs.vh").write_text(f"`define OWNER_{owner} 1\n")
    filelist = source_root / "sources.f"
    filelist.write_text(f"+incdir+{tmp_path}/a/include\n+incdir+{tmp_path}/b/include\ndemo.v\n")

    with pytest.raises(RtlImportError) as error:
        import_project_rtl(str(project), filelist=str(filelist))

    assert error.value.code == "rtl_target_collision"
    assert _files(project / "rtl") == []


def test_import_verilog_reports_no_include_directories(tmp_path):
    project = tmp_path / "project"
    _project(project)
    source = tmp_path / "demo.v"
    source.write_text("module demo; endmodule\n")

    result = import_project_rtl(str(project), verilog=(str(source),))

    assert result["include_dirs"] is None


def _project_with_headers_to_import(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A project, a filelist with ``+incdir+inc`` and a directory outside the project."""
    project = tmp_path / "project"
    _project(project)
    source_root = tmp_path / "sources"
    (source_root / "inc" / "nested").mkdir(parents=True)
    (source_root / "demo.v").write_text("module demo; endmodule\n")
    (source_root / "inc" / "nested" / "defs.vh").write_text("`define DEMO 1\n")
    filelist = source_root / "sources.f"
    filelist.write_text("+incdir+inc\ndemo.v\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    return project, filelist, outside


def test_import_filelist_keeps_include_files_inside_rtl_behind_a_directory_link(tmp_path):
    project, filelist, outside = _project_with_headers_to_import(tmp_path)
    (project / "rtl" / "inc").mkdir()
    (project / "rtl" / "inc" / "nested").symlink_to(outside, target_is_directory=True)

    with pytest.raises(RtlImportError) as error:
        import_project_rtl(str(project), filelist=str(filelist))

    assert error.value.code == "rtl_path_escape"
    assert list(outside.iterdir()) == []
    # Refused before anything is copied: the listed source is not there either.
    assert _files(project / "rtl") == []


def test_import_filelist_does_not_replace_a_file_outside_rtl_through_a_link(tmp_path):
    project, filelist, outside = _project_with_headers_to_import(tmp_path)
    victim = outside / "victim.vh"
    victim.write_text("keep me\n")
    (project / "rtl" / "inc" / "nested").mkdir(parents=True)
    (project / "rtl" / "inc" / "nested" / "defs.vh").symlink_to(victim)

    with pytest.raises(RtlImportError) as error:
        import_project_rtl(str(project), filelist=str(filelist), force=True)

    assert error.value.code == "rtl_path_escape"
    assert victim.read_text() == "keep me\n"


def test_import_filelist_follows_a_link_that_stays_inside_rtl(tmp_path):
    project, filelist, _outside = _project_with_headers_to_import(tmp_path)
    (project / "rtl" / "headers").mkdir()
    (project / "rtl" / "inc").mkdir()
    (project / "rtl" / "inc" / "nested").symlink_to(
        project / "rtl" / "headers", target_is_directory=True
    )

    import_project_rtl(str(project), filelist=str(filelist))

    assert (project / "rtl" / "headers" / "defs.vh").read_text() == "`define DEMO 1\n"


def test_import_filelist_does_not_copy_its_own_output_again(tmp_path):
    """The include directory is the project root: ``rtl/`` holds the previous import."""
    project = tmp_path / "project"
    _project(project)
    (project / "demo.v").write_text("module demo; endmodule\n")
    (project / "defs.vh").write_text("`define DEMO 1\n")
    filelist = project / "sources.f"
    filelist.write_text("+incdir+.\ndemo.v\n")

    for force in (False, True, True):
        import_project_rtl(str(project), filelist=str(filelist), force=force)

    imported = _files(project / "rtl")
    assert {"defs.vh", "demo.v"} <= set(imported)
    assert not (project / "rtl" / "rtl").exists()
    assert [name for name in imported if name.startswith("rtl/")] == []


def test_import_filelist_rejects_a_source_named_like_an_include_directory(tmp_path):
    """``rtl/inc`` cannot be both a copied file and the directory of the headers."""
    project = tmp_path / "project"
    _project(project)
    source_root = tmp_path / "sources"
    (source_root / "inc").mkdir(parents=True)
    (source_root / "inc" / "defs.vh").write_text("`define DEMO 1\n")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "inc").write_text("module inc; endmodule\n")
    filelist = source_root / "sources.f"
    filelist.write_text(f"+incdir+inc\n{elsewhere / 'inc'}\n")

    with pytest.raises(RtlImportError) as error:
        import_project_rtl(str(project), filelist=str(filelist))

    assert error.value.code == "rtl_target_collision"
    # Refused before anything is copied.
    assert _files(project / "rtl") == []


def test_import_filelist_copies_headers_reached_through_a_directory_link(tmp_path):
    """``inc/alias -> real``: an include of ``alias/defs.vh`` still resolves after the import."""
    project = tmp_path / "project"
    _project(project)
    source_root = tmp_path / "sources"
    (source_root / "inc" / "real").mkdir(parents=True)
    (source_root / "inc" / "real" / "defs.vh").write_text("`define DEMO 1\n")
    (source_root / "inc" / "alias").symlink_to("real", target_is_directory=True)
    # A link back to a parent directory must not send the walk in circles.
    (source_root / "inc" / "real" / "up").symlink_to(source_root / "inc", target_is_directory=True)
    (source_root / "demo.v").write_text('`include "alias/defs.vh"\nmodule demo; endmodule\n')
    filelist = source_root / "sources.f"
    filelist.write_text("+incdir+inc\ndemo.v\n")

    import_project_rtl(str(project), filelist=str(filelist))

    assert (project / "rtl" / "inc" / "alias" / "defs.vh").read_text() == "`define DEMO 1\n"
    assert (project / "rtl" / "inc" / "real" / "defs.vh").read_text() == "`define DEMO 1\n"
    assert not (project / "rtl" / "inc" / "real" / "up").exists()


def test_import_filelist_stops_at_directory_links_that_point_at_each_other(tmp_path):
    """``inc/a/to_b -> ../b`` and ``inc/b/to_a -> ../a``: the walk ends, the headers arrive."""
    project = tmp_path / "project"
    _project(project)
    source_root = tmp_path / "sources"
    for name in ("a", "b"):
        (source_root / "inc" / name).mkdir(parents=True)
        (source_root / "inc" / name / f"{name}.vh").write_text(f"`define {name.upper()} 1\n")
    (source_root / "inc" / "a" / "to_b").symlink_to("../b", target_is_directory=True)
    (source_root / "inc" / "b" / "to_a").symlink_to("../a", target_is_directory=True)
    (source_root / "demo.v").write_text("module demo; endmodule\n")
    filelist = source_root / "sources.f"
    filelist.write_text("+incdir+inc\ndemo.v\n")

    import_project_rtl(str(project), filelist=str(filelist))

    imported = _files(project / "rtl")
    assert {"inc/a/a.vh", "inc/b/b.vh", "inc/a/to_b/b.vh", "inc/b/to_a/a.vh"} <= set(imported)
    assert max(name.count("/") for name in imported) <= 3
