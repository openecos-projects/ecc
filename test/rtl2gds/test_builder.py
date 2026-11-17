import pytest

import chipcompiler.rtl2gds.builder as builder_module
from chipcompiler.data import SkippableStepEnum, StateEnum, StepEnum
from chipcompiler.rtl2gds import get_flow_builders


def test_discovery_includes_current_presets():
    assert set(get_flow_builders()) == {
        "rtl2gds",
        "syn_sta",
        "synthesis_lec",
        "defview",
    }


def test_discovery_picks_up_new_flow_def(monkeypatch):
    def build_future_flow():
        return [("synthesis", "yosys", "Unstart")]

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


def test_default_flow_data_marks_checker_steps():
    from chipcompiler.data.workspace import build_dynamic_flow_data

    ledger = build_dynamic_flow_data({"start_step": "synthesis", "end_step": "harden"})
    categories = {step["name"]: step.get("category") for step in ledger.get("steps", [])}

    assert {name for name, category in categories.items() if category == "CHECKER"} == {
        "lvs",
        "drc",
        "antenna_check",
        "post_route_lec",
        "rcx",
        "sta",
        "power_analysis",
        "emir",
    }


def test_build_rtl2gds_flow_skip_removes_exactly_the_skipped_steps():
    flow = builder_module.build_rtl2gds_flow(skip=("diff_opt", SkippableStepEnum.TIMING_OPT.value))

    step_names = [step.value for step, _tool, _state in flow]
    unfiltered = [step.value for step, _tool, _state in builder_module.build_rtl2gds_flow()]
    assert step_names == [
        name for name in unfiltered if name not in {"diff_opt", "timing_optimization"}
    ]


def test_build_flow_range_slices_the_canonical_chain():
    flow = builder_module.build_flow_range("diff_sizing", "routing")

    assert [(step, tool) for step, tool, _state in flow] == [
        (StepEnum.DIFF_SIZING, "dreamplace"),
        (StepEnum.CTS, "ecc"),
        (StepEnum.LEGALIZATION, "dreamplace"),
        (SkippableStepEnum.TIMING_OPT, "sizer"),
        (StepEnum.ROUTING, "ecc"),
    ]


def test_build_flow_range_accepts_emir_after_power_analysis():
    assert builder_module.build_flow_range("power_analysis", "EMIR") == [
        (StepEnum.POWER_ANALYSIS, "ecc", StateEnum.Unstart),
        (StepEnum.EMIR, "ecc", StateEnum.Unstart),
    ]


@pytest.mark.parametrize("spelling", ["antennaCheck", "antenna_check", "antenna"])
def test_build_flow_range_accepts_antenna_after_drc(spelling):
    assert builder_module.build_flow_range("DRC", spelling) == [
        (StepEnum.DRC, "ecc", StateEnum.Unstart),
        (StepEnum.ANTENNA_CHECK, "ecc", StateEnum.Unstart),
    ]


def test_build_flow_range_normalizes_aliases_and_rejects_reverse_ranges():
    assert [step for step, _tool, _state in builder_module.build_flow_range("place", "CTS")] == [
        StepEnum.PLACEMENT,
        SkippableStepEnum.DIFF_OPT,
        StepEnum.DIFF_SIZING,
        StepEnum.CTS,
    ]
    assert [
        step for step, _tool, _state in builder_module.build_flow_range("sta", "power_analysis")
    ] == [
        StepEnum.STA,
        StepEnum.POWER_ANALYSIS,
    ]

    with pytest.raises(ValueError, match="reversed"):
        builder_module.build_flow_range("routing", "cts")
    with pytest.raises(ValueError, match="reversed"):
        builder_module.build_flow_range("power_analysis", "lvs")


def test_build_flow_range_exposes_split_floorplan_steps():
    flow = builder_module.build_flow_range("pre_floorplan", "post_floorplan")

    assert [(step, tool) for step, tool, _state in flow] == [
        (StepEnum.PRE_FLOORPLAN, "ecc"),
        (StepEnum.MACRO_PLACEMENT, "dreamplace"),
        (StepEnum.POST_FLOORPLAN, "ecc"),
    ]


@pytest.mark.parametrize("selector", ["floorplan", "floor-plan"])
def test_floorplan_selector_alias_targets_pre_floorplan(selector):
    assert builder_module.normalize_flow_step(selector) == StepEnum.PRE_FLOORPLAN.value


def test_a_chain_built_check_is_filtered_with_its_step():
    chain = builder_module.build_synthesis_lec_flow()

    assert builder_module.filter_flow_steps(chain, ("synthesis",)) == []


def test_build_flow_range_skip_excludes_steps_from_the_slice():
    flow = builder_module.build_flow_range(
        "synthesis", "post_floorplan", skip=(StepEnum.MACRO_PLACEMENT.value,)
    )

    assert [step for step, _tool, _state in flow] == [
        StepEnum.SYNTHESIS,
        StepEnum.PRE_FLOORPLAN,
        StepEnum.POST_FLOORPLAN,
    ]


