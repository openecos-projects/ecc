import json
from dataclasses import replace
from pathlib import Path

import pytest

from chipcompiler.data.pdk import PDK, apply_pdk_overrides, get_pdk


def test_get_pdk_prefers_explicit_root_over_env(tmp_path, monkeypatch, minimal_ics55_pdk_factory):
    explicit_root = minimal_ics55_pdk_factory(tmp_path / "explicit")
    env_root = minimal_ics55_pdk_factory(tmp_path / "env")
    monkeypatch.setenv("ECC_PDK_ROOT", str(env_root))

    pdk = get_pdk(pdk_name="ics55", pdk_root=explicit_root)

    expected_root = explicit_root.resolve()
    assert isinstance(pdk.root, Path)
    assert isinstance(pdk.tech, Path)
    assert pdk.root == expected_root
    assert pdk.tech.is_relative_to(expected_root)
    assert all(isinstance(path, Path) for path in pdk.lefs + pdk.libs)
    assert all(path.is_relative_to(expected_root) for path in pdk.lefs + pdk.libs)


def test_get_pdk_uses_env_root(tmp_path, monkeypatch, minimal_ics55_pdk_factory):
    env_root = minimal_ics55_pdk_factory(tmp_path / "env")
    monkeypatch.setenv("ECC_PDK_ROOT", str(env_root))

    pdk = get_pdk(pdk_name="ics55", pdk_root="")

    assert pdk.root == env_root.resolve()


def test_get_pdk_raises_on_missing_pdk_files(tmp_path):
    invalid_root = tmp_path / "broken_ics55"
    invalid_root.mkdir(parents=True, exist_ok=True)

    with pytest.raises(ValueError, match="PDK tech LEF is missing"):
        get_pdk("ics55", pdk_root=str(invalid_root))


def test_pdk_ics55_version_absent_resolves_to_v1(tmp_path, minimal_ics55_pdk_factory):
    from chipcompiler.data.pdk import PDK_ICS55

    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")

    pdk = PDK_ICS55(pdk_root=pdk_root)

    resolved_root = pdk_root.resolve()
    stdcell_dir = resolved_root / "IP" / "STD_cell" / "ics55_LLSC_H7C_V1p10C100"
    expected = PDK(
        name="ics55",
        version="v1",
        root=resolved_root,
        tech=resolved_root / "prtech" / "techLEF" / "N551P6M_ecos.lef",
        lefs=[
            stdcell_dir / "ics55_LLSC_H7CR" / "lef" / "ics55_LLSC_H7CR_ecos.lef",
            stdcell_dir / "ics55_LLSC_H7CL" / "lef" / "ics55_LLSC_H7CL_ecos.lef",
        ],
        libs=[
            stdcell_dir
            / "ics55_LLSC_H7CR"
            / "liberty"
            / "ics55_LLSC_H7CR_ss_rcworst_1p08_125_nldm.lib",
            stdcell_dir
            / "ics55_LLSC_H7CL"
            / "liberty"
            / "ics55_LLSC_H7CL_ss_rcworst_1p08_125_nldm.lib",
        ],
        corners=[
            {"name": "TYPICAL", "temperature": [25], "spef_file": "./TYP.spef"},
            {"name": "RCbest", "temperature": [-40, 125], "spef_file": "./RCbest.spef"},
            {"name": "RCworst", "temperature": [-40, 125], "spef_file": "./RCworst.spef"},
            {"name": "Cbest", "temperature": [-40, 125], "spef_file": "./Cbest.spef"},
            {"name": "Cworst", "temperature": [-40, 125], "spef_file": "./Cworst.spef"},
        ],
        site_core="core7",
        site_io="core7",
        site_corner="core7",
        tap_cell="FILLTAPH7R",
        end_cap="FILLTAPH7R",
        buffers=["BUFX8H7L", "BUFX12H7L", "BUFX16H7L", "BUFX20H7L"],
        fillers=[
            "FILLER64H7R",
            "FILLER32H7R",
            "FILLER16H7R",
            "FILLER8H7R",
            "FILLER4H7R",
            "FILLER2H7R",
            "FILLER1H7R",
        ],
        tie_high_cell="TIEHIH7R",
        tie_low_cell="TIELOH7R",
        abc_driver_cell="BUFX0P5H7R",
        abc_load=200.0,
        sdc_load=0.2,
        dont_use=[
            "DFFSRQX*",
            "DFFSRX*",
            "*AO222*",
            "*2BB2*",
            "*AOI222*",
            "*AOI33*",
            "*OA222*",
            "*OAI222*",
            "*OAI33*",
            "*NOR4*",
            "ICG*",
        ],
        latch_cells={
            "$_DLATCH_N_": "LATLX1H7L",
            "$_DLATCH_P_": "LATHX1H7L",
            "$_DLATCH_NN0_": "LATLRX1H7L",
            "$_DLATCH_NN1_": "LATLSX1H7L",
            "$_DLATCH_PN0_": "LATHRX1H7L",
            "$_DLATCH_PN1_": "LATHSX1H7L",
        },
        latch_pins={"data": "D", "reset": "RN", "set": "SN"},
        inverter_cell="INVX1H7L",
        tbuf_cell="TBUFX1H7L",
        tbuf_pins={"data": "A"},
    )

    assert pdk == expected


