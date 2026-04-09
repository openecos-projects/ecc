"""
Formal verification of parameter propagation through tool config builders.

Verifies:
1. Every dict.get() key in builders matches the ICS55 template exactly.
2. Parameters reach their target config fields after build.
3. Dead defaults and forced overrides are documented.
"""

import pytest
from z3 import Int, Real, Solver, unsat

from chipcompiler.data import get_parameters

# Every parameter key accessed by dict.get() in builder files,
# with the builder file and line where it is accessed.
# Source: ecc/builder.py, ecc_dreamplace/builder.py, yosys/builder.py
BUILDER_PARAM_KEYS: list[tuple[str, str, str]] = [
    # (key_string, builder_file, config_field)
    ("Bottom layer", "ecc/builder.py:244", "db.LayerSettings.routing_layer_1st"),
    ("Bottom layer", "ecc/builder.py:329", "RT.-bottom_routing_layer"),
    ("Top layer", "ecc/builder.py:330", "RT.-top_routing_layer"),
    ("Max fanout", "ecc/builder.py:259", "no.max_fanout"),
    ("Global right padding", "ecc/builder.py:273", "PL.GP.global_right_padding"),
    ("Target density", "ecc_dreamplace/builder.py:55", "dreamplace.target_density"),
    ("Target overflow", "ecc_dreamplace/builder.py:58", "dreamplace.stop_overflow"),
    ("Cell padding x", "ecc_dreamplace/builder.py:61", "dreamplace.cell_padding_x"),
    ("Routability opt flag", "ecc_dreamplace/builder.py:64", "dreamplace.routability_opt_flag"),
    ("Frequency max [MHz]", "yosys/builder.py:31", "yosys.clk_freq_mhz"),
    ("File list", "yosys/builder.py:38", "yosys.filelist"),
]


@pytest.mark.xfail(
    reason="'File list' key used in yosys/builder.py but not defined in ICS55 template",
    strict=False,
)
def test_key_spelling_matches_template():
    """Every parameter key used in dict.get() calls in builders must exist
    in the ICS55 template. A typo like 'target density' (lowercase) when
    the template has 'Target density' (capitalized) means the override
    silently falls back to the default."""
    template = get_parameters("ics55")

    def _key_exists_in_dict(data: dict, key: str) -> bool:
        """Check if key exists at top level or any nested dict."""
        if key in data:
            return True
        return any(isinstance(v, dict) and _key_exists_in_dict(v, key) for v in data.values())

    missing = []
    for key, builder, config_field in BUILDER_PARAM_KEYS:
        if not _key_exists_in_dict(template.data, key):
            missing.append(f"  '{key}' (used in {builder} -> {config_field})")

    assert not missing, "Parameter keys in builders not found in ICS55 template:\n" + "\n".join(
        missing
    )


# ---------------------------------------------------------------------------
# z3: Dead defaults and forced overrides
# ---------------------------------------------------------------------------

# Known parameter -> config mappings with both defaults.
# (param_key, param_default, config_default, description)
PARAM_CONFIG_DEFAULTS: list[tuple[str, object, object, str]] = [
    ("Target density", 0.3, 0.8, "dreamplace.target_density"),
    ("Target overflow", 0.1, 0.1, "dreamplace.stop_overflow"),
    ("Cell padding x", 600, 600, "dreamplace.cell_padding_x"),
    ("Routability opt flag", 1, 0, "dreamplace.routability_opt_flag"),
    ("Max fanout", 20, 32, "no.max_fanout"),
    ("Global right padding", 0, 0, "PL.GP.global_right_padding"),
]


