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


def test_pyinstaller_payload_filter_keeps_torch_runtime_binaries():
    payloads = [
        (
            "/venv/site-packages/torch/bin/torch_shm_manager",
            "torch/bin/torch_shm_manager",
            "BINARY",
        ),
        (
            "/venv/site-packages/torch/bin/torch_shm_manager",
            "/home/runner/work/ecc/.venv/lib/python3.11/site-packages/torch/bin/torch_shm_manager",
            "BINARY",
        ),
    ]

    assert filter_collected_payloads(payloads) == payloads


def test_pyinstaller_hiddenimport_filter_keeps_public_torch_imports():
    hiddenimports = [
        "torch",
        "torch.distributed",
        "torch.distributed._shard.sharded_optim",
        "torch.testing",
        "torch.testing._internal.common_utils",
        "chipcompiler.tools.ecc.builder",
    ]

    assert filter_hiddenimports(hiddenimports) == [
        "torch",
        "torch.distributed",
        "torch.distributed._shard.sharded_optim",
        "torch.testing",
        "chipcompiler.tools.ecc.builder",
    ]


def test_pyinstaller_hiddenimport_filter_excludes_missing_torch_sharding_internals():
    hiddenimports = [
        "torch.distributed._shard.checkpoint._async_executor",
        "torch.distributed._shard.checkpoint._experimental.builder",
        "torch.distributed._sharded_tensor._ops",
        "torch.distributed._sharded_tensor.metadata",
        "torch.distributed._sharding_spec._internals",
        "torch.distributed._sharding_spec.chunk_sharding_spec_ops.embedding",
    ]

    assert filter_hiddenimports(hiddenimports) == []