def test_pdk_ics55_version_v2_marker_resolves_to_v2(tmp_path, minimal_ics55_pdk_factory):
    from chipcompiler.data.pdk import PDK_ICS55

    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55", release="v2")

    pdk = PDK_ICS55(pdk_root=pdk_root)

    resolved_root = pdk_root.resolve()
    stdcell_dir = resolved_root / "IP" / "STD_cell"
    expected = PDK(
        name="ics55",
        version="v2",
        root=resolved_root,
        tech=resolved_root / "prtech" / "techLEF" / "N551P6M_ecos.lef",
        lefs=[
            stdcell_dir / "ICsprout55_SC9T_BASIC_SVT" / "lef" / "ICsprout55_9TSVT_basic.lef",
            stdcell_dir / "ICsprout55_SC9T_BASIC_LVT" / "lef" / "ICsprout55_9TLVT_basic.lef",
            stdcell_dir / "ICsprout55_SC9T_BASIC_HVT" / "lef" / "ICsprout55_9THVT_basic.lef",
        ],
        libs=[
            stdcell_dir
            / "ICsprout55_SC9T_BASIC_SVT"
            / "liberty"
            / "ICsprout55_9TSVT_ss_v1p08_125c_basic_nldm.lib",
            stdcell_dir
            / "ICsprout55_SC9T_BASIC_LVT"
            / "liberty"
            / "ICsprout55_9TLVT_ss_v1p08_125c_basic_nldm.lib",
            stdcell_dir
            / "ICsprout55_SC9T_BASIC_HVT"
            / "liberty"
            / "ICsprout55_9THVT_ss_v1p08_125c_basic_nldm.lib",
        ],
        corners=[
            {"name": "TYPICAL", "temperature": [25], "spef_file": "./TYP.spef"},
            {"name": "RCbest", "temperature": [-40, 125], "spef_file": "./RCbest.spef"},
            {"name": "RCworst", "temperature": [-40, 125], "spef_file": "./RCworst.spef"},
            {"name": "Cbest", "temperature": [-40, 125], "spef_file": "./Cbest.spef"},
            {"name": "Cworst", "temperature": [-40, 125], "spef_file": "./Cworst.spef"},
        ],
        site_core="SC9T_site",
        site_io="IOSite",
        site_corner="CornerSite",
        tap_cell="TAPX1_9TSVT",
        end_cap="TAPX1_9TSVT",
        buffers=["BUFX8_9TLVT", "BUFX12_9TLVT", "BUFX16_9TLVT", "BUFX24_9TLVT"],
        fillers=[
            "FILL32_9TSVT",
            "FILL16_9TSVT",
            "FILL8_9TSVT",
            "FILL4_9TSVT",
            "FILL2_9TSVT",
            "FILL1_9TSVT",
        ],
        tie_high_cell="TIEHIX1_9TSVT",
        tie_low_cell="TIELOX1_9TSVT",
        abc_driver_cell="BUFX0P5_9TSVT",
        abc_load=200.0,
        sdc_load=0.2,
        dont_use=[
            "BENCX*",
            "DFFSRQX*",
            "DFFSRX*",
            "*AO222*",
            "*2BB2*",
            "*AOI222*",
            "*AOI33*",
            "*OA222*",
            "*OAI222*",
            "*OAI33*",
            "*NOR4*",
            "ICG*",
        ],
        latch_cells={
            "$_DLATCH_N_": "LATNQX1_9TLVT",
            "$_DLATCH_P_": "LATQX1_9TLVT",
            "$_DLATCH_NN0_": "LATNRNQX1_9TLVT",
            "$_DLATCH_NN1_": "LATNSNQX1_9TLVT",
            "$_DLATCH_PN0_": "LATRNQX1_9TLVT",
            "$_DLATCH_PN1_": "LATSNQX1_9TLVT",
        },
        latch_pins={"data": "D", "reset": "RN", "set": "SN"},
        inverter_cell="INVX1_9TLVT",
        tbuf_cell="TBUFX1_9TLVT",
        tbuf_pins={"data": "A"},
    )

    assert pdk == expected


