import hashlib
from concurrent.futures import ThreadPoolExecutor

import pytest

from chipcompiler.pdk import profiles
from chipcompiler.pdk.catalog import shared_sta_catalog
from chipcompiler.pdk.manifest import Descriptor, DescriptorError


def test_import_cache_reuses_and_repairs_verified_content(tmp_path, monkeypatch):
    monkeypatch.setenv("ECC_PDK_INVENTORY", str(tmp_path / "state/inventory.json"))
    source = tmp_path / "cells.lef"
    source.write_bytes(b"MACRO BUFX2S\n")
    expected = b"BUFX2S\tBUF\tsvt\t2\n"
    rule = profiles.CatalogRule(
        lefs=["cells"],
        master=r"(.+)X(\d+)(S)",
        vt={"S": "svt"},
        sort_by_master=False,
        compact_drive=True,
        sha256=hashlib.sha256(expected).hexdigest(),
    )
    descriptor = Descriptor.model_validate(
        {
            "family_id": "test",
            "resources": {
                "cells": {
                    "role": "lef",
                    "path": source.name,
                    "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                }
            },
        }
    )
    profile = profiles.Profile(
        id="test", description_digests=[], description="x", adaptation="y", sta_catalog=rule
    )
    monkeypatch.setattr("chipcompiler.pdk.catalog.matching_profile", lambda _: profile)

    def ensure():
        path = shared_sta_catalog(tmp_path, descriptor)
        assert path is not None
        return path

    with ThreadPoolExecutor(4) as pool:
        paths = list(pool.map(lambda _: ensure(), range(8)))
    path = paths[0]
    assert set(paths) == {path}
    assert path.read_bytes() == expected
    stamp = path.stat().st_mtime_ns
    assert ensure().stat().st_mtime_ns == stamp
    path.write_bytes(b"wrong but non-empty\n")
    assert ensure().read_bytes() == expected
    path.unlink()
    assert ensure().read_bytes() == expected
    path.unlink()
    source.write_bytes(b"MACRO BUFX3S\n")
    with pytest.raises(DescriptorError, match="unexpected catalog LEF"):
        ensure()
    assert not path.exists()
