import pytest

import chipcompiler.rtl2gds.builder as builder_module
from chipcompiler.data import SkippableStepEnum, StateEnum, StepEnum
from chipcompiler.rtl2gds import get_flow_builders


def test_discovery_includes_current_presets():
    assert set(get_flow_builders()) == {
        "rtl2gds",
        "syn_sta",
        "synthesis_lec",
    }


def test_discovery_picks_up_new_flow_def(monkeypatch):
    def build_future_flow():
        return [("Synthesis", "yosys", "Unstart")]

    monkeypatch.setattr(builder_module, "build_future_flow", build_future_flow, raising=False)
    assert get_flow_builders()["future"] is build_future_flow

    monkeypatch.undo()
    assert "future" not in get_flow_builders()


def test_discovery_resolves_callables_at_call_time(monkeypatch):
    def replacement():
        return []

    monkeypatch.setattr(builder_module, "build_rtl2gds_flow", replacement)
    assert get_flow_builders()["rtl2gds"] is replacement


def test_discovery_ignores_non_matching_names(monkeypatch):
    def build_flow():  # empty preset name
        return []

    def build_helper():  # missing _flow suffix
        return []

    def helper_build_x_flow():  # missing build_ prefix
        return []

    for fn in (build_flow, build_helper, helper_build_x_flow):
        monkeypatch.setattr(builder_module, fn.__name__, fn, raising=False)

    builders = get_flow_builders()
    assert "" not in builders
    for fn in (build_flow, build_helper, helper_build_x_flow):
        assert fn not in builders.values()


def test_build_rtl2gds_flow_is_the_complete_flow():
    flow = builder_module.build_rtl2gds_flow()

    assert flow == [
        (StepEnum.SYNTHESIS, "yosys", StateEnum.Unstart),
        (SkippableStepEnum.LEC, "yosys_lec", StateEnum.Unstart),
        (StepEnum.PRE_FLOORPLAN, "ecc", StateEnum.Unstart),
        (StepEnum.MACRO_PLACEMENT, "dreamplace", StateEnum.Unstart),
        (StepEnum.POST_FLOORPLAN, "ecc", StateEnum.Unstart),
        (StepEnum.PLACEMENT, "dreamplace", StateEnum.Unstart),
        (StepEnum.CTS, "ecc", StateEnum.Unstart),
        (StepEnum.LEGALIZATION, "dreamplace", StateEnum.Unstart),
        (SkippableStepEnum.TIMING_OPT, "sizer", StateEnum.Unstart),
        (StepEnum.ROUTING, "ecc", StateEnum.Unstart),
        (StepEnum.FILLER, "ecc", StateEnum.Unstart),
        (StepEnum.RCX, "ecc", StateEnum.Unstart),
        (StepEnum.STA, "ecc", StateEnum.Unstart),
        (StepEnum.LVS, "ecc", StateEnum.Unstart),
        (SkippableStepEnum.POST_ROUTE_LEC, "yosys_lec", StateEnum.Unstart),
        (StepEnum.DRC, "ecc", StateEnum.Unstart),
        (StepEnum.HARDEN, "ecc", StateEnum.Unstart),
    ]


def test_build_rtl2gds_flow_skip_removes_exactly_the_skipped_steps():
    flow = builder_module.build_rtl2gds_flow(skip=("lec", SkippableStepEnum.TIMING_OPT.value))

    step_names = [step.value for step, _tool, _state in flow]
    assert SkippableStepEnum.LEC.value not in step_names
    assert SkippableStepEnum.TIMING_OPT.value not in step_names
    unfiltered = [step.value for step, _tool, _state in builder_module.build_rtl2gds_flow()]
    assert step_names == [name for name in unfiltered if name not in {"lec", "Timing optimization"}]


def test_build_flow_range_slices_the_canonical_chain():
    flow = builder_module.build_flow_range("CTS", "route")

    assert [(step, tool) for step, tool, _state in flow] == [
        (StepEnum.CTS, "ecc"),
        (StepEnum.LEGALIZATION, "dreamplace"),
        (SkippableStepEnum.TIMING_OPT, "sizer"),
        (StepEnum.ROUTING, "ecc"),
    ]


def test_build_flow_range_normalizes_aliases_and_rejects_reverse_ranges():
    assert [step for step, _tool, _state in builder_module.build_flow_range("place", "cts")] == [
        StepEnum.PLACEMENT,
        StepEnum.CTS,
    ]

    with pytest.raises(ValueError, match="reversed"):
        builder_module.build_flow_range("route", "CTS")


def test_build_flow_range_exposes_split_floorplan_steps():
    flow = builder_module.build_flow_range("preFloorplan", "postFloorplan")

    assert [(step, tool) for step, tool, _state in flow] == [
        (StepEnum.PRE_FLOORPLAN, "ecc"),
        (StepEnum.MACRO_PLACEMENT, "dreamplace"),
        (StepEnum.POST_FLOORPLAN, "ecc"),
    ]


