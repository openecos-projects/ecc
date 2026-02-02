#!/usr/bin/env python
"""
Test filelist parsing and copying functionality.

Tests:
- parse_filelist: Extract file paths from filelist
- resolve_path: Resolve relative/absolute paths
- validate_filelist: Check file existence
- copy_filelist_with_sources: Copy filelist + RTL files to workspace
- create_workspace: Integration test with filelist
"""

import os
import sys

import pytest

current_dir = os.path.dirname(os.path.abspath(__file__))
root = os.path.dirname(current_dir)
sys.path.insert(0, root)

from chipcompiler.data import create_workspace, get_pdk
from chipcompiler.data.parameter import Parameters
from chipcompiler.data.workspace import copy_filelist_with_sources
from chipcompiler.utility.filelist import (
    get_filelist_info,
    parse_filelist,
    parse_incdir_directives,
    resolve_path,
    validate_filelist,
)


@pytest.fixture
def workspace_dir(tmp_path):
    """Create and return a workspace directory."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


@pytest.fixture
def test_parameters():
    """Create default test parameters."""
    parameters = Parameters()
    parameters.data = {
        "Design": "test",
        "Top module": "top",
        "Clock": "clk",
        "Frequency max [MHz]": 100
    }
    return parameters


def write_rtl_file(path, module_name):
    """Helper to write a simple RTL module file."""
    path.write_text(f"module {module_name}(); endmodule")


def write_header_file(path, content):
    """Helper to write a header file."""
    path.write_text(content)


def create_filelist(path, *entries):
    """Helper to create a filelist with given entries."""
    path.write_text("\n".join(entries) + "\n")


def create_filelist_with_content(path, content):
    """Helper to create a filelist with raw content."""
    path.write_text(content)


def setup_project_with_incdir(project_dir, incdir_name="include", rtl_dir="rtl"):
    """
    Helper to set up project structure with RTL and include directories.
    Returns tuple of (rtl_dir_path, include_dir_path).
    """
    rtl_path = project_dir / rtl_dir
    include_path = project_dir / incdir_name
    rtl_path.mkdir(parents=True)
    include_path.mkdir(parents=True)
    return rtl_path, include_path


class TestParseFilelist:
    """Test filelist parsing functionality."""

    def test_parse_simple_filelist(self, tmp_path):
        """Parse filelist with simple file paths."""
        filelist = tmp_path / "design.f"
        create_filelist(filelist, "rtl/gcd.v", "rtl/gcd_pkg.v")

        assert parse_filelist(str(filelist)) == ["rtl/gcd.v", "rtl/gcd_pkg.v"]

    def test_parse_with_comments(self, tmp_path):
        """Parse filelist with comments."""
        filelist = tmp_path / "design.f"
        filelist.write_text(
            "# This is a comment\n"
            "rtl/top.v\n"
            "// Another comment\n"
            "rtl/sub.v  # inline comment\n"
        )

        assert parse_filelist(str(filelist)) == ["rtl/top.v", "rtl/sub.v"]

    def test_parse_with_empty_lines(self, tmp_path):
        """Parse filelist with empty lines."""
        filelist = tmp_path / "design.f"
        filelist.write_text("rtl/file1.v\n\nrtl/file2.v\n\n\nrtl/file3.v\n")

        assert parse_filelist(str(filelist)) == ["rtl/file1.v", "rtl/file2.v", "rtl/file3.v"]

    def test_parse_with_quotes(self, tmp_path):
        """Parse filelist with quoted paths."""
        filelist = tmp_path / "design.f"
        filelist.write_text('"path with spaces/file.v"\n' "'another path/file.v'\n")

        assert parse_filelist(str(filelist)) == ["path with spaces/file.v", "another path/file.v"]

    def test_skip_incdir_directives(self, tmp_path):
        """Skip +incdir directives (supported)."""
        filelist = tmp_path / "design.f"
        filelist.write_text("rtl/top.v\n+incdir+rtl/include\nrtl/sub.v\n")

        assert parse_filelist(str(filelist)) == ["rtl/top.v", "rtl/sub.v"]

    def test_error_on_y_directive(self, tmp_path):
        """Raise error for -y library search directive."""
        filelist = tmp_path / "design.f"
        filelist.write_text("rtl/top.v\n-y rtl/lib\nrtl/sub.v\n")

        with pytest.raises(ValueError, match="Unsupported filelist option.*-y"):
            parse_filelist(str(filelist))

    def test_error_on_v_directive(self, tmp_path):
        """Raise error for -v library file directive."""
        filelist = tmp_path / "design.f"
        filelist.write_text("rtl/top.v\n-v rtl/lib.v\nrtl/sub.v\n")

        with pytest.raises(ValueError, match="Unsupported filelist option.*-v"):
            parse_filelist(str(filelist))

    def test_error_on_f_directive(self, tmp_path):
        """Raise error for -f recursive filelist directive."""
        filelist = tmp_path / "design.f"
        filelist.write_text("rtl/top.v\n-f sub.f\nrtl/sub.v\n")

        with pytest.raises(ValueError, match="Unsupported filelist option.*-f"):
            parse_filelist(str(filelist))

    def test_skip_backtick_includes(self, tmp_path):
        """Skip backtick includes like `include."""
        filelist = tmp_path / "design.f"
        filelist.write_text('rtl/top.v\n`include "header.vh"\nrtl/sub.v\n')

        assert parse_filelist(str(filelist)) == ["rtl/top.v", "rtl/sub.v"]

    def test_nonexistent_filelist(self):
        """Raise error for nonexistent filelist."""
        with pytest.raises(FileNotFoundError):
            parse_filelist("/nonexistent/file.f")


