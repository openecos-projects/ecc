from chipcompiler.data.foundation.extractor import _attribution_profile_inputs


def test_r3_profile_requires_placement_congestion_or_pin_access_seed():
    profiles = _attribution_profile_inputs(
        drc_wire_available=False,
        d2_available=False,
        c1_available=False,
        seed_ids=[],
        short_seed_ids=[],
        r3_seed_ids=["42"],
    )

    assert profiles["R3"] == {
        "availability": "available",
        "rule_version": "congestion_or_pin_access.v1",
        "seed_ids": ["42"],
    }