def test_pdk_ics55_unrecognized_version_marker_raises(tmp_path):
    from chipcompiler.data.pdk import PDK_ICS55

    pdk_root = tmp_path / "ics55"
    pdk_root.mkdir()
    (pdk_root / "VERSION").write_text("ics55-v3\n")

    with pytest.raises(ValueError, match="unrecognized ICS55 VERSION marker"):
        PDK_ICS55(pdk_root=pdk_root)


def test_get_pdk_sg13g2_prefers_explicit_root_over_env(
    tmp_path, monkeypatch, minimal_sg13g2_pdk_factory
):
    explicit_root = minimal_sg13g2_pdk_factory(tmp_path / "explicit")
    env_root = minimal_sg13g2_pdk_factory(tmp_path / "env")
    monkeypatch.setenv("ECC_PDK_ROOT", str(env_root))

    pdk = get_pdk("sg13g2", pdk_root=explicit_root)

    expected_root = explicit_root.resolve()
    assert isinstance(pdk.root, Path)
    assert isinstance(pdk.tech, Path)
    assert pdk.root == expected_root
    assert pdk.tech.is_relative_to(expected_root)
    assert all(isinstance(path, Path) for path in pdk.lefs + pdk.libs)
    assert all(path.is_relative_to(expected_root) for path in pdk.lefs + pdk.libs)


def test_get_pdk_sg13g2_uses_env_root(tmp_path, monkeypatch, minimal_sg13g2_pdk_factory):
    env_root = minimal_sg13g2_pdk_factory(tmp_path / "env")
    monkeypatch.setenv("ECC_PDK_ROOT", str(env_root))

    pdk = get_pdk("sg13g2")

    assert pdk.root == env_root.resolve()


def test_get_pdk_sg13g2_raises_on_missing_pdk_files(tmp_path, monkeypatch):
    invalid_root = tmp_path / "broken_sg13g2"
    invalid_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ECC_PDK_ROOT", str(invalid_root))

    with pytest.raises(ValueError, match="PDK tech LEF is missing"):
        get_pdk("sg13g2")


def test_get_pdk_sg13g2_cell_config(tmp_path, monkeypatch, minimal_sg13g2_pdk_factory):
    pdk_root = minimal_sg13g2_pdk_factory(tmp_path / "sg13g2")
    monkeypatch.setenv("ECC_PDK_ROOT", str(pdk_root))

    pdk = get_pdk("sg13g2")

    assert pdk.name == "sg13g2"
    assert pdk.site_core == "CoreSite"
    assert pdk.tie_high_cell == "sg13g2_tiehi"
    assert pdk.tie_low_cell == "sg13g2_tielo"
    assert "sg13g2_buf_1" in pdk.buffers
    assert "sg13g2_fill_1" in pdk.fillers
    assert "sg13g2_lgcp_1" in pdk.dont_use


