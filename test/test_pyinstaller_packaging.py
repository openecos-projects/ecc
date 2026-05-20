import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_repo_file(path: str) -> str:
    return (ROOT / path).read_text()


def load_spec_helpers(*names: str):
    tree = ast.parse(read_repo_file("ecc.spec"), filename="ecc.spec")
    selected = []
    wanted = set(names)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            target_names = {target.id for target in node.targets if isinstance(target, ast.Name)}
            if target_names & wanted:
                selected.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in wanted:
            selected.append(node)

    namespace = {}
    module = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, "ecc.spec", "exec"), namespace)
    return namespace


def test_ecc_spec_declares_cli_packaging_contract():
    spec = read_repo_file("ecc.spec")

    assert 'BUNDLE_MODE = os.environ.get("ECOS_PYINSTALLER_MODE", "onedir")' in spec
    assert 'name="ecc"' in spec
    assert 'collect_all("chipcompiler")' in spec
    assert 'collect_all("klayout")' in spec
    assert 'collect_all("dreamplace")' in spec
    assert 'collect_all("torch")' in spec

    for dist_name in ("ecc", "ecc-dreamplace", "ecc-tools"):
        assert f'"{dist_name}"' in spec
        assert "copy_metadata(dist_name)" in spec

    for resource in (
        "chipcompiler/tools/ecc/configs",
        "chipcompiler/tools/yosys/configs",
        "chipcompiler/tools/yosys/scripts",
        "chipcompiler/tools/ecc_dreamplace/configs/dreamplace.json",
    ):
        assert resource in spec

    for dreamplace_resource in (
        "thirdparty/flute/lut.ICCAD2015/POWV9.dat",
        "thirdparty/flute/lut.ICCAD2015/POST9.dat",
        "thirdparty/NCTUgr.ICCAD2012/NCTUgr",
        "thirdparty/NCTUgr.ICCAD2012/ICCAD12.set",
    ):
        assert dreamplace_resource in spec


def test_ecc_spec_keeps_server_imports_out_and_linux_libs_guarded():
    spec = read_repo_file("ecc.spec")

    assert "ecos_server" not in spec
    assert "fastapi" not in spec
    assert "uvicorn" not in spec
    assert "starlette" not in spec

    assert 'if sys.platform.startswith("linux"):' in spec
    assert "libgomp.so.1" in spec
    assert "libxcb-render.so.0" in spec
    assert 'elif sys.platform == "darwin":' in spec
    assert 'elif sys.platform == "win32":' in spec


def test_ecc_spec_filters_oversized_thirdparty_payloads():
    spec = read_repo_file("ecc.spec")

    assert "filter_collected_payloads" in spec
    assert "filter_hiddenimports" in spec
    assert "chipcompiler/thirdparty/ecc-tools" in spec
    assert "thirdparty/ecc-dreamplace/test" in spec
    assert "thirdparty/ecc-dreamplace/docs" in spec
    assert "torch/test" in spec
    assert "torch/testing/_internal" in spec
    assert "torch/bin" in spec


def test_ecc_spec_payload_filter_matches_source_and_bundle_paths():
    helpers = load_spec_helpers(
        "EXCLUDED_PAYLOAD_PREFIXES",
        "EXCLUDED_HIDDENIMPORT_PREFIXES",
        "payload_path_matches",
        "payload_is_excluded",
        "filter_collected_payloads",
        "hiddenimport_is_excluded",
        "filter_hiddenimports",
    )

    payloads = [
        (
            "/repo/chipcompiler/thirdparty/ecc-tools/src/main.cc",
            "chipcompiler/thirdparty/ecc-tools/src/main.cc",
            "DATA",
        ),
        (
            "torch/testing/_internal/common_utils.py",
            "/venv/site-packages/torch/testing/_internal/common_utils.py",
            "PYMODULE",
        ),
        (
            "/repo/chipcompiler/tools/ecc/configs/flow_config.json",
            "chipcompiler/tools/ecc/configs/flow_config.json",
            "DATA",
        ),
    ]

    filtered = helpers["filter_collected_payloads"](payloads)
    assert filtered == [payloads[-1]]

    hiddenimports = [
        "torch",
        "torch.testing",
        "torch.testing._internal.common_utils",
        "chipcompiler.tools.ecc.builder",
    ]
    assert helpers["filter_hiddenimports"](hiddenimports) == [
        "torch",
        "torch.testing",
        "chipcompiler.tools.ecc.builder",
    ]


def test_pyinstaller_bootstrap_preserves_user_cwd():
    bootstrap = read_repo_file("packaging/run_ecc.py")

    assert "multiprocessing.freeze_support()" in bootstrap
    assert "ECC_PYINSTALLER_ROOT" in bootstrap
    assert "chipcompiler.cli.main" in bootstrap
    assert "chdir" not in bootstrap


def test_bazel_pyinstaller_bundle_contract_is_onedir_tar():
    build_file = read_repo_file("BUILD.bazel")

    assert 'name = "ecc_pyinstaller_srcs"' in build_file
    assert 'name = "build_ecc_cli_bundle"' in build_file
    assert '":ecc_pyinstaller_srcs",\n        "ecc.spec",' in build_file
    assert 'outs = ["build_ecc_cli_bundle/ecc.tar"]' in build_file
    assert 'export PYTHON_INTERPRETER=".venv/bin/python"' in build_file
    assert 'export ECOS_PYINSTALLER_MODE="onedir"' in build_file
    assert 'tar -cf "$@" -C "$$DIST_DIR/ecc" .' in build_file
    assert "ECOS_PYINSTALLER_MODE=onefile" not in build_file
