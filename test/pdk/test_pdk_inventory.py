import json
import shutil

import pytest

from chipcompiler.pdk.manifest import DescriptorError
from chipcompiler.pdk.registry import (
    default_installation,
    inventory_transaction,
    register,
    relocate,
    set_default,
)


def test_shared_inventory_defaults_and_identical_relocation(tmp_path, monkeypatch):
    path = tmp_path / "state/inventory.json"
    monkeypatch.setenv("ECC_PDK_INVENTORY", str(path))
    root = tmp_path / "pdk"
    root.mkdir()
    (root / "cells.lib").write_text("library(vendor) {}")
    (root / "ecc-pdk.json").write_text(
        json.dumps(
            {
                "family_id": "vendor",
                "release": "r1",
                "resources": {"lib": {"path": "cells.lib", "role": "liberty"}},
            }
        )
    )
    record = register(root)
    set_default(record["id"], "ecc")
    assert default_installation() == record
    assert default_installation("studio") is None
    with inventory_transaction() as inventory:
        inventory["bindings"].append({"projectId": "p", "installationId": record["id"]})
    moved = tmp_path / "relocated"
    shutil.copytree(root, moved)
    assert relocate(record["id"], moved)["root"] == str(moved)
    (root / "cells.lib").write_text("changed")
    with pytest.raises(DescriptorError, match="identical"):
        relocate(record["id"], root)
    with inventory_transaction() as inventory:
        assert inventory["bindings"] == [{"projectId": "p", "installationId": record["id"]}]
        assert inventory["installations"][0]["root"] == str(moved)


def test_failed_transaction_preserves_inventory(tmp_path, monkeypatch):
    monkeypatch.setenv("ECC_PDK_INVENTORY", str(tmp_path / "inventory.json"))
    with pytest.raises(ValueError), inventory_transaction() as inventory:
        inventory["installations"].append({"bad": True})
        raise ValueError("failed operation")
    with inventory_transaction() as inventory:
        assert inventory["installations"] == []