def test_get_pdk_sg13g2_case_insensitive(tmp_path, monkeypatch, minimal_sg13g2_pdk_factory):
    pdk_root = minimal_sg13g2_pdk_factory(tmp_path / "sg13g2")
    monkeypatch.setenv("ECC_PDK_ROOT", str(pdk_root))

    pdk = get_pdk("SG13G2")

    assert pdk.name == "sg13g2"


def test_apply_pdk_overrides_replaces_whole_field(tmp_path, minimal_ics55_pdk_factory):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    base_pdk = get_pdk("ics55", pdk_root=pdk_root)

    overridden = apply_pdk_overrides(base_pdk, {"dont_use": ["ICG*"]})
    expected = replace(base_pdk, dont_use=["ICG*"])

    assert overridden == expected


def test_apply_pdk_overrides_nonexistent_optional_path_stays_pure(
    tmp_path, minimal_ics55_pdk_factory
):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    base_pdk = get_pdk("ics55", pdk_root=pdk_root)
    missing_sdc = tmp_path / "missing.sdc"

    overridden = apply_pdk_overrides(base_pdk, {"sdc": str(missing_sdc)})

    assert overridden == replace(base_pdk, sdc=str(missing_sdc))


def test_apply_pdk_overrides_empty_dict_is_noop(tmp_path, minimal_ics55_pdk_factory):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    base_pdk = get_pdk("ics55", pdk_root=pdk_root)

    overridden = apply_pdk_overrides(base_pdk, {})

    assert overridden is base_pdk


def test_apply_pdk_overrides_unknown_key_raises(tmp_path, minimal_ics55_pdk_factory):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    base_pdk = get_pdk("ics55", pdk_root=pdk_root)

    with pytest.raises(ValueError) as exc_info:
        apply_pdk_overrides(base_pdk, {"dontuse": ["ICG*"]})

    error_msg = str(exc_info.value)
    assert "dontuse" in error_msg
    assert "valid overridable fields" in error_msg
    assert "dont_use" in error_msg
    assert "name" not in error_msg.split("valid overridable fields:")[-1]
    assert "version" not in error_msg.split("valid overridable fields:")[-1]
    assert "root" not in error_msg.split("valid overridable fields:")[-1]


def test_apply_pdk_overrides_type_mismatch_list_field(tmp_path, minimal_ics55_pdk_factory):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    base_pdk = get_pdk("ics55", pdk_root=pdk_root)

    with pytest.raises(ValueError, match="must be a list.*got str"):
        apply_pdk_overrides(base_pdk, {"dont_use": "ICG*"})


@pytest.mark.parametrize("field", ["lefs", "libs", "buffers", "fillers", "dont_use"])
def test_apply_pdk_overrides_rejects_non_string_list_element(
    tmp_path, minimal_ics55_pdk_factory, field
):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    base_pdk = get_pdk("ics55", pdk_root=pdk_root)

    with pytest.raises(
        ValueError,
        match=f"PDK override '{field}' elements must be strings, got int at index 1",
    ):
        apply_pdk_overrides(base_pdk, {field: ["ok", 1]})


def test_apply_pdk_overrides_type_mismatch_float_field(tmp_path, minimal_ics55_pdk_factory):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    base_pdk = get_pdk("ics55", pdk_root=pdk_root)

    with pytest.raises(ValueError, match="must be a number.*got str"):
        apply_pdk_overrides(base_pdk, {"abc_load": "fast"})


def test_apply_pdk_overrides_type_mismatch_dict_field(tmp_path, minimal_ics55_pdk_factory):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    base_pdk = get_pdk("ics55", pdk_root=pdk_root)

    with pytest.raises(ValueError, match="must be a dict.*got list"):
        apply_pdk_overrides(base_pdk, {"latch_cells": ["ICG*"]})


