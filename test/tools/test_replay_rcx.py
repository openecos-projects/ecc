from chipcompiler.tools.replay_rcx import network_views


def test_rc_graph_preserves_units_branching_ground_and_cross_net_coupling(tmp_path):
    design = tmp_path / "input.def"
    design.write_text("UNITS DISTANCE MICRONS 2000 ;")
    spef = tmp_path / "typ.spef"
    spef.write_text("""*DELIMITER :
*C_UNIT 1 PF
*R_UNIT 1 KOHM
*NAME_MAP
*1 net_a
*2 net_b
*10 inst
*D_NET *1 0.006
*CONN
*I *10:Q O *C 1.25 2.5
*N *1:1 *C 3 4
*N *1:2 *C 5 4
*CAP
1 *1:1 0.001
2 *1:1 *2:1 0.005
*RES
1 *10:Q *1:1 0.02
2 *1:1 *1:2 0.03
3 *1:2 missing 0.04
*END
*D_NET *2 0.005
*CONN
*N *2:1 *C 6 4
*CAP
1 *2:1 *1:1 0.005
*END
""")
    view = network_views(spef, design)[0]
    assert view["items"][0]["positions"] == [[2500, 5000], [6000, 8000], [10000, 8000]]
    assert view["items"][0]["segments"] == [
        [[2500, 5000], [6000, 8000]],
        [[6000, 8000], [10000, 8000]],
    ]
    details = view["items"][0]["details"]
    assert details["resistors_ohm"] == [
        {"nodes": ["*10:Q", "*1:1"], "value": 20.0},
        {"nodes": ["*1:1", "*1:2"], "value": 30.0},
        {"nodes": ["*1:2", "missing"], "value": 40.0},
    ]
    assert details["capacitors_ff"] == [
        {"nodes": ["*1:1"], "value": 1.0},
        {"nodes": ["*1:1", "*2:1"], "value": 5.0},
    ]
    assert details["ground_capacitance_ff"] == 1.0
    assert view["summary"]["unlocated_resistors"] == 1
    assert view["items"][1]["details"]["capacitors_ff"] == [
        {"nodes": ["*2:1", "*1:1"], "value": 5.0}
    ]
