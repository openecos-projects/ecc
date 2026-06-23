import os

from chipcompiler.data.workspace import copy_filelist_with_sources


class TestCopyFilelistWithSources:
    def test_copy_simple_filelist(
        self, tmp_path, workspace_dir, write_rtl_file, create_filelist
    ):
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        write_rtl_file(project_dir / "gcd.v", "gcd")

        filelist = project_dir / "design.f"
        create_filelist(filelist, "gcd.v")

        new_filelist = copy_filelist_with_sources(str(filelist), str(workspace_dir))

        assert os.path.exists(new_filelist)
        assert new_filelist == str(workspace_dir / "origin" / "design.f")

        copied_file = workspace_dir / "origin" / "gcd.v"
        assert copied_file.exists()
        assert copied_file.read_text() == "module gcd(); endmodule"

    def test_copy_nested_structure(
        self, tmp_path, workspace_dir, write_rtl_file, create_filelist
    ):
        project_dir = tmp_path / "project"
        (project_dir / "rtl" / "core").mkdir(parents=True)
        (project_dir / "rtl" / "mem").mkdir(parents=True)

        write_rtl_file(project_dir / "rtl" / "core" / "alu.v", "alu")
        write_rtl_file(project_dir / "rtl" / "core" / "ctrl.v", "ctrl")
        write_rtl_file(project_dir / "rtl" / "mem" / "cache.v", "cache")

        filelist = project_dir / "design.f"
        create_filelist(filelist, "rtl/core/alu.v", "rtl/core/ctrl.v", "rtl/mem/cache.v")

        copy_filelist_with_sources(str(filelist), str(workspace_dir))

        origin_dir = workspace_dir / "origin"
        assert (origin_dir / "rtl" / "core" / "alu.v").exists()
        assert (origin_dir / "rtl" / "core" / "ctrl.v").exists()
        assert (origin_dir / "rtl" / "mem" / "cache.v").exists()
        assert (origin_dir / "rtl" / "core" / "alu.v").read_text() == "module alu(); endmodule"

    def test_copy_with_missing_files(
        self, tmp_path, workspace_dir, write_rtl_file, create_filelist
    ):
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        rtl_dir = project_dir / "rtl"
        rtl_dir.mkdir()
        write_rtl_file(rtl_dir / "top.v", "top")

        filelist = project_dir / "design.f"
        create_filelist(filelist, "rtl/top.v", "rtl/missing.v")

        copy_filelist_with_sources(str(filelist), str(workspace_dir))

        origin_dir = workspace_dir / "origin"
        assert (origin_dir / "rtl" / "top.v").exists()
        assert not (origin_dir / "rtl" / "missing.v").exists()

    def test_copy_with_absolute_paths(self, tmp_path, workspace_dir, write_rtl_file):
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        abs_file = project_dir / "absolute.v"
        write_rtl_file(abs_file, "absolute")

        filelist = project_dir / "design.f"
        filelist.write_text(f"{abs_file}\n")

        copy_filelist_with_sources(str(filelist), str(workspace_dir))

        origin_dir = workspace_dir / "origin"
        assert (origin_dir / "absolute.v").exists()
        assert (origin_dir / "absolute.v").read_text() == "module absolute(); endmodule"


class TestCopyFilelistWithIncdir:
    def test_copy_with_incdir_basic(
        self, tmp_path, write_rtl_file, write_header_file, setup_project_with_incdir,
        copy_filelist_content
    ):
        project_dir = tmp_path / "project"
        rtl_dir, include_dir = setup_project_with_incdir(project_dir)

        write_rtl_file(rtl_dir / "top.v", "top")
        write_header_file(include_dir / "defines.vh", "`define WIDTH 32")

        origin_dir = copy_filelist_content(project_dir, "+incdir+./include\nrtl/top.v\n")

        assert (origin_dir / "rtl" / "top.v").exists()
        assert (origin_dir / "include" / "defines.vh").exists()

    def test_copy_with_incdir_deduplication(
        self, tmp_path, write_rtl_file, write_header_file, copy_filelist_content
    ):
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        write_rtl_file(project_dir / "top.v", "top")
        write_header_file(project_dir / "types.vh", "`define TYPES")

        origin_dir = copy_filelist_content(project_dir, "top.v\n+incdir+./\n")

        assert (origin_dir / "top.v").exists()
        assert (origin_dir / "types.vh").exists()

        verilog_files = list(origin_dir.glob("*.v")) + list(origin_dir.glob("*.vh"))
        assert len(verilog_files) == 2

    def test_copy_with_incdir_nested_structure(
        self, tmp_path, write_rtl_file, write_header_file, setup_project_with_incdir,
        copy_filelist_content
    ):
        project_dir = tmp_path / "project"
        rtl_dir, include_dir = setup_project_with_incdir(project_dir)
        (include_dir / "subdir").mkdir()

        write_rtl_file(rtl_dir / "top.v", "top")
        write_header_file(include_dir / "defines.vh", "`define A")
        write_header_file(include_dir / "subdir" / "params.vh", "`define B")

        origin_dir = copy_filelist_content(project_dir, "+incdir+./include\nrtl/top.v\n")

        assert (origin_dir / "rtl" / "top.v").exists()
        assert (origin_dir / "include" / "defines.vh").exists()
        assert (origin_dir / "include" / "subdir" / "params.vh").exists()

    def test_copy_with_incdir_missing_directory(
        self, tmp_path, write_rtl_file, copy_filelist_content
    ):
        project_dir = tmp_path / "project"
        (project_dir / "rtl").mkdir(parents=True)

        write_rtl_file(project_dir / "rtl" / "top.v", "top")

        origin_dir = copy_filelist_content(
            project_dir, "+incdir+./missing_include\nrtl/top.v\n"
        )

        assert (origin_dir / "rtl" / "top.v").exists()

    def test_copy_with_multiple_incdir(
        self, tmp_path, write_rtl_file, write_header_file, copy_filelist_content
    ):
        project_dir = tmp_path / "project"
        (project_dir / "rtl").mkdir(parents=True)
        (project_dir / "include1").mkdir(parents=True)
        (project_dir / "include2").mkdir(parents=True)

        write_rtl_file(project_dir / "rtl" / "top.v", "top")
        write_header_file(project_dir / "include1" / "defs1.vh", "`define A")
        write_header_file(project_dir / "include2" / "defs2.vh", "`define B")

        origin_dir = copy_filelist_content(
            project_dir,
            "+incdir+./include1\n+incdir+./include2\nrtl/top.v\n",
        )

        assert (origin_dir / "rtl" / "top.v").exists()
        assert (origin_dir / "include1" / "defs1.vh").exists()
        assert (origin_dir / "include2" / "defs2.vh").exists()
