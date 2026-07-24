import chipcompiler.rtl2gds.builder as builder_module
from chipcompiler.rtl2gds import get_flow_builders


def test_discovery_includes_current_presets():
    assert {"rtl2gds", "rcx", "harden", "syn_sta"} <= set(get_flow_builders())


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