def test_build_flow_range_rejects_skipped_step_as_boundary():
    with pytest.raises(ValueError, match="unknown flow step"):
        builder_module.build_flow_range("synthesis", "diff_opt", skip=("diff_opt",))


def test_resolve_lec_engine_absent_key_yields_the_code_default():
    from chipcompiler.data import DEFAULT_LEC_ENGINE, LECEngineEnum

    assert builder_module.resolve_lec_engine(None) is DEFAULT_LEC_ENGINE
    assert builder_module.resolve_lec_engine({}) is DEFAULT_LEC_ENGINE
    assert builder_module.resolve_lec_engine({"start_step": "synthesis"}) is DEFAULT_LEC_ENGINE
    assert DEFAULT_LEC_ENGINE is LECEngineEnum.KEPLER_FORMAL


def test_resolve_lec_engine_rejects_unknown_values_with_the_legal_set():
    with pytest.raises(ValueError, match="unknown LEC engine: 'bogus'.*kepler_formal"):
        builder_module.resolve_lec_engine({"lec_engine": "bogus"})


def test_build_rtl2gds_flow_rejects_an_unknown_engine():
    with pytest.raises(ValueError, match="unknown LEC engine"):
        builder_module.build_rtl2gds_flow(lec_engine="bogus")


def test_the_synthesis_lec_preset_builds_the_synthesis_check():
    assert builder_module.build_synthesis_lec_flow() == [
        (StepEnum.SYNTHESIS, "yosys", StateEnum.Unstart),
        ("lec@synthesis", "kepler_formal", StateEnum.Unstart),
    ]


def test_resolve_skip_steps_absent_key_yields_the_code_default():
    from chipcompiler.data import DEFAULT_SKIP_STEPS

    assert builder_module.resolve_skip_steps(None) == DEFAULT_SKIP_STEPS
    assert builder_module.resolve_skip_steps({}) == DEFAULT_SKIP_STEPS
    assert builder_module.resolve_skip_steps({"start_step": "synthesis"}) == DEFAULT_SKIP_STEPS
    assert (SkippableStepEnum.DIFF_OPT.value,) == DEFAULT_SKIP_STEPS


def test_resolve_skip_steps_explicit_empty_list_runs_everything():
    assert builder_module.resolve_skip_steps({"skip_steps": []}) == ()


@pytest.mark.parametrize(
    "raw,expected",
    [
        (["diff_opt"], ("diff_opt",)),
        (["DIFF-OPT", "diff_optimization"], ("diff_opt",)),
        (["postlec", "TimingOpt"], ("timing_optimization", "post_route_lec")),
        # lec is no chain step: existing files still list it, and it is dropped.
        (["lec", "LEC", "diff_opt"], ("diff_opt",)),
        # Any chain step may be named; plan_flow decides whether the rest runs.
        (["route", "Synth", "CTS"], ("synthesis", "cts", "routing")),
    ],
)
def test_resolve_skip_steps_normalizes_aliases_in_canonical_order(raw, expected):
    assert builder_module.resolve_skip_steps({"skip_steps": raw}) == expected
    # Normalization is idempotent: feeding the normalized tuple back is a no-op.
    assert builder_module.resolve_skip_steps({"skip_steps": list(expected)}) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "diff_opt",
        None,
        [1],
        ["bogus"],
        ["defview"],
    ],
)
def test_resolve_skip_steps_rejects_invalid_values(raw):
    with pytest.raises(ValueError, match="skip_steps"):
        builder_module.resolve_skip_steps({"skip_steps": raw})


def test_filter_flow_steps_removes_entries_without_reordering():
    steps = builder_module.build_flow_range("synthesis", "macro_placement")

    assert builder_module.filter_flow_steps(steps, ()) == steps
    assert builder_module.filter_flow_steps(steps, ("pre_floorplan",)) == [steps[0], steps[2]]


