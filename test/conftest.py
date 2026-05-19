import importlib.util
from pathlib import Path

import pytest

TEST_DIR = Path(__file__).resolve().parent


def _load_complete_ics55_pdk_available():
    spec = importlib.util.spec_from_file_location("pdk_runtime", TEST_DIR / "pdk_runtime.py")
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load pdk_runtime from {TEST_DIR}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.complete_ics55_pdk_available


complete_ics55_pdk_available = _load_complete_ics55_pdk_available()

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
