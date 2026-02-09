#!/usr/bin/env python

from pathlib import Path

from chipcompiler.data.pdk import get_pdk


def _create_minimal_ics55_pdk(root: Path) -> Path:
    """Create the minimal ICS55 directory tree required by get_pdk()."""
    tech_path = root / "prtech" / "techLEF" / "N551P6M.lef"
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


def test_get_pdk_prefers_explicit_root_over_env(tmp_path, monkeypatch):
    explicit_root = _create_minimal_ics55_pdk(tmp_path / "explicit")
    env_root = _create_minimal_ics55_pdk(tmp_path / "env")
    monkeypatch.setenv("CHIPCOMPILER_ICS55_PDK_ROOT", str(env_root))

    pdk = get_pdk("ics55", pdk_root=str(explicit_root))

    expected_root = str(explicit_root.resolve())
    assert pdk.root == expected_root
    assert pdk.tech.startswith(expected_root)
    assert all(path.startswith(expected_root) for path in pdk.lefs + pdk.libs)


def test_get_pdk_uses_namespaced_env(tmp_path, monkeypatch):
    env_root = _create_minimal_ics55_pdk(tmp_path / "env")
    monkeypatch.setenv("CHIPCOMPILER_ICS55_PDK_ROOT", str(env_root))
    monkeypatch.delenv("ICS55_PDK_ROOT", raising=False)

    pdk = get_pdk("ics55")

    assert pdk.root == str(env_root.resolve())


def test_get_pdk_uses_legacy_env_when_namespaced_missing(tmp_path, monkeypatch):
    legacy_root = _create_minimal_ics55_pdk(tmp_path / "legacy")
    monkeypatch.delenv("CHIPCOMPILER_ICS55_PDK_ROOT", raising=False)
    monkeypatch.setenv("ICS55_PDK_ROOT", str(legacy_root))

    pdk = get_pdk("ics55")

    assert pdk.root == str(legacy_root.resolve())


def test_get_pdk_allows_partial_root_without_forcing_paths(tmp_path):
    invalid_root = tmp_path / "broken_ics55"
    invalid_root.mkdir(parents=True, exist_ok=True)

    pdk = get_pdk("ics55", pdk_root=str(invalid_root))
    assert pdk.root == str(invalid_root.resolve())
    assert pdk.tech == ""
    assert pdk.lefs == []
    assert pdk.libs == []
