from pathlib import Path

import pytest

from chipcompiler.data.pdk import apply_pdk_overrides, get_pdk


def test_get_pdk_prefers_explicit_root_over_env(tmp_path, monkeypatch, minimal_ics55_pdk_factory):
    explicit_root = minimal_ics55_pdk_factory(tmp_path / "explicit")
    env_root = minimal_ics55_pdk_factory(tmp_path / "env")
    monkeypatch.setenv("CHIPCOMPILER_ICS55_PDK_ROOT", str(env_root))

    pdk = get_pdk(pdk_name="ics55", pdk_root=explicit_root)

    expected_root = explicit_root.resolve()
    assert isinstance(pdk.root, Path)
    assert isinstance(pdk.tech, Path)
    assert pdk.root == expected_root
    assert pdk.tech.is_relative_to(expected_root)
    assert all(isinstance(path, Path) for path in pdk.lefs + pdk.libs)
    assert all(path.is_relative_to(expected_root) for path in pdk.lefs + pdk.libs)


def test_get_pdk_uses_namespaced_env(tmp_path, monkeypatch, minimal_ics55_pdk_factory):
    env_root = minimal_ics55_pdk_factory(tmp_path / "env")
    monkeypatch.setenv("CHIPCOMPILER_ICS55_PDK_ROOT", str(env_root))
    monkeypatch.delenv("ICS55_PDK_ROOT", raising=False)

    pdk = get_pdk(pdk_name="ics55", pdk_root="")

    assert pdk.root == env_root.resolve()


def test_get_pdk_uses_legacy_env_when_namespaced_missing(
    tmp_path, monkeypatch, minimal_ics55_pdk_factory
):
    legacy_root = minimal_ics55_pdk_factory(tmp_path / "legacy")
    monkeypatch.delenv("CHIPCOMPILER_ICS55_PDK_ROOT", raising=False)
    monkeypatch.setenv("ICS55_PDK_ROOT", str(legacy_root))

    pdk = get_pdk(pdk_name="ics55", pdk_root="")

    assert pdk.root == legacy_root.resolve()


def test_get_pdk_raises_on_missing_pdk_files(tmp_path):
    invalid_root = tmp_path / "broken_ics55"
    invalid_root.mkdir(parents=True, exist_ok=True)

    with pytest.raises(ValueError, match="PDK validation failed"):
        get_pdk("ics55", pdk_root=str(invalid_root))


def test_get_pdk_sg13g2_prefers_explicit_root_over_env(
    tmp_path, monkeypatch, minimal_sg13g2_pdk_factory
):
    explicit_root = minimal_sg13g2_pdk_factory(tmp_path / "explicit")
    env_root = minimal_sg13g2_pdk_factory(tmp_path / "env")
    monkeypatch.setenv("CHIPCOMPILER_SG13G2_PDK_ROOT", str(env_root))

    pdk = get_pdk("sg13g2", pdk_root=explicit_root)

    expected_root = explicit_root.resolve()
    assert isinstance(pdk.root, Path)
    assert isinstance(pdk.tech, Path)
    assert pdk.root == expected_root
    assert pdk.tech.is_relative_to(expected_root)
    assert all(isinstance(path, Path) for path in pdk.lefs + pdk.libs)
    assert all(path.is_relative_to(expected_root) for path in pdk.lefs + pdk.libs)


def test_get_pdk_sg13g2_uses_namespaced_env(tmp_path, monkeypatch, minimal_sg13g2_pdk_factory):
    env_root = minimal_sg13g2_pdk_factory(tmp_path / "env")
    monkeypatch.setenv("CHIPCOMPILER_SG13G2_PDK_ROOT", str(env_root))
    monkeypatch.delenv("SG13G2_PDK_ROOT", raising=False)

    pdk = get_pdk("sg13g2")

    assert pdk.root == env_root.resolve()


def test_get_pdk_sg13g2_uses_legacy_env_when_namespaced_missing(
    tmp_path, monkeypatch, minimal_sg13g2_pdk_factory
):
    legacy_root = minimal_sg13g2_pdk_factory(tmp_path / "legacy")
    monkeypatch.delenv("CHIPCOMPILER_SG13G2_PDK_ROOT", raising=False)
    monkeypatch.setenv("SG13G2_PDK_ROOT", str(legacy_root))

    pdk = get_pdk("sg13g2")

    assert pdk.root == legacy_root.resolve()


def test_get_pdk_sg13g2_raises_on_missing_pdk_files(tmp_path, monkeypatch):
    invalid_root = tmp_path / "broken_sg13g2"
    invalid_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CHIPCOMPILER_SG13G2_PDK_ROOT", str(invalid_root))

    with pytest.raises(ValueError, match="PDK validation failed"):
        get_pdk("sg13g2")


def test_get_pdk_sg13g2_cell_config(tmp_path, monkeypatch, minimal_sg13g2_pdk_factory):
    pdk_root = minimal_sg13g2_pdk_factory(tmp_path / "sg13g2")
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


def test_get_pdk_sg13g2_case_insensitive(tmp_path, monkeypatch, minimal_sg13g2_pdk_factory):
    pdk_root = minimal_sg13g2_pdk_factory(tmp_path / "sg13g2")
    monkeypatch.setenv("CHIPCOMPILER_SG13G2_PDK_ROOT", str(pdk_root))

    pdk = get_pdk("SG13G2")

    assert pdk.name == "sg13g2"


def test_apply_pdk_overrides_replaces_whole_field(tmp_path, minimal_ics55_pdk_factory):
    from dataclasses import replace

    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    base_pdk = get_pdk("ics55", pdk_root=pdk_root)

    overridden = apply_pdk_overrides(base_pdk, {"dont_use": ["ICG*"]})
    expected = replace(base_pdk, dont_use=["ICG*"])

    assert overridden == expected


def test_apply_pdk_overrides_nonexistent_optional_path_stays_pure(
    tmp_path, minimal_ics55_pdk_factory
):
    from dataclasses import replace

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
    assert "name" not in error_msg or "name" not in error_msg.split("valid overridable fields:")[-1]
    assert (
        "version" not in error_msg
        or "version" not in error_msg.split("valid overridable fields:")[-1]
    )


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


def test_get_pdk_with_overrides(tmp_path, minimal_ics55_pdk_factory):
    from dataclasses import replace

    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    base_pdk = get_pdk("ics55", pdk_root=pdk_root)

    pdk = get_pdk("ics55", pdk_root=pdk_root, overrides={"dont_use": ["DFFSRQX*"]})
    expected = replace(base_pdk, dont_use=["DFFSRQX*"])

    assert pdk == expected


def test_get_pdk_overrides_none_is_noop(tmp_path, minimal_ics55_pdk_factory):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")

    pdk_default = get_pdk("ics55", pdk_root=pdk_root)
    pdk_with_none = get_pdk("ics55", pdk_root=pdk_root, overrides=None)

    assert pdk_with_none == pdk_default


def test_get_pdk_overrides_unknown_key_raises(tmp_path, minimal_ics55_pdk_factory):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")

    with pytest.raises(ValueError, match="unknown PDK override fields"):
        get_pdk("ics55", pdk_root=pdk_root, overrides={"bogus": 1})


def test_get_pdk_overrides_validated(tmp_path, minimal_ics55_pdk_factory):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")

    with pytest.raises(ValueError, match="PDK validation failed"):
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
