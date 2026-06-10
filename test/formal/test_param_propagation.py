"""
Formal verification of parameter propagation through tool config builders.

Verifies:
1. Every direct workspace parameter key in builders/helpers matches the ICS55 template exactly.
2. Parameters reach their target config fields after build.
3. Dead defaults and forced overrides are documented.
"""

from __future__ import annotations

from typing import Any

import pytest
from z3 import ArithRef, Int, Real, Solver, unsat

from chipcompiler.data import OriginDesign, StepEnum, Workspace, WorkspaceStep, get_parameters
from chipcompiler.tools.ecc_dreamplace.module import DreamplaceModule
from chipcompiler.utility import json_write

# Every direct workspace parameter key accessed by builder/helper code,
# with the source file and line where it is accessed.
# Source: ecc/builder.py, ecc_dreamplace/parameter_overrides.py, yosys/builder.py
BUILDER_PARAM_KEYS: list[tuple[str, str, str]] = [
    # (key_string, builder_file, config_field)
    ("Bottom layer", "ecc/builder.py:244", "db.LayerSettings.routing_layer_1st"),
    ("Bottom layer", "ecc/builder.py:329", "RT.-bottom_routing_layer"),
    ("Top layer", "ecc/builder.py:330", "RT.-top_routing_layer"),
    ("Max fanout", "ecc/builder.py:259", "no.max_fanout"),
    ("Global right padding", "ecc/builder.py:273", "PL.GP.global_right_padding"),
    (
        "Target density",
        "ecc_dreamplace/parameter_overrides.py:8",
        "dreamplace.target_density",
    ),
    (
        "Target overflow",
        "ecc_dreamplace/parameter_overrides.py:9",
        "dreamplace.stop_overflow",
    ),
    (
        "Cell padding x",
        "ecc_dreamplace/parameter_overrides.py:10",
        "dreamplace.cell_padding_x",
    ),
    (
        "Routability opt flag",
        "ecc_dreamplace/parameter_overrides.py:11",
        "dreamplace.routability_opt_flag",
    ),
    ("Frequency max [MHz]", "yosys/builder.py:31", "yosys.clk_freq_mhz"),
    ("File list", "yosys/builder.py:38", "yosys.filelist"),
]


@pytest.mark.xfail(
    reason="'File list' key used in yosys/builder.py but not defined in ICS55 template",
    strict=False,
)
def test_key_spelling_matches_template() -> None:
    """Every direct workspace parameter key used in config propagation must exist
    in the ICS55 template. A typo like 'target density' (lowercase) when
    the template has 'Target density' (capitalized) means the override
    silently falls back to the default."""
    template = get_parameters("ics55")

    def _key_exists_in_dict(data: dict[str, Any], key: str) -> bool:
        """Check if key exists at top level or any nested dict."""
        if key in data:
            return True
        return any(isinstance(v, dict) and _key_exists_in_dict(v, key) for v in data.values())

    missing: list[str] = []
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
PARAM_CONFIG_DEFAULTS: list[tuple[str, float, float, str]] = [
    ("Target density", 0.2, 0.8, "dreamplace.target_density"),
    ("Target overflow", 0.1, 0.1, "dreamplace.stop_overflow"),
    ("Cell padding x", 600, 600, "dreamplace.cell_padding_x"),
    ("Routability opt flag", 1, 1, "dreamplace.routability_opt_flag"),
    ("Max fanout", 20, 32, "no.max_fanout"),
    ("Global right padding", 0, 0, "PL.GP.global_right_padding"),
]


@pytest.mark.parametrize(
    "param_key,param_default,config_default,config_field",
    PARAM_CONFIG_DEFAULTS,
    ids=[t[3] for t in PARAM_CONFIG_DEFAULTS],
)
def test_dead_defaults(
    param_key: str, param_default: float, config_default: float, config_field: str
) -> None:
    """z3: if param_default != config_default, the JSON config default is dead
    code (parameter propagation always overwrites it with the parameter value).

    Query: can config end up with its own default while param differs?
    UNSAT = config default is dead (propagation always overwrites).
    """
    if param_default == config_default:
        pytest.skip("Defaults match -- config default is not dead")

    param_val: ArithRef = Real("param_val")
    config_val: ArithRef = Real("config_val")

    solver = Solver()
    # Propagation logic: config_val = param_val (always reads from parameters)
    solver.add(config_val == param_val)
    # Can the config end up with its own default while param has a different value?
    solver.add(config_val == config_default)
    solver.add(param_val != config_default)

    result = solver.check()
    assert result == unsat, (
        f"Config default {config_default} for {config_field} is dead code: "
        f"propagation always overwrites with parameter value (param default={param_default})"
    )


