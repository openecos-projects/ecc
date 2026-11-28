import pytest

from chipcompiler.data.workspace.sta_liberty import select_liberty_group, validate_liberty_groups


def test_rc_specific_group_replaces_default_without_mixing_macro_models():
    common = {"corner": "MIN", "temperature": -40, "path": ["std.lib"]}
    rc = {**common, "rc_corner": "Cbest", "path": ["std.lib", "macro_cbest.lib"]}
    groups = [rc, common]
    validate_liberty_groups(groups)
    assert [select_liberty_group(groups, "MIN", corner) for corner in ("Cbest", "RCworst")] == [
        rc,
        common,
    ]
    assert select_liberty_group([rc], "MIN", "RCworst") is None


@pytest.mark.parametrize(
    "override, message",
    [
        ({}, "Ambiguous"),
        ({"rc_corner": "Cbest", "temperature": 125}, "same temperature"),
        ({"rc_corner": ""}, "nonempty"),
    ],
)
def test_invalid_scenario_mapping_is_rejected(override, message):
    group = {"corner": "MIN", "temperature": -40, "path": ["std.lib"]}
    with pytest.raises(ValueError, match=message):
        validate_liberty_groups([group, {**group, **override}])


def test_ambiguous_selected_rc_group_is_not_resolved_by_list_order():
    group = {"corner": "MIN", "rc_corner": "Cbest", "temperature": -40, "path": ["std.lib"]}
    with pytest.raises(ValueError, match="Ambiguous"):
        select_liberty_group([group, group], "MIN", "Cbest")


@pytest.mark.parametrize("paths", ["macro.lib", [""], [1], ["std.lib"], ["min.lib", "min.lib"]])
def test_min_models_must_be_explicit_distinct_paths(paths):
    group = {"corner": "MIN", "temperature": -40, "path": ["std.lib"], "min_path": paths}
    with pytest.raises(ValueError, match="min_path"):
        validate_liberty_groups([group])
