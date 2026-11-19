"""Parameter invalidation follows the config fields each tool declares it reads."""

from types import SimpleNamespace

from chipcompiler.data.step_config_reads import ConfigRead
from chipcompiler.data.workspace.parameters import workspace_param_step
from chipcompiler.params import lookup_schema
from chipcompiler.rtl2gds.builder import build_rtl2gds_flow


def test_a_read_overlaps_writes_inside_or_around_its_field():
    read = ConfigRead("routing", ("RT", "-top_routing_layer"))

    assert [
        read.overlaps(key, path)
        for key, path in (
            ("routing", ("RT", "-top_routing_layer")),
            ("routing", ("RT",)),
            ("routing", ("RT", "-thread_number")),
            ("sta", ("RT", "-top_routing_layer")),
        )
    ] == [True, True, False, False]


def test_a_parameter_invalidates_from_the_first_step_reading_its_field():
    steps = [{"name": str(step), "tool": str(tool)} for step, tool, _ in build_rtl2gds_flow()]
    workspace = SimpleNamespace(flow=SimpleNamespace(steps=lambda: steps))
    params = (
        "route.RT.-thread_number",
        "route.top_layer",
        "sta.liberty",
        "sta.max_parallel_corners",
        "timing_opt.hold_margin",
    )

    assert {param: workspace_param_step(lookup_schema(param), workspace) for param in params} == {
        # Only the router reads its thread count.
        "route.RT.-thread_number": "routing",
        # DreamPlace's GPU global router reads the layer bounds first.
        "route.top_layer": "macro_placement",
        # Sizer reads the MIN-corner Liberty files at preplace.
        "sta.liberty": "preplace",
        # Timing-driven placement hands the whole STA config to its timer.
        "sta.max_parallel_corners": "placement",
        "timing_opt.hold_margin": "preplace",
    }