class TestResolvePath:
    """Test path resolution functionality."""

    def test_resolve_relative_path(self, tmp_path):
        """Resolve relative path against base directory."""
        base_dir = str(tmp_path)
        expected = os.path.abspath(os.path.join(base_dir, "rtl/gcd.v"))
        assert resolve_path("rtl/gcd.v", base_dir) == expected

    def test_resolve_absolute_path(self, tmp_path):
        """Absolute path should be returned as-is."""
        abs_path = "/absolute/path/file.v"
        assert resolve_path(abs_path, str(tmp_path)) == os.path.abspath(abs_path)

    def test_resolve_nested_path(self, tmp_path):
        """Resolve nested relative path."""
        base_dir = str(tmp_path)
        expected = os.path.abspath(os.path.join(base_dir, "rtl/core/alu.v"))
        assert resolve_path("rtl/core/alu.v", base_dir) == expected


class TestValidateFilelist:
    """Test filelist validation functionality."""

    def test_validate_all_exist(self, tmp_path):
        """All files exist."""
        rtl_dir = tmp_path / "rtl"
        rtl_dir.mkdir()
        write_rtl_file(rtl_dir / "gcd.v", "gcd")
        write_rtl_file(rtl_dir / "top.v", "top")

        filelist = tmp_path / "design.f"
        create_filelist(filelist, "rtl/gcd.v", "rtl/top.v")

        existing, missing = validate_filelist(str(filelist))
        assert existing == ["rtl/gcd.v", "rtl/top.v"]
        assert missing == []

    def test_validate_some_missing(self, tmp_path):
        """Some files missing."""
        rtl_dir = tmp_path / "rtl"
        rtl_dir.mkdir()
        write_rtl_file(rtl_dir / "gcd.v", "gcd")

        filelist = tmp_path / "design.f"
        create_filelist(filelist, "rtl/gcd.v", "rtl/missing.v")

        existing, missing = validate_filelist(str(filelist))
        assert existing == ["rtl/gcd.v"]
        assert missing == ["rtl/missing.v"]

    def test_validate_all_missing(self, tmp_path):
        """All files missing."""
        filelist = tmp_path / "design.f"
        create_filelist(filelist, "rtl/missing1.v", "rtl/missing2.v")

        existing, missing = validate_filelist(str(filelist))
        assert existing == []
        assert missing == ["rtl/missing1.v", "rtl/missing2.v"]


class TestGetFilelistInfo:
    """Test get_filelist_info functionality."""

    def test_get_info(self, tmp_path):
        """Get detailed filelist information."""
        rtl_dir = tmp_path / "rtl"
        rtl_dir.mkdir()
        write_rtl_file(rtl_dir / "gcd.v", "gcd")

        filelist = tmp_path / "design.f"
        create_filelist(filelist, "rtl/gcd.v", "rtl/missing.v")

        info = get_filelist_info(str(filelist))

        assert info['filelist'] == os.path.abspath(str(filelist))
        assert info['base_dir'] == str(tmp_path)
        assert info['total_files'] == 2
        assert info['existing_files'] == ["rtl/gcd.v"]
        assert info['missing_files'] == ["rtl/missing.v"]
        assert "rtl/gcd.v" in info['file_sizes']
        assert info['file_sizes']["rtl/gcd.v"] > 0


class TestCopyFilelistWithSources:
    """Test copy_filelist_with_sources functionality."""

    def test_copy_simple_filelist(self, tmp_path, workspace_dir):
        """Copy filelist with single file."""
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

    def test_copy_nested_structure(self, tmp_path, workspace_dir):
        """Copy filelist preserving nested directory structure."""
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

    def test_copy_with_missing_files(self, tmp_path, workspace_dir):
        """Copy filelist with some missing files."""
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

    def test_copy_with_absolute_paths(self, tmp_path, workspace_dir):
        """Copy filelist with absolute paths."""
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