def test_build_flow_range_skip_excludes_steps_from_the_slice():
    flow = builder_module.build_flow_range("Synthesis", "preFloorplan", skip=("lec",))

    assert [step for step, _tool, _state in flow] == [
        StepEnum.SYNTHESIS,
        StepEnum.PRE_FLOORPLAN,
    ]


def test_build_flow_range_rejects_skipped_step_as_boundary():
    with pytest.raises(ValueError, match="unknown flow step"):
        builder_module.build_flow_range("Synthesis", "lec", skip=("lec",))


def test_resolve_skip_steps_absent_key_yields_the_code_default():
    from chipcompiler.data import DEFAULT_SKIP_STEPS

    assert builder_module.resolve_skip_steps(None) == DEFAULT_SKIP_STEPS
    assert builder_module.resolve_skip_steps({}) == DEFAULT_SKIP_STEPS
    assert builder_module.resolve_skip_steps({"start_step": "Synthesis"}) == DEFAULT_SKIP_STEPS
    assert (SkippableStepEnum.LEC.value,) == DEFAULT_SKIP_STEPS


def test_resolve_skip_steps_explicit_empty_list_runs_everything():
    assert builder_module.resolve_skip_steps({"skip_steps": []}) == ()


@pytest.mark.parametrize(
    "raw,expected",
    [
        (["lec"], ("lec",)),
        (["LEC"], ("lec",)),
        (["lec", "lec"], ("lec",)),
        (["postRouteLec", "lec"], ("lec", "postRouteLec")),
        (["TimingOpt", "lec", "postlec"], ("lec", "Timing optimization", "postRouteLec")),
    ],
)
def test_resolve_skip_steps_normalizes_aliases_in_canonical_order(raw, expected):
    assert builder_module.resolve_skip_steps({"skip_steps": raw}) == expected
    # Normalization is idempotent: feeding the normalized tuple back is a no-op.
    assert builder_module.resolve_skip_steps({"skip_steps": list(expected)}) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "lec",
        None,
        [1],
        ["lec", "route"],
        ["bogus"],
    ],
)
def test_resolve_skip_steps_rejects_invalid_values(raw):
    with pytest.raises(ValueError, match="skip_steps"):
        builder_module.resolve_skip_steps({"skip_steps": raw})


def test_filter_flow_steps_removes_entries_without_reordering():
    steps = builder_module.build_synthesis_lec_flow()

    assert builder_module.filter_flow_steps(steps, ()) == steps
    assert builder_module.filter_flow_steps(steps, ("lec",)) == steps[:1]


def test_all_creation_paths_build_the_same_ledger_for_one_policy():
    from chipcompiler.data.workspace import build_dynamic_flow_data

    policy = {"start_step": "Synthesis", "end_step": "Harden", "skip_steps": ["lec"]}

    # Sidecar/direct flow_config path: the dynamic ledger.
    sidecar = [step["name"] for step in build_dynamic_flow_data(policy)["steps"]]

    # CLI ranged path: build_flow_range with the resolved policy.
    ranged = [
        step.value
        for step, _tool, _state in builder_module.build_flow_range(
            "Synthesis", "Harden", skip=builder_module.resolve_skip_steps(policy)
        )
    ]

    # CLI preset path: the no-arg builder output filtered post-call.
    preset = [
        step.value
        for step, _tool, _state in builder_module.filter_flow_steps(
            builder_module.build_rtl2gds_flow(),
            builder_module.resolve_skip_steps(policy),
        )
    ]

    assert sidecar == ranged == preset
    assert "lec" not in sidecar


def test_policy_only_flow_config_never_yields_a_ledger():
    from chipcompiler.data.workspace import build_dynamic_flow_data

    assert build_dynamic_flow_data({"skip_steps": ["lec"]}) == {}
    assert build_dynamic_flow_data({"skip_steps": []}) == {}


def test_unknown_flow_config_keys_never_become_steps_or_errors():
    from chipcompiler.data.workspace import build_dynamic_flow_data

    ledger = build_dynamic_flow_data(
        {
            "start_step": "Synthesis",
            "end_step": "Harden",
            "future_unknown_key": {"nested": [1, 2, 3]},
        }
    )

    names = [step["name"] for step in ledger["steps"]]
    assert "Synthesis" in names
    assert "future_unknown_key" not in names


def test_preset_shaped_flow_config_builds_the_preset_ledger():
    from chipcompiler.data.workspace import build_dynamic_flow_data
    from chipcompiler.data.workspace_config import flow_section_from_flow_config

    policy = {"preset": "synthesis_lec", "skip_steps": []}

    ledger = build_dynamic_flow_data(policy)
    assert [step["name"] for step in ledger["steps"]] == ["Synthesis", "lec"]

    # The persisted flow section keeps the preset and the normalized policy.
    section = flow_section_from_flow_config(policy)
    assert section == {"preset": "synthesis_lec", "skip_steps": []}

    # The default policy conflicts with this preset's LEC endpoint: the
    # skipped boundary is a deterministic unknown-step error (the data-level
    # mirror of the creation-time preset conflict).
    with pytest.raises(ValueError, match="unknown flow step"):
        build_dynamic_flow_data({"preset": "synthesis_lec"})
