import json

from chipcompiler.tools.replay_analysis_compact import compact_analysis
from chipcompiler.tools.replay_logic import collect_logical


def test_power_reuses_one_instance_table_and_preserves_all_display_values():
    views = [{"kind": "power", "items": [{"label": "u", "value": v}]} for v in [1, 2, 3, 6]]
    result = compact_analysis(views, [])
    assert result == {
        "schema": "ecos.replay.analysis.v2",
        "nets": [],
        "instances": ["u"],
        "unavailable": [],
        "views": [
            {"kind": "power", "items": [{"instance_ref": 0, "value": v}]} for v in [1, 2, 3, 6]
        ],
    }


def test_solver_locations_remain_distinct_from_native_wire_geometry():
    result = compact_analysis(
        [
            {
                "kind": "ir",
                "items": [
                    {
                        "label": "VDD:3",
                        "value": 0.02,
                        "bboxes": [[3, 4, 3, 4]],
                        "details": {"layer": "M1", "voltage_v": 0.98, "source": False},
                    }
                ],
            }
        ],
        [],
    )
    assert result["views"][0]["items"] == [
        {"label": "VDD:3", "value": 0.02, "bboxes": [[3, 4, 3, 4]], "details": {"layer": "M1"}}
    ]


def test_synthesis_publishes_only_the_logical_summary_used_by_replay(tmp_path):
    capture = tmp_path / "capture/logical"
    capture.mkdir(parents=True)
    (capture / "0.event").write_text(json.dumps({"elapsed_ns": 10, "phase": "mapped"}))
    (capture / "0.json").write_text(
        json.dumps({"modules": {"top": {"cells": {"u": {"type": "AND"}}}}})
    )
    collect_logical(tmp_path)
    files = [p for p in (tmp_path / "subflows").rglob("*") if p.is_file()]
    assert [p.name for p in files] == ["logic.json"]
    assert json.loads(files[0].read_text()) == {
        "cell_count": 1,
        "net_count": 0,
        "cell_types": {"AND": 1},
        "connections": [],
    }