@pytest.mark.parametrize("declared_policy", [{}, {"skip_steps": ["cts"]}])
def test_all_creation_paths_build_the_same_ledger_for_one_policy(declared_policy):
    from chipcompiler.data.workspace import build_dynamic_flow_data

    policy = {"start_step": "synthesis", "end_step": "harden", **declared_policy}

    # Sidecar/direct flow_config path: the dynamic ledger.
    sidecar = [step["name"] for step in build_dynamic_flow_data(policy).get("steps", [])]

    # CLI ranged path: build_flow_range with the resolved policy.
    ranged = [
        step.value
        for step, _tool, _state in builder_module.build_flow_range(
            "synthesis", "harden", skip=builder_module.resolve_skip_steps(policy)
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
    assert ("diff_opt" in sidecar, "cts" in sidecar) == (bool(declared_policy), not declared_policy)


def test_policy_only_flow_config_never_yields_a_ledger():
    from chipcompiler.data.workspace import build_dynamic_flow_data

    assert build_dynamic_flow_data({"skip_steps": ["diff_opt"]}) == {}
    assert build_dynamic_flow_data({"skip_steps": []}) == {}


def test_unknown_flow_config_keys_never_become_steps_or_errors():
    from chipcompiler.data.workspace import build_dynamic_flow_data

    ledger = build_dynamic_flow_data(
        {
            "start_step": "synthesis",
            "end_step": "harden",
            "future_unknown_key": {"nested": [1, 2, 3]},
        }
    )

    names = [step["name"] for step in ledger.get("steps", [])]
    assert "synthesis" in names
    assert "future_unknown_key" not in names


def test_preset_shaped_flow_config_builds_the_preset_ledger():
    from chipcompiler.data.workspace import build_dynamic_flow_data
    from chipcompiler.data.workspace_config import flow_section_from_flow_config

    policy = {"preset": "synthesis_lec", "skip_steps": [], "insert_steps": ["lec@synthesis"]}

    ledger = build_dynamic_flow_data(policy)
    # The preset's own lec@synthesis is not inserted a second time.
    assert [step["name"] for step in ledger.get("steps", [])] == ["synthesis", "lec@synthesis"]

    # The persisted flow section keeps the preset and the normalized policy.
    section = flow_section_from_flow_config(policy)
    assert section == {
        "preset": "synthesis_lec",
        "skip_steps": [],
        "insert_steps": ["lec@synthesis"],
    }


def test_preset_ledger_may_start_after_a_skipped_first_step():
    from chipcompiler.data.workspace import build_dynamic_flow_data

    ledger = build_dynamic_flow_data({"preset": "rtl2gds", "skip_steps": ["synthesis"]})

    assert [step["name"] for step in ledger.get("steps", [])][:2] == [
        "pre_floorplan",
        "macro_placement",
    ]


def test_ledger_is_never_built_for_a_selection_missing_required_design_data():
    from chipcompiler.data.workspace import build_dynamic_flow_data

    with pytest.raises(ValueError, match="routing requires legal; enable timing_optimization"):
        build_dynamic_flow_data(
            {"preset": "rtl2gds", "skip_steps": ["legalization", "timing_optimization"]}
        )


def test_resolve_insert_steps_absent_key_inserts_nothing():
    assert builder_module.resolve_insert_steps({}) == ()


def test_resolve_insert_steps_normalizes_aliases_order_and_duplicates():
    insert = ["lec@route", "LEC@timing_opt", "lec@cts", "lec@CTS"]

    assert builder_module.resolve_insert_steps({"insert_steps": insert}) == (
        "lec@cts",
        "lec@timing_optimization",
        "lec@routing",
    )


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("lec@cts", "insert_steps must be a list, not str: 'lec@cts'"),
        ([1], "insert_steps entries must be strings, not 1"),
        (["cts"], "insert_steps entry 'cts' must be STEP@AFTER, for example lec@cts"),
        (["drc@CTS"], "insert_steps entry 'drc@CTS': only lec can be inserted"),
        (
            ["lec@filler"],
            "insert_steps entry 'lec@filler': lec can be inserted after synthesis, "
            "pre_floorplan, macro_placement, post_floorplan, preplace, placement, diff_opt, "
            "diff_sizing, cts, legalization, timing_optimization, routing",
        ),
    ],
)
def test_resolve_insert_steps_rejects_invalid_entries(raw, message):
    with pytest.raises(ValueError) as error:
        builder_module.resolve_insert_steps({"insert_steps": raw})

    assert str(error.value) == message


def test_an_inserted_lec_follows_its_step_with_the_lec_engine():
    flow = builder_module.build_rtl2gds_flow(skip=("cts",), insert=("lec@placement", "lec@cts"))

    names = [str(getattr(step, "value", step)) for step, _tool, _state in flow]
    place = names.index("placement")
    assert (names[place : place + 3], flow[place + 1][1:], "lec@cts" in names) == (
        ["placement", "lec@placement", "diff_opt"],
        ("kepler_formal", StateEnum.Unstart),
        False,
    )


def test_a_range_keeps_the_inserted_steps_of_its_steps_only():
    flow = builder_module.build_flow_range(
        "cts", "routing", insert=("lec@placement", "lec@cts", "lec@routing")
    )

    assert [str(getattr(step, "value", step)) for step, _tool, _state in flow] == [
        "cts",
        "lec@cts",
        "legalization",
        "timing_optimization",
        "routing",
        "lec@routing",
    ]


def test_a_ledger_holds_the_inserted_lec_after_its_step():
    from chipcompiler.data.workspace import build_dynamic_flow_data

    ledger = build_dynamic_flow_data({"preset": "rtl2gds", "insert_steps": ["lec@cts"]})
    steps = ledger.get("steps", [])
    names = [step["name"] for step in steps]
    inserted = steps[names.index("lec@cts")]

    assert (names[names.index("cts") + 1], inserted) == (
        "lec@cts",
        {
            "name": "lec@cts",
            "tool": "kepler_formal",
            "category": "PNR",
            "state": "Unstart",
            "directory": f"{names.index('lec@cts') + 1:02d}_lec@cts_kepler_formal",
            "runtime": "",
            "peak memory (mb)": 0,
            "info": {},
        },
    )
