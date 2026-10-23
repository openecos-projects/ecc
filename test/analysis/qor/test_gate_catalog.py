from chipcompiler.analysis.qor.gate_catalog import (
    QOR_STEP_GATE_IDS,
    WORKSPACE_GATE_ALIASES,
    WORKSPACE_GATES,
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
        "GATE_SETUP_SLACK",
        "GATE_HOLD_SLACK",
        "GATE_SETUP_NVP",
        "GATE_HOLD_NVP",
        "GATE_HARDEN_ARTIFACTS",
    ]
