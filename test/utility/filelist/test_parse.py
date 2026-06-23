import os

import pytest

from chipcompiler.utility.filelist import (
    get_filelist_info,
    parse_filelist,
    resolve_path,
    validate_filelist,
)


class TestParseFilelist:
    def test_parse_simple_filelist(self, tmp_path, create_filelist):
        filelist = tmp_path / "design.f"
        create_filelist(filelist, "rtl/gcd.v", "rtl/gcd_pkg.v")

        assert parse_filelist(str(filelist)) == ["rtl/gcd.v", "rtl/gcd_pkg.v"]

    def test_parse_with_comments(self, tmp_path):
        filelist = tmp_path / "design.f"
        filelist.write_text(
            "# This is a comment\n"
            "rtl/top.v\n"
            "// Another comment\n"
            "rtl/sub.v  # inline comment\n"
        )

        assert parse_filelist(str(filelist)) == ["rtl/top.v", "rtl/sub.v"]

    def test_parse_with_empty_lines(self, tmp_path):
        filelist = tmp_path / "design.f"
        filelist.write_text("rtl/file1.v\n\nrtl/file2.v\n\n\nrtl/file3.v\n")

        assert parse_filelist(str(filelist)) == ["rtl/file1.v", "rtl/file2.v", "rtl/file3.v"]

    def test_parse_with_quotes(self, tmp_path):
        filelist = tmp_path / "design.f"
        filelist.write_text('"path with spaces/file.v"\n' "'another path/file.v'\n")

        assert parse_filelist(str(filelist)) == ["path with spaces/file.v", "another path/file.v"]

    def test_skip_incdir_directives(self, tmp_path):
        filelist = tmp_path / "design.f"
        filelist.write_text("rtl/top.v\n+incdir+rtl/include\nrtl/sub.v\n")

        assert parse_filelist(str(filelist)) == ["rtl/top.v", "rtl/sub.v"]

    def test_error_on_y_directive(self, tmp_path):
        filelist = tmp_path / "design.f"
        filelist.write_text("rtl/top.v\n-y rtl/lib\nrtl/sub.v\n")

        with pytest.raises(ValueError, match="Unsupported filelist option.*-y"):
            parse_filelist(str(filelist))

    def test_error_on_v_directive(self, tmp_path):
        filelist = tmp_path / "design.f"
        filelist.write_text("rtl/top.v\n-v rtl/lib.v\nrtl/sub.v\n")

        with pytest.raises(ValueError, match="Unsupported filelist option.*-v"):
            parse_filelist(str(filelist))

    def test_error_on_f_directive(self, tmp_path):
        filelist = tmp_path / "design.f"
        filelist.write_text("rtl/top.v\n-f sub.f\nrtl/sub.v\n")

        with pytest.raises(ValueError, match="Unsupported filelist option.*-f"):
            parse_filelist(str(filelist))

    def test_skip_backtick_includes(self, tmp_path):
        filelist = tmp_path / "design.f"
        filelist.write_text('rtl/top.v\n`include "header.vh"\nrtl/sub.v\n')

        assert parse_filelist(str(filelist)) == ["rtl/top.v", "rtl/sub.v"]

    def test_nonexistent_filelist(self):
        with pytest.raises(FileNotFoundError):
            parse_filelist("/nonexistent/file.f")


class TestResolvePath:
    def test_resolve_relative_path(self, tmp_path):
        base_dir = str(tmp_path)
        expected = os.path.abspath(os.path.join(base_dir, "rtl/gcd.v"))
        assert resolve_path("rtl/gcd.v", base_dir) == expected

    def test_resolve_absolute_path(self, tmp_path):
        abs_path = "/absolute/path/file.v"
        assert resolve_path(abs_path, str(tmp_path)) == os.path.abspath(abs_path)

    def test_resolve_nested_path(self, tmp_path):
        base_dir = str(tmp_path)
        expected = os.path.abspath(os.path.join(base_dir, "rtl/core/alu.v"))
        assert resolve_path("rtl/core/alu.v", base_dir) == expected