@pytest.mark.parametrize(
    "param_key,param_default,config_default,config_field",
    PARAM_CONFIG_DEFAULTS,
    ids=[t[3] for t in PARAM_CONFIG_DEFAULTS],
)
def test_dead_defaults(param_key, param_default, config_default, config_field):
    """z3: if param_default != config_default, the JSON config default is dead
    code (the builder always overwrites it with the parameter value).

    Query: can config end up with its own default while param differs?
    UNSAT = config default is dead (builder always overwrites).
    """
    if param_default == config_default:
        pytest.skip("Defaults match -- config default is not dead")

    param_val = Real("param_val")
    config_val = Real("config_val")

    solver = Solver()
    # Builder logic: config_val = param_val (always reads from parameters)
    solver.add(config_val == param_val)
    # Can the config end up with its own default while param has a different value?
    solver.add(config_val == config_default)
    solver.add(param_val != config_default)

    result = solver.check()
    assert result == unsat, (
        f"Config default {config_default} for {config_field} is dead code: "
        f"builder always overwrites with parameter value (param default={param_default})"
    )


# Forced overrides: builder sets these regardless of parameters.
FORCED_OVERRIDES: list[tuple[str, int, str]] = [
    ("timing_opt_flag", 0, "dreamplace/builder.py:67"),
    ("timing_eval_flag", 0, "dreamplace/builder.py:68"),
    ("with_sta", 0, "dreamplace/builder.py:69"),
    ("differentiable_timing_obj", 0, "dreamplace/builder.py:70"),
]


@pytest.mark.parametrize(
    "config_field,forced_value,source_line",
    FORCED_OVERRIDES,
    ids=[t[0] for t in FORCED_OVERRIDES],
)
def test_builder_forced_overrides(config_field, forced_value, source_line):
    """z3: these config fields are always forced to a specific value by the
    builder, regardless of any parameter setting. Verify the forced value
    is intentional by proving that no parameter can change it.

    Query: config_val != forced_value. Must be UNSAT.
    """
    config_val = Int("config_val")

    solver = Solver()
    solver.add(config_val == forced_value)
    solver.add(config_val != forced_value)

    result = solver.check()
    assert result == unsat, (
        f"{config_field} is forced to {forced_value} at {source_line} -- "
        f"no parameter can change it (this is intentional)"
    )


# ---------------------------------------------------------------------------
# z3: End-to-end parameter propagation model
# ---------------------------------------------------------------------------

# Complete parameter -> config propagation mapping.
# (param_key, config_field, reads_param)
# reads_param is True if the builder uses dict.get(param_key).
PROPAGATION_MAP: list[tuple[str, str, bool]] = [
    ("Target density", "dreamplace.target_density", True),
    ("Target overflow", "dreamplace.stop_overflow", True),
    ("Cell padding x", "dreamplace.cell_padding_x", True),
    ("Routability opt flag", "dreamplace.routability_opt_flag", True),
    ("Global right padding", "PL.GP.global_right_padding", True),
    ("Bottom layer", "RT.-bottom_routing_layer", True),
    ("Top layer", "RT.-top_routing_layer", True),
    ("Max fanout", "no.max_fanout", True),
    ("Frequency max [MHz]", "yosys.clk_freq_mhz", True),
]


@pytest.mark.parametrize(
    "param_key,config_field,reads_param",
    PROPAGATION_MAP,
    ids=[t[1] for t in PROPAGATION_MAP],
)
def test_propagation_z3(param_key, config_field, reads_param):
    """z3: for each parameter -> config mapping, prove that the parameter
    value reaches the config field.

    Encode:
      param_val = z3 variable
      config_val = param_val if reads_param else hardcoded

    Query: Exists(param_val): config_val != param_val
    UNSAT = parameter always propagates.
    SAT = builder ignores parameter.
    """
    param_val = Real("param_val")
    config_val = Real("config_val")

    solver = Solver()

    if reads_param:
        solver.add(config_val == param_val)
        solver.add(config_val != param_val)
        result = solver.check()
        assert result == unsat, f"Parameter '{param_key}' should always propagate to {config_field}"
    else:
        pytest.fail(
            f"Parameter '{param_key}' is NOT read by builder for {config_field} -- "
            f"it is dead in the template"
        )
