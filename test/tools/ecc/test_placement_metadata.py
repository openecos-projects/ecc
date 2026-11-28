"""Metadata-only loading must never enter ECC's timing/RC evaluation APIs."""

from types import SimpleNamespace

import pytest

from chipcompiler.tools.ecc.module import ECCToolsModule


def test_placement_metadata_loads_inputs_without_native_sta(tmp_path):
    calls = []

    def record(name):
        def invoke(*args, **kwargs):
            calls.append((name, args, kwargs))
            return True

        return invoke

    module = ECCToolsModule.__new__(ECCToolsModule)
    module._place_timing_active = False
    module._place_timing_inputs = None
    module.ecc = SimpleNamespace(
        lib_init=record("lib"),
        sdc_init=record("sdc"),
        load_placement_timing_metadata=record("metadata"),
        destroy_sta=record("destroy"),
        is_placement_metadata_ready=lambda: True,
        placement_metadata_reason=lambda: "",
    )
    inputs = {"lib_paths": [tmp_path / "tt.lib"], "sdc_path": tmp_path / "design.sdc"}
    summary = module.prepare_placement_metadata(inputs)

    assert calls == [
        ("lib", (), {"lib_paths": [str(tmp_path / "tt.lib")]}),
        ("sdc", (str(tmp_path / "design.sdc"),), {}),
        (
            "metadata",
            (),
            {
                "config": "",
                "config_dict": {
                    "-output_timing_reports": "0",
                    "-output_timing_features": "0",
                    "-timing_path_limit": "20",
                    "-max_paths": "20",
                    "-thread_number": "2",
                },
            },
        ),
    ]
    assert summary == {
        "status": "ok",
        "mode": "placement_metadata_only",
        "timing_evaluator": "dreamplace_timing_propagation",
        "ecc_sta_run": False,
        "placement_metadata_supported": True,
        "parasitics_initialization": "python_placement_rc_pending",
        "lib_count": 1,
        "sdc_path": str(tmp_path / "design.sdc"),
    }
    assert module._place_timing_inputs == inputs
    module.destroy_place_timing()
    assert calls[-1] == ("destroy", (), {})


def test_placement_metadata_falls_back_when_sdc_exceeds_the_model(tmp_path):
    calls = []

    def record(name):
        def invoke(*args, **kwargs):
            calls.append((name, args, kwargs))
            return True

        return invoke

    module = ECCToolsModule.__new__(ECCToolsModule)
    module._place_timing_active = False
    module._place_timing_inputs = None
    module.ecc = SimpleNamespace(
        lib_init=record("lib"),
        sdc_init=record("sdc"),
        load_placement_timing_metadata=record("metadata"),
        destroy_sta=record("destroy"),
        is_placement_metadata_ready=lambda: False,
        placement_metadata_reason=lambda: "requires exactly one clock, found 3",
    )
    module.prepare_place_timing = lambda inputs: {"status": "ok", "mode": "native_timing"}
    inputs = {"lib_paths": [tmp_path / "tt.lib"], "sdc_path": tmp_path / "design.sdc"}

    summary = module.prepare_placement_metadata(inputs)

    assert summary == {
        "status": "ok",
        "mode": "native_timing",
        "placement_metadata_supported": False,
        "placement_metadata_reason": "requires exactly one clock, found 3",
    }
    # The rejected metadata session must be torn down before the full export.
    assert calls[-1] == ("destroy", (), {})


@pytest.mark.parametrize("field", ["spef", "spef_path", "rcx_config"])
def test_placement_metadata_rejects_routing_parasitics_before_loading(field):
    module = ECCToolsModule.__new__(ECCToolsModule)
    with pytest.raises(ValueError, match="placement RC"):
        module.prepare_placement_metadata({field: "routing_parasitics"})