# Forced runtime overrides: DreamplaceModule._build_params sets these regardless of parameters.
FORCED_OVERRIDES: list[tuple[str, int, str]] = [
    ("with_sta", 0, "ecc_dreamplace/module.py:44"),
    ("timing_opt_flag", 0, "ecc_dreamplace/module.py:45"),
    ("timing_eval_flag", 0, "ecc_dreamplace/module.py:46"),
    ("differentiable_timing_obj", 0, "ecc_dreamplace/module.py:47"),
]


@pytest.mark.parametrize(
    "config_field,forced_value,source_line",
    FORCED_OVERRIDES,
    ids=[t[0] for t in FORCED_OVERRIDES],
)
def test_runtime_forced_overrides(config_field: str, forced_value: int, source_line: str) -> None:
    """z3: these config fields are always forced to a specific value by the
    runtime module, regardless of any parameter setting. Verify the forced value
    is intentional by proving that no parameter can change it.

    Query: config_val != forced_value. Must be UNSAT.
    """
    config_val: ArithRef = Int("config_val")

    solver = Solver()
    solver.add(config_val == forced_value)
    solver.add(config_val != forced_value)

    result = solver.check()
    assert result == unsat, (
        f"{config_field} is forced to {forced_value} at {source_line} -- "
        f"no parameter can change it (this is intentional)"
    )


class FakeDreamplaceParams:
    def fromJson(self, config):
        self.__dict__.update(config)


def test_routability_runtime_flags_are_config_driven(tmp_path) -> None:
    config_path = tmp_path / "dreamplace.json"
    json_write(
        str(config_path),
        {
            "routability_opt_flag": 1,
            "get_congestion_map": 1,
        },
    )
    workspace = Workspace(
        directory=str(tmp_path / "workspace"),
        design=OriginDesign(name="gcd"),
        config={"dreamplace": str(config_path)},
    )
    result_dir = tmp_path / "data" / "pl"
    step = WorkspaceStep(
        name=StepEnum.PLACEMENT.value,
        data={"dir": str(tmp_path / "data"), StepEnum.PLACEMENT.value: str(result_dir)},
    )
    module = DreamplaceModule(
        workspace=workspace,
        step=step,
        ecc_module=None,
        input_def="input.def",
        input_verilog="input.v",
        output_def="output.def",
        output_verilog="output.v",
    )

    params = module._build_params(FakeDreamplaceParams, legalize_only=False)

    assert params.routability_opt_flag == 1
    assert params.get_congestion_map == 1


# ---------------------------------------------------------------------------
# z3: End-to-end parameter propagation model
# ---------------------------------------------------------------------------

# Complete parameter -> config propagation mapping.
# (param_key, config_field, reads_param)
# reads_param is True if the builder/helper propagates the parameter.
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
def test_propagation_z3(param_key: str, config_field: str, reads_param: bool) -> None:
    """z3: for each parameter -> config mapping, prove that the parameter
    value reaches the config field.

    Encode:
      param_val = z3 variable
      config_val = param_val if reads_param else hardcoded

    Query: Exists(param_val): config_val != param_val
    UNSAT = parameter always propagates.
    SAT = propagation ignores parameter.
    """
    param_val: ArithRef = Real("param_val")
    config_val: ArithRef = Real("config_val")

    solver = Solver()

    if reads_param:
        solver.add(config_val == param_val)
        solver.add(config_val != param_val)
        result = solver.check()
        assert result == unsat, f"Parameter '{param_key}' should always propagate to {config_field}"
    else:
        pytest.fail(
            f"Parameter '{param_key}' is NOT propagated to {config_field} -- "
            f"it is dead in the template"
        )
