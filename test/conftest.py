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

FILELIST_INTEGRATION_PREFIX = "test/data/test_workspace_filelist.py::TestCreateWorkspaceIntegration"

# Empty pdk_root means "resolve via env / default layout" in complete_ics55_pdk_available.
PDK_REQUIRED_PREFIXES = (
    FILELIST_INTEGRATION_PREFIX,
    "test/integration/test_rtl2gds_flow.py::test_ics55_gcd",
)


def pytest_collection_modifyitems(config, items):
    if complete_ics55_pdk_available(""):
        return
    skip_missing_pdk = pytest.mark.skip(reason="complete ICS55 PDK is not available")
    for item in items:
        if any(item.nodeid.startswith(prefix) for prefix in PDK_REQUIRED_PREFIXES):
            item.add_marker(skip_missing_pdk)


def create_minimal_ics55_pdk(root):
    root = Path(root)
    tech_path = root / "prtech" / "techLEF" / "N551P6M_ecos.lef"
    tech_path.parent.mkdir(parents=True, exist_ok=True)
    tech_path.write_text("VERSION 5.8 ;\n")

    stdcell_root = root / "IP" / "STD_cell" / "ics55_LLSC_H7C_V1p10C100"
    for flavor in ("ics55_LLSC_H7CR", "ics55_LLSC_H7CL"):
        lef_path = stdcell_root / flavor / "lef" / f"{flavor}_ecos.lef"
        lef_path.parent.mkdir(parents=True, exist_ok=True)
        lef_path.write_text("VERSION 5.8 ;\n")

        lib_path = stdcell_root / flavor / "liberty" / f"{flavor}_ss_rcworst_1p08_125_nldm.lib"
        lib_path.parent.mkdir(parents=True, exist_ok=True)
        lib_path.write_text("library(test) { }\n")

    return root


@pytest.fixture
def minimal_ics55_pdk_factory():
    return create_minimal_ics55_pdk
