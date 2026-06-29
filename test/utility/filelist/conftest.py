import pytest

from chipcompiler.data.workspace import copy_filelist_with_sources
from chipcompiler.utility.filelist import parse_incdir_directives


@pytest.fixture
def workspace_dir(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


@pytest.fixture
def write_rtl_file():
    def write(path, module_name):
        path.write_text(f"module {module_name}(); endmodule")

    return write


@pytest.fixture
def write_header_file():
    def write(path, content):
        path.write_text(content)

    return write


@pytest.fixture
def create_filelist():
    def create(path, *entries):
        path.write_text("\n".join(entries) + "\n")

    return create


@pytest.fixture
def create_filelist_with_content():
    def create(path, content):
        path.write_text(content)

    return create


@pytest.fixture
def setup_project_with_incdir():
    def setup(project_dir, incdir_name="include", rtl_dir="rtl"):
        rtl_path = project_dir / rtl_dir
        include_path = project_dir / incdir_name
        rtl_path.mkdir(parents=True)
        include_path.mkdir(parents=True)
        return rtl_path, include_path

    return setup


@pytest.fixture
def parse_incdir_from_content(tmp_path, create_filelist_with_content):
    def parse(content):
        filelist = tmp_path / "design.f"
        create_filelist_with_content(filelist, content)
        return parse_incdir_directives(str(filelist))

    return parse


@pytest.fixture
def copy_filelist_content(tmp_path, create_filelist_with_content):
    def copy(project_dir, filelist_content):
        filelist = project_dir / "design.f"
        create_filelist_with_content(filelist, filelist_content)

        workspace = tmp_path / "workspace"
        copy_filelist_with_sources(str(filelist), str(workspace))
        return workspace / "origin"

    return copy
