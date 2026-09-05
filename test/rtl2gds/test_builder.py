import chipcompiler.rtl2gds.builder as builder_module
from chipcompiler.data import StateEnum, StepEnum
from chipcompiler.rtl2gds import get_flow_builders


def test_discovery_includes_current_presets():
    assert {
        "rtl2gds",
        "rcx",
        "harden",
        "syn_sta",
        "synthesis_lec",
    } <= set(get_flow_builders())


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


def test_build_rtl2gds_flow_includes_lvs_after_drc():
    flow = builder_module.build_rtl2gds_flow()

    assert flow == [
        (StepEnum.SYNTHESIS, "yosys", StateEnum.Unstart),
        (StepEnum.LEC, "yosys_lec", StateEnum.Unstart),
        (StepEnum.FLOORPLAN, "ecc", StateEnum.Unstart),
        (StepEnum.PLACEMENT, "dreamplace", StateEnum.Unstart),
        (StepEnum.CTS, "ecc", StateEnum.Unstart),
        (StepEnum.LEGALIZATION, "dreamplace", StateEnum.Unstart),
        (StepEnum.TIMING_OPT, "sizer", StateEnum.Unstart),
        (StepEnum.ROUTING, "ecc", StateEnum.Unstart),
        (StepEnum.DRC, "ecc", StateEnum.Unstart),
        (StepEnum.LVS, "ecc", StateEnum.Unstart),
        (StepEnum.FILLER, "ecc", StateEnum.Unstart),
        (StepEnum.POST_ROUTE_LEC, "yosys_lec", StateEnum.Unstart),
    ]
