from chipcompiler.analysis.qor.gate_catalog import (
    QOR_STEP_GATE_IDS,
    WORKSPACE_GATE_ALIASES,
    WORKSPACE_GATES,
    gate_metric_ids,
    step_gate_blocking,
    step_gate_policy,
)


def test_every_step_gate_has_a_workspace_alias_entry():
    step_gate_ids = {gate_id for ids in QOR_STEP_GATE_IDS.values() for gate_id in ids}

    assert set(WORKSPACE_GATE_ALIASES) == step_gate_ids
    assert WORKSPACE_GATE_ALIASES["qor.sta.setup_closed"] == (
        "GATE_SETUP_SLACK",
        "GATE_SETUP_NVP",
    )
    assert WORKSPACE_GATE_ALIASES["qor.rcx.corner_coverage"] == ()


def test_workspace_gate_order_is_the_feasibility_evaluation_order():
    assert [gate.id for gate in WORKSPACE_GATES] == [
        "GATE_DRC",
        "GATE_LVS",
        "GATE_ANTENNA",
        "GATE_SETUP_SLACK",
        "GATE_HOLD_SLACK",
        "GATE_SETUP_NVP",
        "GATE_HOLD_NVP",
        "GATE_MAX_TRANSITION",
        "GATE_MAX_CAPACITANCE",
        "GATE_MAX_FANOUT",
        "GATE_HARDEN_ARTIFACTS",
    ]


def test_drv_step_gate_maps_to_the_three_drv_workspace_gates():
    assert "qor.sta.drv_clean" in QOR_STEP_GATE_IDS["sta"]
    assert WORKSPACE_GATE_ALIASES["qor.sta.drv_clean"] == (
        "GATE_MAX_TRANSITION",
        "GATE_MAX_CAPACITANCE",
        "GATE_MAX_FANOUT",
    )


def test_gate_metric_ids_include_antenna_coverage_metrics():
    ids = gate_metric_ids()
    assert {"antenna_violation_count", "antenna_signal_net_count", "antenna_gate_pin_count"} <= ids


def test_step_gate_policy_comes_from_catalog():
    assert step_gate_blocking("qor.sta.drv_clean") is False
    assert step_gate_blocking("qor.antenna.clean") is True
    assert step_gate_policy("qor.sta.drv_clean", "failed") == "warn"
    assert step_gate_policy("qor.antenna.clean", "unavailable") == "warn"
    assert step_gate_policy("qor.antenna.clean", "failed") == "block"


def test_workspace_gate_blocking_matches_advisory_policy():
    by_id = {spec.id: spec for spec in WORKSPACE_GATES}
    for gate_id in ("GATE_MAX_TRANSITION", "GATE_MAX_CAPACITANCE", "GATE_MAX_FANOUT"):
        assert by_id[gate_id].blocks_tapeout is False
    for spec in WORKSPACE_GATES:
        expected = not spec.qor_gate_ids or any(
            step_gate_blocking(gid) for gid in spec.qor_gate_ids
        )
        assert spec.blocks_tapeout is expected
