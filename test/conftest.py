import pytest

from test.pdk_runtime import complete_ics55_pdk_available

FILELIST_INTEGRATION_PREFIX = "test/test_filelist.py::TestCreateWorkspaceIntegration"

PDK_REQUIRED_TESTS = {
    f"{FILELIST_INTEGRATION_PREFIX}::test_workspace_with_filelist": "",
    f"{FILELIST_INTEGRATION_PREFIX}::test_workspace_with_nested_filelist": "",
    "test/test_harden.py::test_ics55_gcd": "../icsprout55-pdk",
    "test/test_rcx.py::test_ics55_gcd": "",
    "test/test_tools.py::test_ics55_gcd": "",
}


def pytest_collection_modifyitems(config, items):
    repo_root = str(config.rootpath)
    skip_missing_pdk = pytest.mark.skip(reason="complete ICS55 PDK is not available")
    for item in items:
        pdk_root = PDK_REQUIRED_TESTS.get(item.nodeid)
        if pdk_root is None:
            continue
        if pdk_root:
            pdk_root = f"{repo_root}/{pdk_root}"
        if not complete_ics55_pdk_available(pdk_root):
            item.add_marker(skip_missing_pdk)
