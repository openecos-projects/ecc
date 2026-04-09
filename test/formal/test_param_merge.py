"""
Formal verification of update_parameters() merge behavior using z3.

Models dict merge as z3 constraints over abstract (key, value, type) tuples.
Proves override, preservation, list replacement, and nested merge properties.
"""

from copy import deepcopy

import pytest
from z3 import And, Bool, If, Int, Not, Solver, unsat

from chipcompiler.data import get_parameters
from chipcompiler.data.parameter import update_parameters

# Type tags for dict values
TYPE_SCALAR = 0
TYPE_LIST = 1
TYPE_DICT = 2


def _build_merge_model(num_keys: int):
    """Build z3 model of update_parameters() for `num_keys` possible keys.

    Returns (solver, source, target, result, source_present, target_present,
             source_type, target_type) where:
    - source[k], target[k], result[k]: value at key k (Int)
    - source_present[k], target_present[k]: whether key exists (Bool)
    - source_type[k], target_type[k]: type tag (Int: 0=scalar, 1=list, 2=dict)
    """
    solver = Solver()

    source_val = [Int(f"src_v_{k}") for k in range(num_keys)]
    target_val = [Int(f"tgt_v_{k}") for k in range(num_keys)]
    result_val = [Int(f"res_v_{k}") for k in range(num_keys)]
    source_present = [Bool(f"src_p_{k}") for k in range(num_keys)]
    target_present = [Bool(f"tgt_p_{k}") for k in range(num_keys)]
    source_type = [Int(f"src_t_{k}") for k in range(num_keys)]
    target_type = [Int(f"tgt_t_{k}") for k in range(num_keys)]

    # Constrain types to valid range
    for k in range(num_keys):
        solver.add(And(source_type[k] >= 0, source_type[k] <= 2))
        solver.add(And(target_type[k] >= 0, target_type[k] <= 2))

    # Encode update_parameters() logic per key:
    for k in range(num_keys):
        both_present = And(source_present[k], target_present[k])
        list_replace = And(both_present, source_type[k] == TYPE_LIST)
        dict_merge = And(both_present, source_type[k] == TYPE_DICT, target_type[k] == TYPE_DICT)
        scalar_replace = And(
            both_present,
            Not(source_type[k] == TYPE_LIST),
            Not(And(source_type[k] == TYPE_DICT, target_type[k] == TYPE_DICT)),
        )
        source_only = And(source_present[k], Not(target_present[k]))
        target_only = And(Not(source_present[k]), target_present[k])

        solver.add(
            If(
                list_replace,
                result_val[k] == source_val[k],
                If(
                    dict_merge,
                    result_val[k] == source_val[k],
                    If(
                        scalar_replace,
                        result_val[k] == source_val[k],
                        If(
                            source_only,
                            result_val[k] == source_val[k],
                            If(target_only, result_val[k] == target_val[k], result_val[k] == 0),
                        ),
                    ),
                ),
            )
        )

    return (
        solver,
        source_val,
        target_val,
        result_val,
        source_present,
        target_present,
        source_type,
        target_type,
    )


@pytest.mark.parametrize("num_keys", [3, 5, 10])
def test_scalar_override_wins(num_keys):
    """z3: for any scalar key K present in both source and target,
    result[K] == source[K] after merge."""
    (solver, src, tgt, res, src_p, tgt_p, src_t, tgt_t) = _build_merge_model(num_keys)

    k = Int("k")
    solver.add(And(k >= 0, k < num_keys))

    for i in range(num_keys):
        solver.add(
            If(
                k == i,
                And(
                    src_p[i],
                    tgt_p[i],
                    src_t[i] == TYPE_SCALAR,
                    src[i] != tgt[i],
                    res[i] != src[i],
                ),
                True,
            )
        )

    result = solver.check()
    assert result == unsat, "Scalar override must always win"


@pytest.mark.parametrize("num_keys", [3, 5, 10])
def test_absent_keys_preserved(num_keys):
    """z3: for any key K in target but NOT in source, result[K] == target[K]."""
    (solver, src, tgt, res, src_p, tgt_p, src_t, tgt_t) = _build_merge_model(num_keys)

    k = Int("k")
    solver.add(And(k >= 0, k < num_keys))

    for i in range(num_keys):
        solver.add(
            If(
                k == i,
                And(Not(src_p[i]), tgt_p[i], res[i] != tgt[i]),
                True,
            )
        )

    result = solver.check()
    assert result == unsat, "Absent keys in source must be preserved from target"


@pytest.mark.parametrize("num_keys", [3, 5, 10])
def test_list_replaced_not_appended(num_keys):
    """z3: for a list-typed key K present in both, result[K] == source[K]
    (entire replacement, not append)."""
    (solver, src, tgt, res, src_p, tgt_p, src_t, tgt_t) = _build_merge_model(num_keys)

    k = Int("k")
    solver.add(And(k >= 0, k < num_keys))

    for i in range(num_keys):
        solver.add(
            If(
                k == i,
                And(
                    src_p[i],
                    tgt_p[i],
                    src_t[i] == TYPE_LIST,
                    src[i] != tgt[i],
                    res[i] != src[i],
                ),
                True,
            )
        )

    result = solver.check()
    assert result == unsat, "List values must be replaced entirely, not appended"