class TestCreateWorkspaceIntegration:
    """Test create_workspace integration with filelist copying."""

    @pytest.fixture
    def pdk(self):
        """Get the ICS55 PDK for integration tests."""
        return get_pdk(pdk_name="ics55")

    def test_workspace_with_filelist(self, tmp_path, test_parameters, pdk):
        """Create workspace with filelist."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        write_rtl_file(project_dir / "gcd.v", "gcd")

        filelist = project_dir / "design.f"
        create_filelist(filelist, "gcd.v")

        test_parameters.data["Design"] = "gcd"
        test_parameters.data["Top module"] = "gcd"

        workspace_dir = tmp_path / "workspace"
        workspace = create_workspace(
            directory=str(workspace_dir),
            origin_def="",
            origin_verilog="",
            pdk=pdk,
            parameters=test_parameters,
            input_filelist=str(filelist)
        )

        assert os.path.exists(workspace_dir)
        assert os.path.exists(workspace_dir / "origin")
        assert os.path.exists(workspace_dir / "origin" / "design.f")
        assert os.path.exists(workspace_dir / "origin" / "gcd.v")
        assert (workspace_dir / "origin" / "gcd.v").read_text() == "module gcd(); endmodule"
        assert workspace.design.input_filelist == str(workspace_dir / "origin" / "design.f")

    def test_workspace_with_nested_filelist(self, tmp_path, test_parameters, pdk):
        """Create workspace with nested filelist structure."""
        project_dir = tmp_path / "project"
        (project_dir / "rtl" / "core").mkdir(parents=True)

        write_rtl_file(project_dir / "rtl" / "core" / "alu.v", "alu")
        write_rtl_file(project_dir / "rtl" / "core" / "ctrl.v", "ctrl")

        filelist = project_dir / "design.f"
        create_filelist(filelist, "rtl/core/alu.v", "rtl/core/ctrl.v")

        workspace_dir = tmp_path / "workspace"
        create_workspace(
            directory=str(workspace_dir),
            origin_def="",
            origin_verilog="",
            pdk=pdk,
            parameters=test_parameters,
            input_filelist=str(filelist)
        )

        origin_dir = workspace_dir / "origin"
        assert (origin_dir / "rtl" / "core" / "alu.v").exists()
        assert (origin_dir / "rtl" / "core" / "ctrl.v").exists()


class TestParseIncdirDirectives:
    """Test suite for parse_incdir_directives function."""

    def _parse_incdir(self, tmp_path, content):
        """Helper to create filelist and parse incdir directives."""
        filelist = tmp_path / "design.f"
        create_filelist_with_content(filelist, content)
        return parse_incdir_directives(str(filelist))

    def test_parse_single_incdir(self, tmp_path):
        """Parse filelist with single +incdir directive."""
        dirs = self._parse_incdir(tmp_path, "+incdir+./include\nrtl/top.v\n")
        assert dirs == ["./include"]

    def test_parse_multiple_incdir(self, tmp_path):
        """Parse filelist with multiple +incdir directives."""
        content = (
            "+incdir+./include\n"
            "+incdir+./rtl/common\n"
            "+incdir+../shared/headers\n"
            "rtl/top.v\n"
        )
        dirs = self._parse_incdir(tmp_path, content)
        assert dirs == ["./include", "./rtl/common", "../shared/headers"]

    def test_parse_incdir_current_dir(self, tmp_path):
        """Parse filelist with +incdir+./ directive."""
        dirs = self._parse_incdir(tmp_path, "+incdir+./\nrtl/top.v\n")
        assert dirs == ["./"]

    def test_parse_incdir_with_comments(self, tmp_path):
        """Parse +incdir directives with inline comments."""
        content = (
            "+incdir+./include  # Main headers\n"
            "+incdir+./rtl/common // Common headers\n"
            "rtl/top.v\n"
        )
        dirs = self._parse_incdir(tmp_path, content)
        assert dirs == ["./include", "./rtl/common"]

    def test_parse_incdir_with_quotes(self, tmp_path):
        """Parse +incdir directives with quoted paths."""
        dirs = self._parse_incdir(tmp_path, '+incdir+"./include"\nrtl/top.v\n')
        assert dirs == ["./include"]

    def test_parse_incdir_empty_filelist(self, tmp_path):
        """Parse filelist with no +incdir directives."""
        dirs = self._parse_incdir(tmp_path, "rtl/top.v\nrtl/sub.v\n")
        assert dirs == []

    def test_parse_incdir_skip_comments(self, tmp_path):
        """Ensure comments are skipped when parsing +incdir."""
        content = (
            "# +incdir+./should_skip\n"
            "// +incdir+./also_skip\n"
            "+incdir+./valid\n"
        )
        dirs = self._parse_incdir(tmp_path, content)
        assert dirs == ["./valid"]

    def test_parse_incdir_with_spaces(self, tmp_path):
        """Parse +incdir directives with surrounding spaces."""
        content = (
            "+incdir+ ./include\n"           # Space after prefix
            "+incdir+  ./rtl/common  \n"     # Multiple spaces
            "+incdir+ \"./quoted\"  # comment\n"  # Spaces with quotes
            "  +incdir+./leading\n"          # Leading spaces on line
            "\t+incdir+./tab\n"              # Leading tab
        )
        dirs = self._parse_incdir(tmp_path, content)
        assert dirs == ["./include", "./rtl/common", "./quoted", "./leading", "./tab"]


class TestCopyFilelistWithIncdir:
    """Test suite for copy_filelist_with_sources with +incdir support."""

    def _copy_and_get_origin(self, tmp_path, project_dir, filelist_content):
        """Helper to create filelist, copy sources, and return origin directory."""
        filelist = project_dir / "design.f"
        create_filelist_with_content(filelist, filelist_content)

        workspace_dir = tmp_path / "workspace"
        copy_filelist_with_sources(str(filelist), str(workspace_dir))
        return workspace_dir / "origin"

    def test_copy_with_incdir_basic(self, tmp_path):
        """Copy filelist with basic +incdir directive."""
        project_dir = tmp_path / "project"
        rtl_dir, include_dir = setup_project_with_incdir(project_dir)

        write_rtl_file(rtl_dir / "top.v", "top")
        write_header_file(include_dir / "defines.vh", "`define WIDTH 32")

        origin_dir = self._copy_and_get_origin(
            tmp_path, project_dir, "+incdir+./include\nrtl/top.v\n"
        )

        assert (origin_dir / "rtl" / "top.v").exists()
        assert (origin_dir / "include" / "defines.vh").exists()

    def test_copy_with_incdir_deduplication(self, tmp_path):
        """Verify deduplication when file appears in both filelist and +incdir."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        write_rtl_file(project_dir / "top.v", "top")
        write_header_file(project_dir / "types.vh", "`define TYPES")

        origin_dir = self._copy_and_get_origin(
            tmp_path, project_dir, "top.v\n+incdir+./\n"
        )

        assert (origin_dir / "top.v").exists()
        assert (origin_dir / "types.vh").exists()

        # Verify file count: top.v and types.vh only
        verilog_files = list(origin_dir.glob("*.v")) + list(origin_dir.glob("*.vh"))
        assert len(verilog_files) == 2

    def test_copy_with_incdir_nested_structure(self, tmp_path):
        """Copy +incdir with nested directory structure."""
        project_dir = tmp_path / "project"
        rtl_dir, include_dir = setup_project_with_incdir(project_dir)
        (include_dir / "subdir").mkdir()

        write_rtl_file(rtl_dir / "top.v", "top")
        write_header_file(include_dir / "defines.vh", "`define A")
        write_header_file(include_dir / "subdir" / "params.vh", "`define B")

        origin_dir = self._copy_and_get_origin(
            tmp_path, project_dir, "+incdir+./include\nrtl/top.v\n"
        )

        assert (origin_dir / "rtl" / "top.v").exists()
        assert (origin_dir / "include" / "defines.vh").exists()
        assert (origin_dir / "include" / "subdir" / "params.vh").exists()

    def test_copy_with_incdir_missing_directory(self, tmp_path):
        """Handle missing +incdir directory gracefully."""
        project_dir = tmp_path / "project"
        (project_dir / "rtl").mkdir(parents=True)

        write_rtl_file(project_dir / "rtl" / "top.v", "top")

        origin_dir = self._copy_and_get_origin(
            tmp_path, project_dir, "+incdir+./missing_include\nrtl/top.v\n"
        )

        assert (origin_dir / "rtl" / "top.v").exists()

    def test_copy_with_multiple_incdir(self, tmp_path):
        """Copy filelist with multiple +incdir directives."""
        project_dir = tmp_path / "project"
        (project_dir / "rtl").mkdir(parents=True)
        (project_dir / "include1").mkdir(parents=True)
        (project_dir / "include2").mkdir(parents=True)

        write_rtl_file(project_dir / "rtl" / "top.v", "top")
        write_header_file(project_dir / "include1" / "defs1.vh", "`define A")
        write_header_file(project_dir / "include2" / "defs2.vh", "`define B")

        origin_dir = self._copy_and_get_origin(
            tmp_path,
            project_dir,
            "+incdir+./include1\n+incdir+./include2\nrtl/top.v\n",
        )

        assert (origin_dir / "rtl" / "top.v").exists()
        assert (origin_dir / "include1" / "defs1.vh").exists()
        assert (origin_dir / "include2" / "defs2.vh").exists()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
