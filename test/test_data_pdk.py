#!/usr/bin/env python

from pathlib import Path

import pytest

from chipcompiler.data.pdk import get_pdk

import os, sys
current_dir = os.path.split(os.path.abspath(__file__))[0]
root = current_dir.rsplit('/', 1)[0]
sys.path.append(root)

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

    pdk = get_pdk(pdk_name="ics55", pdk_root=str(explicit_root))

    expected_root = str(explicit_root.resolve())
    assert pdk.root == expected_root
    assert pdk.tech.startswith(expected_root)
    assert all(path.startswith(expected_root) for path in pdk.lefs + pdk.libs)


def test_get_pdk_uses_namespaced_env(tmp_path, monkeypatch):
    env_root = _create_minimal_ics55_pdk(tmp_path / "env")
    monkeypatch.setenv("CHIPCOMPILER_ICS55_PDK_ROOT", str(env_root))
    monkeypatch.delenv("ICS55_PDK_ROOT", raising=False)

    pdk = get_pdk(pdk_name= "ics55", 
                  pdk_root="{}/../icsprout55-pdk".format(root))

    assert pdk.root == str(env_root.resolve())


def test_get_pdk_uses_legacy_env_when_namespaced_missing(tmp_path, monkeypatch):
    legacy_root = _create_minimal_ics55_pdk(tmp_path / "legacy")
    monkeypatch.delenv("CHIPCOMPILER_ICS55_PDK_ROOT", raising=False)
    monkeypatch.setenv("ICS55_PDK_ROOT", str(legacy_root))

    pdk = get_pdk(pdk_name= "ics55", 
                  pdk_root="{}/../icsprout55-pdk".format(root))

    assert pdk.root == str(legacy_root.resolve())


def test_get_pdk_raises_on_missing_pdk_files(tmp_path):
    invalid_root = tmp_path / "broken_ics55"
    invalid_root.mkdir(parents=True, exist_ok=True)

    with pytest.raises(ValueError, match="PDK validation failed"):
        get_pdk("ics55", pdk_root=str(invalid_root))


#SG13G2 helpers and tests

def _create_minimal_sg13g2_pdk(root: Path) -> Path:
    """Create the minimal SG13G2 directory tree required by get_pdk()."""
    tech_path = root / "libs.ref" / "sg13g2_stdcell" / "lef" / "sg13g2_tech.lef"
    tech_path.parent.mkdir(parents=True, exist_ok=True)
    tech_path.write_text("VERSION 5.8 ;\n")

    lef_path = root / "libs.ref" / "sg13g2_stdcell" / "lef" / "sg13g2_stdcell.lef"
    lef_path.write_text("VERSION 5.8 ;\n")

    lib_path = root / "libs.ref" / "sg13g2_stdcell" / "lib" / "sg13g2_stdcell_typ_1p20V_25C.lib"
    lib_path.parent.mkdir(parents=True, exist_ok=True)
    lib_path.write_text("library(test) { }\n")

    return root


def test_get_pdk_sg13g2_prefers_explicit_root_over_env(tmp_path, monkeypatch):
    explicit_root = _create_minimal_sg13g2_pdk(tmp_path / "explicit")
    env_root = _create_minimal_sg13g2_pdk(tmp_path / "env")
    monkeypatch.setenv("CHIPCOMPILER_SG13G2_PDK_ROOT", str(env_root))

    pdk = get_pdk("sg13g2", pdk_root=str(explicit_root))

    expected_root = str(explicit_root.resolve())
    assert pdk.root == expected_root
    assert pdk.tech.startswith(expected_root)
    assert all(path.startswith(expected_root) for path in pdk.lefs + pdk.libs)


def test_get_pdk_sg13g2_uses_namespaced_env(tmp_path, monkeypatch):
    env_root = _create_minimal_sg13g2_pdk(tmp_path / "env")
    monkeypatch.setenv("CHIPCOMPILER_SG13G2_PDK_ROOT", str(env_root))
    monkeypatch.delenv("SG13G2_PDK_ROOT", raising=False)

    pdk = get_pdk("sg13g2")

    assert pdk.root == str(env_root.resolve())


def test_get_pdk_sg13g2_uses_legacy_env_when_namespaced_missing(tmp_path, monkeypatch):
    legacy_root = _create_minimal_sg13g2_pdk(tmp_path / "legacy")
    monkeypatch.delenv("CHIPCOMPILER_SG13G2_PDK_ROOT", raising=False)
    monkeypatch.setenv("SG13G2_PDK_ROOT", str(legacy_root))

    pdk = get_pdk("sg13g2")

    assert pdk.root == str(legacy_root.resolve())


def test_get_pdk_sg13g2_raises_on_missing_pdk_files(tmp_path, monkeypatch):
    invalid_root = tmp_path / "broken_sg13g2"
    invalid_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CHIPCOMPILER_SG13G2_PDK_ROOT", str(invalid_root))

    with pytest.raises(ValueError, match="PDK validation failed"):
        get_pdk("sg13g2")


def test_get_pdk_sg13g2_cell_config(tmp_path, monkeypatch):
    pdk_root = _create_minimal_sg13g2_pdk(tmp_path / "sg13g2")
    monkeypatch.setenv("CHIPCOMPILER_SG13G2_PDK_ROOT", str(pdk_root))

    pdk = get_pdk("sg13g2")

    assert pdk.name == "sg13g2"
    assert pdk.site_core == "CoreSite"
    assert pdk.tie_high_cell == "sg13g2_tiehi"
    assert pdk.tie_high_port == "L_HI"
    assert pdk.tie_low_cell == "sg13g2_tielo"
    assert pdk.tie_low_port == "L_LO"
    assert "sg13g2_buf_1" in pdk.buffers
    assert "sg13g2_fill_1" in pdk.fillers
    assert "sg13g2_lgcp_1" in pdk.dont_use


def test_get_pdk_sg13g2_case_insensitive(tmp_path, monkeypatch):
    pdk_root = _create_minimal_sg13g2_pdk(tmp_path / "sg13g2")
    monkeypatch.setenv("CHIPCOMPILER_SG13G2_PDK_ROOT", str(pdk_root))

    pdk = get_pdk("SG13G2")

    assert pdk.name == "sg13g2"