def test_apply_pdk_overrides_name_rejected(tmp_path, minimal_ics55_pdk_factory):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    base_pdk = get_pdk("ics55", pdk_root=pdk_root)

    with pytest.raises(ValueError, match="'name'.*cannot be overridden"):
        apply_pdk_overrides(base_pdk, {"name": "custom"})


def test_apply_pdk_overrides_version_rejected(tmp_path, minimal_ics55_pdk_factory):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    base_pdk = get_pdk("ics55", pdk_root=pdk_root)

    with pytest.raises(ValueError, match="'version'.*cannot be overridden"):
        apply_pdk_overrides(base_pdk, {"version": "custom"})


def test_apply_pdk_overrides_root_rejected(tmp_path, minimal_ics55_pdk_factory):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    base_pdk = get_pdk("ics55", pdk_root=pdk_root)

    with pytest.raises(ValueError, match="'root'.*cannot be overridden"):
        apply_pdk_overrides(base_pdk, {"root": "/other/pdk"})


def test_get_pdk_overrides_none_is_noop(tmp_path, minimal_ics55_pdk_factory):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")

    pdk_default = get_pdk("ics55", pdk_root=pdk_root)
    pdk_with_none = get_pdk("ics55", pdk_root=pdk_root, overrides=None)

    assert pdk_with_none == pdk_default


def test_get_pdk_overrides_unknown_key_raises(tmp_path, minimal_ics55_pdk_factory):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")

    with pytest.raises(ValueError, match="unknown PDK override fields"):
        get_pdk("ics55", pdk_root=pdk_root, overrides={"bogus": 1})


def test_get_pdk_overrides_applied_and_validated(tmp_path, minimal_ics55_pdk_factory):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")

    pdk = get_pdk("ics55", pdk_root=pdk_root, overrides={"dont_use": ["DFFSRQX*"]})

    assert pdk.dont_use == ["DFFSRQX*"]

    with pytest.raises(ValueError, match="PDK tech LEF not found"):
        get_pdk("ics55", pdk_root=pdk_root, overrides={"tech": "/no/such.lef"})


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("mapping_file", "PDK mapping file not found"),
        ("sdc", "PDK SDC file not found"),
        ("spef", "PDK SPEF file not found"),
    ],
)
def test_get_pdk_optional_path_override_nonexistent_raises(
    tmp_path, minimal_ics55_pdk_factory, field, message
):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")

    with pytest.raises(ValueError, match=message):
        get_pdk("ics55", pdk_root=pdk_root, overrides={field: "/no/such.file"})


@pytest.mark.parametrize("field", ["mapping_file", "sdc", "spef"])
def test_get_pdk_optional_path_override_existing_ok(tmp_path, minimal_ics55_pdk_factory, field):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    real_file = tmp_path / f"{field}.file"
    real_file.write_text("content\n")

    pdk = get_pdk("ics55", pdk_root=pdk_root, overrides={field: str(real_file)})

    assert getattr(pdk, field) == real_file


def test_pdk_validate_optional_paths_absent_ok(tmp_path, minimal_ics55_pdk_factory):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")

    pdk = get_pdk("ics55", pdk_root=pdk_root)

    assert pdk.mapping_file is None
    assert pdk.spef is None


def test_get_pdk_detects_layer_map_directly(tmp_path, minimal_ics55_pdk_factory):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    layer_map = pdk_root / "techfile" / "icsprout55.layermap"
    layer_map.parent.mkdir()
    layer_map.write_text("MET1 drawing 11 0\n", encoding="utf-8")

    pdk = get_pdk("ics55", pdk_root=pdk_root)

    assert pdk.mapping_file == layer_map


def test_builtin_pdk_external_config_keeps_explicit_buffer_override(
    tmp_path, minimal_ics55_pdk_factory
):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    pdk_config = tmp_path / "pdk.json"
    pdk_config.write_text(
        json.dumps(
            {
                "name": "ics55",
                "root": str(pdk_root),
                "buffers": ["CUSTOM_BUFFER"],
            }
        )
    )

    pdk = get_pdk("ics55", pdk_config=pdk_config)

    assert pdk.buffers == ["CUSTOM_BUFFER"]
