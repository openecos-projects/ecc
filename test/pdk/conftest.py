import pytest


@pytest.fixture(autouse=True)
def isolated_pdk_management(tmp_path_factory, monkeypatch):
    monkeypatch.setenv(
        "ECC_PDK_INVENTORY", str(tmp_path_factory.mktemp("ecc-state") / "inventory.json")
    )
