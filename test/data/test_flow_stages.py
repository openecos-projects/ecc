"""Stages group the enabled steps the way the engine runs them; needs name each step's producers."""

import pytest

from chipcompiler.data import DEFAULT_SKIP_STEPS
from chipcompiler.data.flow_needs import plan_needs
from chipcompiler.data.flow_plan import plan_flow, preset_chain
from chipcompiler.data.flow_stages import StepStage, plan_stages
from chipcompiler.data.workspace.flow_data import build_dynamic_flow_data
from chipcompiler.data.workspace.flow_policy import analysis_wave_end
from chipcompiler.rtl2gds import resolve_skip_steps

_RTL2GDS = preset_chain("rtl2gds")


def _plan(skip=DEFAULT_SKIP_STEPS):
    return plan_flow(_RTL2GDS, skip_steps=skip).steps


def _by_name(steps, values):
    return {step.name: value for step, value in zip(steps, values, strict=True)}


def test_the_post_filler_checkers_form_parallel_stages():
    steps = _plan()
    stages = _by_name(steps, plan_stages(steps))

    assert stages["filler"] == StepStage(12, "", ())
    assert stages["lvs"] == StepStage(13, "a", ("drc", "antennaCheck", "postRouteLec", "RCX"))
    assert stages["RCX"] == StepStage(13, "e", ("lvs", "drc", "antennaCheck", "postRouteLec"))
    assert stages["sta"] == StepStage(14, "a", ("powerAnalysis",))
    assert stages["powerAnalysis"] == StepStage(14, "b", ("sta",))
    assert stages["emir"] == StepStage(15, "", ())
    assert stages["Harden"] == StepStage(16, "", ())


def test_a_disabled_step_has_no_stage_and_the_stages_after_it_renumber():
    steps = _plan(skip=[*DEFAULT_SKIP_STEPS, "drc"])
    stages = _by_name(steps, plan_stages(steps))

    assert stages["drc"] == StepStage(None, "", ())
    assert stages["drc"].label == ""
    assert stages["lvs"] == StepStage(13, "a", ("antennaCheck", "postRouteLec", "RCX"))
    assert stages["Harden"] == StepStage(16, "", ())


def _waves(names, stages):
    """Names grouped by stage number, in order; a disabled step (no stage) is left out."""
    groups: dict[int, list[str]] = {}
    for name, stage in zip(names, stages, strict=True):
        if stage.stage is not None:
            groups.setdefault(stage.stage, []).append(name)
    return list(groups.values())


def _ledger_waves(flow_config):
    """The analysis waves the engine finds in the ledger a fresh run builds."""
    records = build_dynamic_flow_data(flow_config).get("steps", [])
    waves, start = [], 0
    while start < len(records):
        end = analysis_wave_end(records, start)
        waves.append([record["name"] for record in records[start:end]])
        start = end
    return waves


_CHAIN_NAMES = [name for name, _tool in _RTL2GDS]
_SYNTHESIS_TO_FILLER = _CHAIN_NAMES[
    _CHAIN_NAMES.index("Synthesis") : _CHAIN_NAMES.index("filler") + 1
]


@pytest.mark.parametrize(
    "flow_config",
    [
        pytest.param({"preset": "rtl2gds"}, id="default-skip"),
        pytest.param({"preset": "rtl2gds", "skip_steps": []}, id="nothing-skipped"),
        pytest.param(
            {"preset": "rtl2gds", "skip_steps": [*DEFAULT_SKIP_STEPS, "drc"]}, id="drc-disabled"
        ),
        pytest.param(
            {"preset": "rtl2gds", "skip_steps": _SYNTHESIS_TO_FILLER}, id="synthesis-to-filler"
        ),
        pytest.param(
            {"start_step": "Synthesis", "end_step": "postRouteLec"}, id="range-to-postRouteLec"
        ),
        pytest.param({"start_step": "route", "end_step": "RCX", "skip_steps": []}, id="route-RCX"),
        pytest.param({"preset": "syn_sta"}, id="syn_sta"),
        pytest.param({"preset": "synthesis_lec", "skip_steps": []}, id="synthesis_lec"),
    ],
)
def test_the_stages_are_the_analysis_waves_of_the_ledger_a_fresh_run_builds(flow_config):
    preset = flow_config.get("preset", "rtl2gds")
    plan = plan_flow(
        preset_chain(preset),
        skip_steps=resolve_skip_steps(flow_config),
        start=flow_config.get("start_step"),
        end=flow_config.get("end_step"),
    )
    names = [step.name for step in plan.steps]

    assert _waves(names, plan_stages(plan.steps)) == _ledger_waves(flow_config)


def test_after_keeps_a_producer_unless_another_producer_relays_all_it_gives():
    steps = _plan()
    needs = _by_name(steps, plan_needs(steps))

    assert {
        name: needs[name].after
        for name in (
            "route",
            "lvs",
            "postRouteLec",
            "RCX",
            "sta",
            "powerAnalysis",
            "emir",
            "Harden",
        )
    } == {
        "route": ("Timing optimization", "CTS"),
        "lvs": ("filler",),
        "postRouteLec": ("filler", "Synthesis"),
        "RCX": ("filler",),
        # RCX relays filled from filler, but nothing else relays CTS's clock tree.
        "sta": ("RCX", "CTS"),
        "powerAnalysis": ("RCX", "CTS"),
        "emir": ("powerAnalysis", "postFloorplan"),
        "Harden": ("RCX", "CTS"),
    }


def test_a_capability_nothing_provides_has_no_producer():
    steps = _plan()
    needs = _by_name(steps, plan_needs(steps))

    assert needs["Synthesis"].producers == (("rtl", None),)
    assert needs["Synthesis"].after == ()


def test_producers_are_the_enabled_steps_only():
    steps = _plan(skip=[*DEFAULT_SKIP_STEPS, "CTS"])
    needs = _by_name(steps, plan_needs(steps))

    assert dict(needs["route"].producers)["clock_tree"] is None
    assert needs["route"].after == ("Timing optimization",)
