import os

import pytest

from chipcompiler.data import create_workspace, get_pdk
from chipcompiler.data.parameter import Parameters


@pytest.fixture
def test_parameters():
    parameters = Parameters()
    parameters.data = {
        "Design": "test",
        "Top module": "top",
        "Clock": "clk",
        "Frequency max [MHz]": 100,
    }
    return parameters


@pytest.fixture
def pdk():
    return get_pdk(pdk_name="ics55")


def _write_rtl_file(path, module_name):
    path.write_text(f"module {module_name}(); endmodule")


def _create_filelist(path, *entries):
    path.write_text("\n".join(entries) + "\n")


class TestCreateWorkspaceIntegration:
    def test_workspace_with_filelist(self, tmp_path, test_parameters, pdk):
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        _write_rtl_file(project_dir / "gcd.v", "gcd")

        filelist = project_dir / "design.f"
        _create_filelist(filelist, "gcd.v")

        test_parameters.data["Design"] = "gcd"
        test_parameters.data["Top module"] = "gcd"

        workspace_dir = tmp_path / "workspace"
        workspace = create_workspace(
            directory=str(workspace_dir),
            origin_def="",
            origin_verilog="",
            pdk=pdk,
            parameters=test_parameters,
            input_filelist=str(filelist),
        )

        assert os.path.exists(workspace_dir)
        assert os.path.exists(workspace_dir / "origin")
        assert os.path.exists(workspace_dir / "origin" / "design.f")
        assert os.path.exists(workspace_dir / "origin" / "gcd.v")
        assert (workspace_dir / "origin" / "gcd.v").read_text() == "module gcd(); endmodule"
        assert workspace.design.input_filelist == str(workspace_dir / "origin" / "design.f")

    def test_workspace_with_nested_filelist(self, tmp_path, test_parameters, pdk):
        project_dir = tmp_path / "project"
        (project_dir / "rtl" / "core").mkdir(parents=True)

        _write_rtl_file(project_dir / "rtl" / "core" / "alu.v", "alu")
        _write_rtl_file(project_dir / "rtl" / "core" / "ctrl.v", "ctrl")

        filelist = project_dir / "design.f"
        _create_filelist(filelist, "rtl/core/alu.v", "rtl/core/ctrl.v")

        workspace_dir = tmp_path / "workspace"
        create_workspace(
            directory=str(workspace_dir),
            origin_def="",
            origin_verilog="",
            pdk=pdk,
            parameters=test_parameters,
            input_filelist=str(filelist),
        )

        origin_dir = workspace_dir / "origin"
        assert (origin_dir / "rtl" / "core" / "alu.v").exists()
        assert (origin_dir / "rtl" / "core" / "ctrl.v").exists()
