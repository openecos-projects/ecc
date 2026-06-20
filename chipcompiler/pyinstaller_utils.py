EXCLUDED_PAYLOAD_PREFIXES = (
    "chipcompiler/thirdparty/ecc-tools",
    "chipcompiler/thirdparty/ecc-sizer",
    "chipcompiler/thirdparty/ecc-dreamplace/test",
    "chipcompiler/thirdparty/ecc-dreamplace/docs",
    "chipcompiler/thirdparty/ecc-dreamplace/build",
    "thirdparty/ecc-dreamplace/test",
    "thirdparty/ecc-dreamplace/docs",
    "thirdparty/ecc-dreamplace/build",
    "chipcompiler/tools/ecc_dreamplace/dreamplace/test",
    "chipcompiler/tools/ecc_dreamplace/dreamplace/unittest",
    "chipcompiler/tools/ecc_dreamplace/dreamplace/benchmarks",
    "torch/test",
    "torch/testing/_internal",
)

EXCLUDED_HIDDENIMPORT_PREFIXES = (
    "torch.distributed._shard.checkpoint",
    "torch.distributed._sharded_tensor",
    "torch.distributed._sharding_spec",
    "torch.testing._internal",
    "torch.test",
)


def payload_path_matches(path, prefix):
    normalized = str(path).replace("\\", "/")
    return (
        normalized == prefix
        or normalized.startswith(f"{prefix}/")
        or f"/{prefix}/" in normalized
    )


def payload_is_excluded(item):
    paths = item[:2] if isinstance(item, (tuple, list)) else (item,)
    return any(
        payload_path_matches(path, prefix)
        for path in paths
        for prefix in EXCLUDED_PAYLOAD_PREFIXES
    )


def filter_collected_payloads(payloads):
    return [item for item in payloads if not payload_is_excluded(item)]


def hiddenimport_is_excluded(module_name):
    return any(
        module_name == prefix or module_name.startswith(f"{prefix}.")
        for prefix in EXCLUDED_HIDDENIMPORT_PREFIXES
    )


def filter_hiddenimports(imports):
    return [module_name for module_name in imports if not hiddenimport_is_excluded(module_name)]
