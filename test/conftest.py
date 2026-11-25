import importlib.util
from pathlib import Path

import pytest

TEST_DIR = Path(__file__).resolve().parent


@pytest.fixture(autouse=True)
def _step_worker_double(monkeypatch, request):
    if request.node.get_closest_marker("real_step_worker") is not None:
        return
    from chipcompiler.engine.step import execution as step_execution
    from test.engine.step_execution_double import execute_in_process

    monkeypatch.setattr(step_execution, "_execute_in_worker", execute_in_process)


def _load_complete_ics55_pdk_available():
    spec = importlib.util.spec_from_file_location("pdk_runtime", TEST_DIR / "pdk_runtime.py")
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load pdk_runtime from {TEST_DIR}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.complete_ics55_pdk_available


complete_ics55_pdk_available = _load_complete_ics55_pdk_available()

FILELIST_INTEGRATION_PREFIX = "test/data/test_workspace_filelist.py::TestCreateWorkspaceIntegration"

PDK_REQUIRED_TESTS = {
    f"{FILELIST_INTEGRATION_PREFIX}::test_workspace_with_filelist": "",
    f"{FILELIST_INTEGRATION_PREFIX}::test_workspace_with_nested_filelist": "",
    "test/integration/test_rtl2gds_flow.py::test_ics55_gcd": "",
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


def create_minimal_ics55_pdk(root, release="v1"):
    root = Path(root)
    tech_path = root / "prtech" / "techLEF" / "N551P6M_ecos.lef"
    tech_path.parent.mkdir(parents=True, exist_ok=True)
    tech_path.write_text("VERSION 5.8 ;\n")

    if release == "v1":
        stdcell_root = root / "IP" / "STD_cell" / "ics55_LLSC_H7C_V1p10C100"
        for flavor in ("ics55_LLSC_H7CR", "ics55_LLSC_H7CL"):
            lef_path = stdcell_root / flavor / "lef" / f"{flavor}_ecos.lef"
            lef_path.parent.mkdir(parents=True, exist_ok=True)
            lef_path.write_text("VERSION 5.8 ;\n")

            lib_path = stdcell_root / flavor / "liberty" / f"{flavor}_ss_rcworst_1p08_125_nldm.lib"
            lib_path.parent.mkdir(parents=True, exist_ok=True)
            lib_path.write_text("library(test) { }\n")
    elif release == "v2":
        (root / "VERSION").write_text("ics55-v2\n")
        stdcell_root = root / "IP" / "STD_cell"
        for vt in ("SVT", "LVT", "HVT"):
            flavor_dir = stdcell_root / f"ICsprout55_SC9T_BASIC_{vt}"
            lef_path = flavor_dir / "lef" / f"ICsprout55_9T{vt}_basic.lef"
            lef_path.parent.mkdir(parents=True, exist_ok=True)
            lef_path.write_text("VERSION 5.8 ;\n")

            lib_path = flavor_dir / "liberty" / f"ICsprout55_9T{vt}_ss_v1p08_125c_basic_nldm.lib"
            lib_path.parent.mkdir(parents=True, exist_ok=True)
            lib_path.write_text("library(test) { }\n")
    else:
        raise ValueError(f"unknown ICS55 release fixture: {release!r}")

    return root


@pytest.fixture
def minimal_ics55_pdk_factory():
    return create_minimal_ics55_pdk