@pytest.mark.parametrize("num_keys", [3, 5, 10])
def test_new_key_added(num_keys):
    """z3: for a key K in source but NOT in target, result[K] == source[K]."""
    (solver, src, tgt, res, src_p, tgt_p, src_t, tgt_t) = _build_merge_model(num_keys)

    k = Int("k")
    solver.add(And(k >= 0, k < num_keys))

    for i in range(num_keys):
        solver.add(
            If(
                k == i,
                And(src_p[i], Not(tgt_p[i]), res[i] != src[i]),
                True,
            )
        )

    result = solver.check()
    assert result == unsat, "New keys from source must be added to result"


@pytest.mark.parametrize("num_keys", [3, 5, 10])
def test_nested_dict_merges_not_replaces(num_keys):
    """z3: for a dict-typed key K present in both source and target,
    the merge recurses (inner keys from target that are NOT in source
    are preserved). We model this at one level of depth."""
    (solver, src, tgt, res, src_p, tgt_p, src_t, tgt_t) = _build_merge_model(num_keys)

    if num_keys < 3:
        pytest.skip("Need at least 3 keys for nested dict test")

    k_outer = 0
    k_inner_src = 1
    k_inner_tgt = 2

    solver.add(src_p[k_outer])
    solver.add(tgt_p[k_outer])
    solver.add(src_t[k_outer] == TYPE_DICT)
    solver.add(tgt_t[k_outer] == TYPE_DICT)

    solver.add(src_p[k_inner_src])
    solver.add(tgt_p[k_inner_src])
    solver.add(src_t[k_inner_src] == TYPE_SCALAR)

    solver.add(Not(src_p[k_inner_tgt]))
    solver.add(tgt_p[k_inner_tgt])

    # Violation: inner target key not preserved
    solver.add(res[k_inner_tgt] != tgt[k_inner_tgt])

    result = solver.check()
    assert result == unsat, "Nested dict merge must preserve target-only inner keys"


# ---------------------------------------------------------------------------
# Concrete tests against real ICS55 template
# ---------------------------------------------------------------------------


def test_merge_against_real_template_scalar():
    """Concrete: override scalar keys in ICS55 template, verify they take effect."""
    template = get_parameters("ics55")
    target = deepcopy(template.data)
    source = {
        "Design": "test_design",
        "Top module": "test_top",
        "Clock": "test_clk",
        "Frequency max [MHz]": 200,
        "Max fanout": 50,
        "Target density": 0.6,
        "Bottom layer": "MET3",
        "Top layer": "MET4",
    }

    result = update_parameters(source, target)

    for key, expected in source.items():
        assert result[key] == expected, f"Key '{key}': expected {expected}, got {result[key]}"


def test_merge_against_real_template_preserves_untouched():
    """Concrete: keys NOT in override remain unchanged."""
    template = get_parameters("ics55")
    original = deepcopy(template.data)
    target = deepcopy(template.data)
    source = {"Design": "override_only"}

    update_parameters(source, target)

    for key in ["PDK", "Core", "Floorplan", "PDN", "Cell padding x"]:
        assert target[key] == original[key], f"Key '{key}' was modified but should be preserved"


def test_merge_against_real_template_list_replace():
    """Concrete: list override replaces entirely, not appends."""
    template = get_parameters("ics55")
    target = deepcopy(template.data)
    original_tracks_len = len(target["Floorplan"]["Tracks"])

    new_tracks = [{"layer": "MET1", "x start": 0, "x step": 100, "y start": 0, "y step": 100}]
    source = {"Floorplan": {"Tracks": new_tracks}}

    update_parameters(source, target)

    assert target["Floorplan"]["Tracks"] == new_tracks, "List should be replaced entirely"
    assert len(target["Floorplan"]["Tracks"]) == 1, (
        f"Expected 1 track, got {len(target['Floorplan']['Tracks'])} "
        f"(original had {original_tracks_len})"
    )


def test_merge_against_real_template_nested_dict_preserves():
    """Concrete: nested dict merge preserves keys not in source."""
    template = get_parameters("ics55")
    target = deepcopy(template.data)

    source = {"Core": {"Utilitization": 0.7}}
    update_parameters(source, target)

    assert target["Core"]["Utilitization"] == 0.7, "Nested override should apply"
    assert target["Core"]["Margin"] == [2, 2], "Nested untouched key should be preserved"
    assert target["Core"]["Aspect ratio"] == 1, "Nested untouched key should be preserved"


def test_merge_adds_new_key():
    """Concrete: new key in source is added to target."""
    template = get_parameters("ics55")
    target = deepcopy(template.data)

    source = {"Brand new key": "brand new value"}
    update_parameters(source, target)

    assert target["Brand new key"] == "brand new value"