class TestValidateFilelist:
    def test_validate_all_exist(self, tmp_path, write_rtl_file, create_filelist):
        rtl_dir = tmp_path / "rtl"
        rtl_dir.mkdir()
        write_rtl_file(rtl_dir / "gcd.v", "gcd")
        write_rtl_file(rtl_dir / "top.v", "top")

        filelist = tmp_path / "design.f"
        create_filelist(filelist, "rtl/gcd.v", "rtl/top.v")

        existing, missing = validate_filelist(str(filelist))
        assert existing == ["rtl/gcd.v", "rtl/top.v"]
        assert missing == []

    def test_validate_some_missing(self, tmp_path, write_rtl_file, create_filelist):
        rtl_dir = tmp_path / "rtl"
        rtl_dir.mkdir()
        write_rtl_file(rtl_dir / "gcd.v", "gcd")

        filelist = tmp_path / "design.f"
        create_filelist(filelist, "rtl/gcd.v", "rtl/missing.v")

        existing, missing = validate_filelist(str(filelist))
        assert existing == ["rtl/gcd.v"]
        assert missing == ["rtl/missing.v"]

    def test_validate_all_missing(self, tmp_path, create_filelist):
        filelist = tmp_path / "design.f"
        create_filelist(filelist, "rtl/missing1.v", "rtl/missing2.v")

        existing, missing = validate_filelist(str(filelist))
        assert existing == []
        assert missing == ["rtl/missing1.v", "rtl/missing2.v"]


class TestGetFilelistInfo:
    def test_get_info(self, tmp_path, write_rtl_file, create_filelist):
        rtl_dir = tmp_path / "rtl"
        rtl_dir.mkdir()
        write_rtl_file(rtl_dir / "gcd.v", "gcd")

        filelist = tmp_path / "design.f"
        create_filelist(filelist, "rtl/gcd.v", "rtl/missing.v")

        info = get_filelist_info(str(filelist))

        assert info["filelist"] == os.path.abspath(str(filelist))
        assert info["base_dir"] == str(tmp_path)
        assert info["total_files"] == 2
        assert info["existing_files"] == ["rtl/gcd.v"]
        assert info["missing_files"] == ["rtl/missing.v"]
        assert "rtl/gcd.v" in info["file_sizes"]
        assert info["file_sizes"]["rtl/gcd.v"] > 0


class TestParseIncdirDirectives:
    def test_parse_single_incdir(self, parse_incdir_from_content):
        dirs = parse_incdir_from_content("+incdir+./include\nrtl/top.v\n")
        assert dirs == ["./include"]

    def test_parse_multiple_incdir(self, parse_incdir_from_content):
        content = (
            "+incdir+./include\n"
            "+incdir+./rtl/common\n"
            "+incdir+../shared/headers\n"
            "rtl/top.v\n"
        )
        dirs = parse_incdir_from_content(content)
        assert dirs == ["./include", "./rtl/common", "../shared/headers"]

    def test_parse_incdir_current_dir(self, parse_incdir_from_content):
        dirs = parse_incdir_from_content("+incdir+./\nrtl/top.v\n")
        assert dirs == ["./"]

    def test_parse_incdir_with_comments(self, parse_incdir_from_content):
        content = (
            "+incdir+./include  # Main headers\n"
            "+incdir+./rtl/common // Common headers\n"
            "rtl/top.v\n"
        )
        dirs = parse_incdir_from_content(content)
        assert dirs == ["./include", "./rtl/common"]

    def test_parse_incdir_with_quotes(self, parse_incdir_from_content):
        dirs = parse_incdir_from_content('+incdir+"./include"\nrtl/top.v\n')
        assert dirs == ["./include"]

    def test_parse_incdir_empty_filelist(self, parse_incdir_from_content):
        dirs = parse_incdir_from_content("rtl/top.v\nrtl/sub.v\n")
        assert dirs == []

    def test_parse_incdir_skip_comments(self, parse_incdir_from_content):
        content = (
            "# +incdir+./should_skip\n"
            "// +incdir+./also_skip\n"
            "+incdir+./valid\n"
        )
        dirs = parse_incdir_from_content(content)
        assert dirs == ["./valid"]

    def test_parse_incdir_with_spaces(self, parse_incdir_from_content):
        content = (
            "+incdir+ ./include\n"
            "+incdir+  ./rtl/common  \n"
            '+incdir+ "./quoted"  # comment\n'
            "  +incdir+./leading\n"
            "\t+incdir+./tab\n"
        )
        dirs = parse_incdir_from_content(content)
        assert dirs == ["./include", "./rtl/common", "./quoted", "./leading", "./tab"]
