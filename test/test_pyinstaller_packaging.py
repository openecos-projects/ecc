from chipcompiler.pyinstaller_utils import (
    filter_collected_payloads,
    filter_hiddenimports,
)


def test_pyinstaller_payload_filter_excludes_oversized_paths():
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

    assert filter_collected_payloads(payloads) == [payloads[-1]]


def test_pyinstaller_hiddenimport_filter_keeps_public_torch_imports():
    hiddenimports = [
        "torch",
        "torch.testing",
        "torch.testing._internal.common_utils",
        "chipcompiler.tools.ecc.builder",
    ]

    assert filter_hiddenimports(hiddenimports) == [
        "torch",
        "torch.testing",
        "chipcompiler.tools.ecc.builder",
    ]
