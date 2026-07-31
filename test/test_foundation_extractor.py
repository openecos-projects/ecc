# ruff: noqa: E501
from __future__ import annotations

import csv
import gzip
import json
import logging
from collections.abc import Iterable
from pathlib import Path

import pytest

import chipcompiler.data.foundation.extractor as extractor_module
import chipcompiler.data.foundation.table_contract as table_contract_module
from chipcompiler.data.foundation import FoundationExtractor
from chipcompiler.data.foundation.grid.canonical_grid import build_patch_grid
from chipcompiler.data.foundation.parsers.def_parser import parse_def
from chipcompiler.data.foundation.parsers.route_native_demand_capacity import (
    parse_route_native_demand_capacity_artifacts,
)
from chipcompiler.data.foundation.table_contract import TABLE_SPECS, write_tables
from chipcompiler.data.foundation.writers import write_parquet


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_csv(path: Path, rows: list[list[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerows(rows)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_sample_gcell_info(stage_dir: Path) -> None:
    _write_text(
        stage_dir / "data" / "rt" / "rt_temp_directory" / "early_router" / "gcell.info",
        "\n".join(
            [
                "0,0,0,0,120,80",
                "0,1,0,80,120,200",
                "1,0,120,0,200,80",
                "1,1,120,80,200,200",
            ]
        )
        + "\n",
    )


def _write_sample_egr_demand_capacity(stage_dir: Path) -> None:
    early_router = stage_dir / "data" / "rt" / "rt_temp_directory" / "early_router"
    _write_text(
        early_router / "route.guide",
        "\n".join(
            [
                "guide net_name",
                "pin grid_x grid_y real_x real_y layer energy name",
                "wire grid1_x grid1_y grid2_x grid2_y real1_x real1_y real2_x real2_y layer",
                "via grid_x grid_y real_x real_y layer1 layer2",
                "guide n1",
                "wire 0 0 1 0 0 0 120 0 MET2",
                "wire 0 0 0 1 0 0 0 80 MET3",
            ]
        )
        + "\n",
    )
    _write_csv(early_router / "net_map_MET2.csv", [[8, 1], [3, 4]])
    _write_csv(early_router / "supply_map_MET2.csv", [[5, 5], [2, 1]])
    _write_csv(early_router / "net_map_MET3.csv", [[0, 9], [6, 1]])
    _write_csv(early_router / "supply_map_MET3.csv", [[1, 2], [3, 4]])


def _regular_test_patches(rows: int, cols: int, *, step: float = 10.0) -> list[dict]:
    return [
        {
            "row": row,
            "col": col,
            "bbox": {
                "llx": col * step,
                "lly": row * step,
                "urx": (col + 1) * step,
                "ury": (row + 1) * step,
            },
        }
        for row in range(rows)
        for col in range(cols)
    ]


def test_patch_point_density_directly_indexes_regular_grid(monkeypatch: pytest.MonkeyPatch):
    rows = 10
    cols = 10
    patches = _regular_test_patches(rows, cols)
    calls = {"count": 0}
    original = extractor_module._point_in_bbox

    def counted_point_in_bbox(*args, **kwargs):
        calls["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(extractor_module, "_point_in_bbox", counted_point_in_bbox)

    matrix = extractor_module._patch_point_density(
        patches,
        rows,
        cols,
        [{"x": 25.0, "y": 35.0}, {"x": 25.0, "y": 35.0}, {"x": 95.0, "y": 5.0}],
    )

    assert matrix[3][2] == 2.0
    assert matrix[0][9] == 1.0
    assert sum(sum(row) for row in matrix) == 3.0
    assert calls["count"] <= 1


def test_patch_shape_maps_visit_only_overlapping_regular_grid_cells(
    monkeypatch: pytest.MonkeyPatch,
):
    rows = 10
    cols = 10
    patches = _regular_test_patches(rows, cols)
    calls = {"count": 0}
    original = extractor_module._bbox_overlap_area

    def counted_bbox_overlap_area(*args, **kwargs):
        calls["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(extractor_module, "_bbox_overlap_area", counted_bbox_overlap_area)
    shapes = [{"llx": 12.0, "lly": 12.0, "urx": 18.0, "ury": 18.0}]

    density = extractor_module._patch_shape_density(patches, rows, cols, shapes)
    presence = extractor_module._patch_shape_presence_count(patches, rows, cols, shapes)

    assert density[1][1] == pytest.approx(0.36)
    assert presence[1][1] == 1.0
    assert sum(sum(row) for row in density) == pytest.approx(0.36)
    assert sum(sum(row) for row in presence) == 1.0
    assert calls["count"] <= 8


def _make_workspace(
    tmp_path: Path,
    *,
    include_route_artifacts: bool = True,
    include_route_maps: bool = True,
    include_native_demand_capacity: bool = True,
) -> Path:
    ws = tmp_path / "sample-ws"
    _write_json(
        ws / "home" / "flow.json",
        {
            "steps": [
                {"name": "Floorplan", "tool": "ecc", "state": "Success", "info": {}},
                {"name": "place", "tool": "dreamplace", "state": "Success"},
                {"name": "CTS", "tool": "ecc", "state": "Success"},
                {"name": "route", "tool": "ecc", "state": "Success"},
                {"name": "drc", "tool": "ecc", "state": "Success"},
            ]
        },
    )
    _write_json(
        ws / "home" / "parameters.json",
        {
            "PDK": "ics55",
            "Design": "gcd",
            "Die": {"Size": [], "Area": 0},
            "Core": {
                "Size": [],
                "Area": 0,
                "Utilitization": 0.5,
                "Margin": [2, 2],
                "Aspect ratio": 1,
            },
            "Max fanout": 20,
            "Target density": 0.3,
            "Target overflow": 0.1,
            "Cell padding x": 600,
            "Routability opt flag": 1,
            "Bottom layer": "MET2",
            "Top layer": "MET5",
        },
    )
    for stage_dir, stage_name in [
        ("Floorplan_ecc", "Floorplan"),
        ("place_dreamplace", "place"),
        ("CTS_ecc", "CTS"),
        ("route_ecc", "route"),
        ("drc_ecc", "drc"),
    ]:
        _write_json(
            ws / stage_dir / "analysis" / f"{stage_name}_metrics.json",
            {"Tool": "ecc", "max_WNS": "1.0"},
        )
        _write_json(
            ws / stage_dir / "config" / "fp_default_config.json",
            {"Floorplan": {"Tap distance": 58}},
        )
        _write_json(
            ws / stage_dir / "config" / "pl_default_config.json",
            {"PL": {"GP": {"global_right_padding": 0}}},
        )
        _write_json(
            ws / stage_dir / "config" / "rt_default_config.json",
            {
                "RT": {
                    "-bottom_routing_layer": "MET2",
                    "-top_routing_layer": "MET5",
                    "-thread_number": "50",
                    "-enable_timing": "0",
                }
            },
        )
        if "dreamplace" in stage_dir:
            _write_json(
                ws / stage_dir / "config" / "dreamplace.json",
                {
                    "num_bins_x": 32,
                    "num_bins_y": 32,
                    "global_place_stages": [{"iteration": 3000}],
                    "target_density": 0.3,
                    "density_weight": 0.00085,
                    "random_seed": 3000,
                    "route_num_bins_x": 512,
                    "route_num_bins_y": 512,
                    "unit_horizontal_capacity": 1.5625,
                    "unit_vertical_capacity": 1.45,
                    "max_route_opt_adjust_rate": 2.0,
                },
            )
        _write_json(ws / stage_dir / "checklist.json", {"state": "Success"})
        _write_json(
            ws / stage_dir / "output" / f"gcd_{stage_name}.json",
            {
                "design name": "gcd",
                "diearea": {"path": [[0, 0], [200, 0], [200, 200], [0, 200], [0, 0]]},
                "layerInfo": [{"id": 0, "layername": "cell"}, {"id": 2, "layername": "M1"}],
                "data": [
                    {
                        "type": "group",
                        "struct name": "Instance_U1",
                        "children": [
                            {
                                "type": "box",
                                "layer": 0,
                                "path": [[0, 0], [10, 0], [10, 20], [0, 20], [0, 0]],
                            }
                        ],
                    },
                    {
                        "type": "group",
                        "struct name": "Macro_SRAM0",
                        "children": [
                            {
                                "type": "box",
                                "layer": 0,
                                "path": [[50, 50], [100, 50], [100, 100], [50, 100], [50, 50]],
                            }
                        ],
                    },
                ],
            },
        )

    _write_csv(
        ws / "place_dreamplace" / "feature" / "density_map" / "place_allcell_density.csv",
        [[1, 2], [3, 4]],
    )
    _write_csv(
        ws / "place_dreamplace" / "feature" / "density_map" / "place_macro_density.csv",
        [[1, 2], [3, 4]],
    )
    _write_csv(
        ws / "place_dreamplace" / "feature" / "density_map" / "place_stdcell_density.csv",
        [[1, 2], [3, 4]],
    )
    _write_csv(
        ws / "place_dreamplace" / "feature" / "margin_map" / "place_horizontal_margin.csv",
        [[1, 2], [3, 4]],
    )
    _write_csv(
        ws / "place_dreamplace" / "feature" / "margin_map" / "place_vertical_margin.csv",
        [[1, 2], [3, 4]],
    )
    _write_csv(
        ws / "place_dreamplace" / "feature" / "margin_map" / "place_union_margin.csv",
        [[1, 2], [3, 4]],
    )
    _write_csv(
        ws / "place_dreamplace" / "feature" / "RUDY_map" / "place_rudy_union.csv", [[1, 2], [3, 4]]
    )
    _write_csv(
        ws
        / "place_dreamplace"
        / "feature"
        / "gcell_patch_map"
        / "density_map"
        / "place_allcell_density.csv",
        [[10, 11], [12, 13]],
    )
    _write_csv(
        ws
        / "place_dreamplace"
        / "feature"
        / "gcell_patch_map"
        / "density_map"
        / "place_allcell_pin_density.csv",
        [[20, 21], [22, 23]],
    )
    _write_csv(
        ws
        / "place_dreamplace"
        / "feature"
        / "gcell_patch_map"
        / "density_map"
        / "place_allnet_density.csv",
        [[30, 31], [32, 33]],
    )
    _write_csv(
        ws
        / "place_dreamplace"
        / "feature"
        / "gcell_patch_map"
        / "density_map"
        / "place_global_net_density.csv",
        [[34, 35], [36, 37]],
    )
    _write_csv(
        ws
        / "place_dreamplace"
        / "feature"
        / "gcell_patch_map"
        / "density_map"
        / "place_local_net_density.csv",
        [[38, 39], [40, 41]],
    )
    _write_csv(
        ws
        / "place_dreamplace"
        / "feature"
        / "gcell_patch_map"
        / "density_map"
        / "place_macro_density.csv",
        [[0, 0], [0, 0]],
    )
    _write_csv(
        ws
        / "place_dreamplace"
        / "feature"
        / "gcell_patch_map"
        / "density_map"
        / "place_macro_pin_density.csv",
        [[0, 0], [0, 0]],
    )
    _write_csv(
        ws
        / "place_dreamplace"
        / "feature"
        / "gcell_patch_map"
        / "density_map"
        / "place_stdcell_density.csv",
        [[10, 11], [12, 13]],
    )
    _write_csv(
        ws
        / "place_dreamplace"
        / "feature"
        / "gcell_patch_map"
        / "density_map"
        / "place_stdcell_pin_density.csv",
        [[20, 21], [22, 23]],
    )
    _write_csv(
        ws
        / "place_dreamplace"
        / "feature"
        / "gcell_patch_map"
        / "margin_map"
        / "place_union_margin.csv",
        [[40, 41], [42, 43]],
    )
    _write_csv(
        ws
        / "place_dreamplace"
        / "feature"
        / "gcell_patch_map"
        / "RUDY_map"
        / "place_rudy_union.csv",
        [[50, 51], [52, 53]],
    )
    _write_csv(
        ws
        / "place_dreamplace"
        / "feature"
        / "gcell_patch_map"
        / "RUDY_map"
        / "place_lut_rudy_union.csv",
        [[150, 151], [152, 153]],
    )
    _write_csv(
        ws
        / "place_dreamplace"
        / "feature"
        / "egr_congestion_map"
        / "place_egr_horizontal_overflow.csv",
        [[5]],
    )
    _write_csv(
        ws
        / "place_dreamplace"
        / "feature"
        / "egr_congestion_map"
        / "place_egr_vertical_overflow.csv",
        [[7]],
    )
    _write_text(
        ws / "place_dreamplace" / "output" / "gcd_place.def",
        """
VERSION 5.8 ;
DIVIDERCHAR "/" ;
BUSBITCHARS "[]" ;
DESIGN gcd ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 200 200 ) ;
COMPONENTS 1 ;
- U1 NAND2 + PLACED ( 10 20 ) N ;
END COMPONENTS
PINS 1 ;
- OUT + NET n1 + DIRECTION OUTPUT + PLACED ( 180 50 ) N ;
END PINS
NETS 1 ;
- n1 ( U1 A ) ( PIN OUT ) ;
END NETS
END DESIGN
""".strip()
        + "\n",
    )
    _write_text(
        ws / "Floorplan_ecc" / "output" / "gcd_Floorplan.def",
        """
VERSION 5.8 ;
DIVIDERCHAR "/" ;
BUSBITCHARS "[]" ;
DESIGN gcd ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 200 200 ) ;
ROW ROW_0 core 0 0 N DO 2 BY 1 STEP 50 10 ;
COMPONENTS 2 ;
- U1 NAND2 + PLACED ( 10 20 ) N ;
- MAC0 SRAM + PLACED ( 50 50 ) N ;
- ENDCAP_0 FILLTAPH7R + FIXED ( 0 0 ) N + SIZE 50 BY 20 ;
END COMPONENTS
PINS 1 ;
- OUT + NET n1 + DIRECTION OUTPUT + PLACED ( 180 50 ) N ;
END PINS
NETS 2 ;
- n1 ( U1 A ) ( PIN OUT ) ;
- n2 ( MAC0 A ) ( U1 Y ) ;
END NETS
SPECIALNETS 1 ;
- VDD ( * VDD )
  + USE POWER
  + ROUTED MET2 10 ( 0 50 ) ( 200 * )
  ;
END SPECIALNETS
END DESIGN
""".strip()
        + "\n",
    )
    _write_sample_gcell_info(ws / "place_dreamplace")
    _write_sample_egr_demand_capacity(ws / "place_dreamplace")
    _write_json(
        ws / "place_dreamplace" / "feature" / "place.map.json",
        {
            "Density": {"cell": {"allcell_density": "density_map/place_allcell_density.csv"}},
            "Congestion": {
                "map": {
                    "egr": {
                        "horizontal": "egr_congestion_map/place_egr_horizontal_overflow.csv",
                        "vertical": "egr_congestion_map/place_egr_vertical_overflow.csv",
                    }
                },
                "overflow": {"top_average": {"horizontal": 5, "vertical": 7}},
            },
        },
    )
    if include_route_maps:
        _write_csv(
            ws
            / "route_ecc"
            / "feature"
            / "egr_congestion_map"
            / "route_egr_horizontal_overflow.csv",
            [[1, 0], [2, 3]],
        )
        _write_csv(
            ws / "route_ecc" / "feature" / "egr_congestion_map" / "route_egr_vertical_overflow.csv",
            [[0, 4], [1, 1]],
        )
        _write_csv(
            ws / "route_ecc" / "feature" / "egr_congestion_map" / "route_egr_union_overflow.csv",
            [[1, 4], [3, 4]],
        )
        _write_json(
            ws / "route_ecc" / "feature" / "route.map.json",
            {
                "Congestion": {
                    "map": {
                        "egr": {
                            "horizontal": "egr_congestion_map/route_egr_horizontal_overflow.csv",
                            "vertical": "egr_congestion_map/route_egr_vertical_overflow.csv",
                            "union": "egr_congestion_map/route_egr_union_overflow.csv",
                        }
                    },
                    "overflow": {"top_average": {"horizontal": 2.5, "vertical": 3.0}},
                }
            },
        )
    if include_route_artifacts:
        _write_sample_gcell_info(ws / "route_ecc")
        _write_text(
            ws / "route_ecc" / "output" / "gcd_route.def",
            """
VERSION 5.8 ;
DIVIDERCHAR "/" ;
BUSBITCHARS "[]" ;
DESIGN gcd ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 200 200 ) ;
TRACKS Y 50 DO 1 STEP 100 LAYER MET2 ;
TRACKS X 50 DO 1 STEP 100 LAYER MET3 ;
GCELLGRID X 0 DO 3 STEP 100 ;
GCELLGRID Y 0 DO 3 STEP 100 ;
VIAS 1 ;
- VIA23 + LAYERS MET2 VIA2 MET3 ;
END VIAS
COMPONENTS 1 ;
- U1 NAND2 + PLACED ( 10 20 ) N ;
END COMPONENTS
PINS 1 ;
- OUT + NET n1 + DIRECTION OUTPUT + PLACED ( 180 50 ) N ;
END PINS
NETS 2 ;
- n1 ( U1 A ) ( PIN OUT )
  + ROUTED MET2 ( 0 50 ) ( 200 * )
    NEW MET2 ( 0 60 ) ( 200 * )
    NEW MET3 ( 50 0 ) ( * 200 )
    NEW MET3 ( 60 0 ) ( * 200 )
    NEW MET3 ( 60 60 ) VIA23
  ;
- n2 ( U1 B ) ( U1 Y ) ;
END NETS
END DESIGN
""".strip()
            + "\n",
        )
        _write_text(
            ws / "route_ecc" / "data" / "rt" / "rt.log",
            """
[RT Info printDatabase]     idx:0 order:9 name:MET2 prefer_direction:horizontal
[RT Info printDatabase]     idx:1 order:11 name:MET3 prefer_direction:vertical
[RT Info printTableList] |      total_demand |       8 |
[RT Info printTableList] |    total_overflow |       4 |
[RT Info printTableList] | total_wire_length |   800.0 |
[RT Info printTableList] | routing | demand | prop | | routing | overflow | prop | | routing | wire_length | prop | | cut | #via | prop |
[RT Info printTableList] | MET2 | 4 | 50.00% | | MET2 | 2 | 50.00% | | MET2 | 400.0 | 50.00% | | VIA2 | 1 | 100.00% |
[RT Info printTableList] | MET3 | 4 | 50.00% | | MET3 | 2 | 50.00% | | MET3 | 400.0 | 50.00% | | Total | 1 | 100.00% |
[RT Info printTableList] | Total | 8 | 100.00% | | Total | 4 | 100.00% | | Total | 800.0 | 100.00% | | Total | 1 | 100.00% |
""".strip()
            + "\n",
        )
        if include_native_demand_capacity:
            _write_text(
                ws
                / "route_ecc"
                / "data"
                / "rt"
                / "space_router"
                / "route_native_demand_capacity_final.jsonl",
                "\n".join(
                    [
                        json.dumps(
                            {
                                "row": 0,
                                "col": 0,
                                "gcell": {"x": 0, "y": 0},
                                "layer": "MET2",
                                "layer_idx": 0,
                                "direction": "horizontal",
                                "demand": 6.0,
                                "capacity": 3.0,
                                "demand_capacity": 3.0,
                                "utilization": 2.0,
                                "source": "irt_space_router_native",
                                "stage": "space_router_final",
                            }
                        ),
                        json.dumps(
                            {
                                "row": 0,
                                "col": 0,
                                "gcell": {"x": 0, "y": 0},
                                "layer": "MET3",
                                "layer_idx": 1,
                                "direction": "vertical",
                                "demand": 4.0,
                                "capacity": 2.0,
                                "demand_capacity": 2.0,
                                "utilization": 2.0,
                                "source": "irt_space_router_native",
                                "stage": "space_router_final",
                            }
                        ),
                        json.dumps(
                            {
                                "gcell": {"x": 1, "y": 0},
                                "layer": "MET3",
                                "layer_idx": 1,
                                "direction": "vertical",
                                "demand": 8.0,
                                "capacity": 3.0,
                                "demand_capacity": 5.0,
                                "utilization": 2.6666666666666665,
                                "source": "irt_space_router_native",
                                "stage": "space_router_final",
                            }
                        ),
                        json.dumps(
                            {
                                "row": 1,
                                "col": 1,
                                "gcell": {"x": 1, "y": 1},
                                "layer": "MET2",
                                "layer_idx": 0,
                                "direction": "horizontal",
                                "demand": 1.0,
                                "capacity": 5.0,
                                "demand_capacity": -4.0,
                                "utilization": 0.2,
                                "source": "irt_space_router_native",
                                "stage": "space_router_final",
                            }
                        ),
                    ]
                )
                + "\n",
            )
        _write_json(
            ws / "route_ecc" / "feature" / "route.step.json",
            {
                "route": {
                    "DR": [
                        {
                            "iter": 1,
                            "total_wire_length": 800.0,
                            "total_violation_num": 4,
                            "total_via_num": 1,
                        }
                    ]
                }
            },
        )
        _write_json(
            ws / "route_ecc" / "data" / "sta" / "gcd.rpt.json",
            {
                "summary": [
                    {
                        "endpoint": "U1/Y",
                        "clock_group": "clk",
                        "delay_type": "max",
                        "path_delay": "1.0",
                        "path_required": "2.0",
                        "slack": "1.0",
                    }
                ],
                "slack": [{"clock": "clk", "delay_type": "max", "TNS": "0.0", "WNS": "1.0"}],
            },
        )
        _write_json(
            ws / "route_ecc" / "data" / "sta" / "wire_paths" / "wire_path_1.json",
            [
                {
                    "node_0": {
                        "Point": "U1/A",
                        "Capacitance": 0.1,
                        "slew": 0.2,
                        "trans_type": "rise",
                    }
                },
                {"net_arc_0": {"Incr": 0.3, "Resistance": 1.5}},
                {
                    "node_1": {
                        "Point": "U1/Y",
                        "Capacitance": 0.4,
                        "slew": 0.6,
                        "trans_type": "fall",
                    }
                },
            ],
        )
        _write_json(
            ws / "drc_ecc" / "data" / "drc" / "violation_map.json",
            [
                {
                    "type": "short",
                    "rule": "M2.SHORT",
                    "layer": "MET2",
                    "bbox": {"llx": 20, "lly": 20, "urx": 80, "ury": 80},
                    "count": 2,
                },
                {
                    "type": "spacing",
                    "rule": "M3.SPACE",
                    "layer": "MET3",
                    "bbox": [120, 120, 180, 180],
                },
            ],
        )
        _write_json(ws / "drc_ecc" / "analysis" / "drc_metrics.json", {"Tool": "ecc", "drc_num": 3})
    return ws


def test_read_numeric_csv_ignores_trailing_empty_columns(tmp_path: Path):
    from chipcompiler.data.foundation.parsers.map_csv import read_numeric_csv, shape

    csv_path = tmp_path / "trailing.csv"
    csv_path.write_text("1,2,\n3,,4,\n", encoding="utf-8")

    matrix = read_numeric_csv(csv_path)

    assert matrix == [[1.0, 2.0], [3.0, 0.0, 4.0]]
    assert shape(matrix) == (2, 3)


def test_iccd_full_v1_extractor_writes_parquet_contract_and_no_legacy_defaults(tmp_path: Path):
    ws = _make_workspace(tmp_path)
    result = FoundationExtractor(ws, profile="iccd_full_v1").extract()

    foundation_dir = result.foundation_dir
    schema = json.loads((foundation_dir / "schema.json").read_text(encoding="utf-8"))
    manifest = json.loads((foundation_dir / "manifest.json").read_text(encoding="utf-8"))
    quality = json.loads((foundation_dir / "quality.json").read_text(encoding="utf-8"))
    migration_report = json.loads(
        (foundation_dir / "migration_report.json").read_text(encoding="utf-8")
    )

    assert schema["contract_name"] == "foundation_data/ecc"
    assert schema["storage_format"] == "parquet+json_views"
    assert schema["schema_version"]
    assert "tables" in schema
    for table_name in [
        "designs",
        "runs",
        "stages",
        "artifacts",
        "provenance",
        "semantic_blocks",
        "tech_layers",
        "tech_vias",
        "library_cells",
        "patches",
        "patch_neighbors",
        "run_stage_patch_maps",
        "run_stage_patch_features",
        "run_patch_route_labels",
        "run_patch_route_label_layers",
        "patch_entity_refs",
        "instances",
        "instance_stage_state",
        "pins",
        "pin_stage_state",
        "nets",
        "net_terminals",
        "wire_segments",
        "wire_patch_intersections",
        "routing_vertices",
        "routing_edges",
        "timing_paths",
        "timing_path_points",
        "timing_edges",
        "timing_wire_path_nodes",
        "stage_metrics",
        "stage_deltas",
    ]:
        assert table_name in schema["tables"]
        table_meta = manifest["tables"][table_name]
        table_path = foundation_dir / table_meta["path"]
        assert table_path.exists(), table_name
        assert table_meta["format"] == "parquet"
        assert table_meta["row_count"] >= 0
        assert table_meta["primary_key"] == schema["tables"][table_name]["primary_key"]
        assert len(table_meta["sha256"]) == 64
        assert table_meta["size_bytes"] > 0

    assert manifest["contract_name"] == "foundation_data/ecc"
    assert manifest["storage_format"] == "parquet+json_views"
    assert manifest["route_completion_mode"] == "full_route"
    assert manifest["schema"] == "foundation_data/ecc/schema.json"
    assert manifest["design_id"].startswith("design_")
    assert manifest["run_id"].startswith("run_")
    assert manifest["created_at"]
    assert (
        manifest["generated_by"]["extractor"] == "chipcompiler.data.foundation.FoundationExtractor"
    )
    assert [stage["stage_name"] for stage in manifest["stages"]] == [
        "Floorplan",
        "place",
        "CTS",
        "route",
        "drc",
    ]
    assert manifest["tables"]["patches"]["row_count"] == 4
    assert manifest["tables"]["run_stage_patch_features"]["row_count"] == 20
    assert manifest["tables"]["run_patch_route_labels"]["row_count"] == 4
    route_label_columns = schema["tables"]["run_patch_route_labels"]["columns"]
    assert "horizontal_demand_capacity" in route_label_columns
    assert "vertical_demand_capacity" in route_label_columns
    assert "union_demand_capacity" in route_label_columns
    assert "horizontal_overflow" not in route_label_columns
    assert "vertical_overflow" not in route_label_columns
    assert "union_overflow" not in route_label_columns
    layer_label_columns = schema["tables"]["run_patch_route_label_layers"]["columns"]
    assert "demand_capacity" in layer_label_columns
    assert "overflow" not in layer_label_columns
    assert manifest["views"]["ml_task_views"] == "foundation_data/ecc/views/ml/task_views.json"
    assert manifest["migration_report"] == "foundation_data/ecc/migration_report.json"
    assert quality["tables"]["patches"]["row_count"] == 4
    assert quality["legacy_outputs"]["vectors_default_enabled"] is False
    assert quality["legacy_outputs"]["maps_default_enabled"] is False
    assert quality["tables"]["semantic_blocks"]["row_count"] > 0
    assert migration_report["contract_name"] == "foundation_data/ecc"
    assert migration_report["source_docs_dir"] == "ecos/agent/docs/foundatio_data"
    for source_doc in [
        "vec_patches.md",
        "vec_pins.md",
        "vec_nets.md",
        "vec_wires.md",
        "vec_routing_graph.md",
        "vec_timing_paths.md",
        "labels_route_native_demand_capacity.md",
        "views_ml.md",
    ]:
        assert source_doc in migration_report["source_docs"]
    assert (
        migration_report["information_families"]["route_native_labels"]["status"]
        == "preserved_as_table"
    )
    assert (
        migration_report["information_families"]["source_refs_null_reason"]["status"]
        == "preserved_as_semantic_block"
    )

    dataset_index = json.loads(
        (foundation_dir / "views" / "ml" / "dataset_index.json").read_text(encoding="utf-8")
    )
    task_views = json.loads(
        (foundation_dir / "views" / "ml" / "task_views.json").read_text(encoding="utf-8")
    )
    assert dataset_index["tables_dir"] == "tables"
    assert "progressive_patch_route_demand_capacity" in task_views["tasks"]
    task = task_views["tasks"]["progressive_patch_route_demand_capacity"]
    assert task["input_table"] == "run_stage_patch_features"
    assert task["label_table"] == "run_patch_route_labels"
    assert task["leakage_policy"]["route_truth_as_preroute_input"] == "forbidden"
    assert task["route_completion_mode"] == "full_route"

    assert not (foundation_dir / "vectors").exists()
    assert not (foundation_dir / "maps").exists()
    assert not (foundation_dir / "labels" / "route_native_demand_capacity.jsonl").exists()

    top_patches = json.loads(
        (foundation_dir / "views" / "agent" / "top_patches.json").read_text(encoding="utf-8")
    )["items"]
    top_nets = json.loads(
        (foundation_dir / "views" / "agent" / "top_nets.json").read_text(encoding="utf-8")
    )["items"]
    assert top_patches
    assert top_nets
    assert top_patches[0]["provenance"]["query"]["provenance_id"]
    assert top_nets[0]["provenance"]["query"]["provenance_id"]


def test_iccd_full_v1_extractor_parses_drc_final_artifacts(tmp_path: Path):
    ws = _make_workspace(tmp_path)
    flow_path = ws / "home" / "flow.json"
    flow = json.loads(flow_path.read_text(encoding="utf-8"))
    flow["steps"].append({"name": "drc_final", "tool": "ecc", "state": "Success"})
    _write_json(flow_path, flow)
    _write_json(
        ws / "drc_final_ecc" / "data" / "drc_final" / "violation_map.json",
        [
            {
                "type": "short",
                "rule": "M2.SHORT",
                "layer": "MET2",
                "bbox": [20, 20, 80, 80],
                "count": 2,
            }
        ],
    )
    _write_json(
        ws / "drc_final_ecc" / "analysis" / "drc_final_metrics.json",
        {"Tool": "ecc", "drc_num": 2},
    )

    result = FoundationExtractor(ws, profile="iccd_full_v1").extract(export_legacy_debug=True)

    patches = _read_jsonl(result.foundation_dir / "vectors" / "patches" / "drc_final.jsonl")
    assert patches[0]["drc_context"]["count"] == 2
    assert patches[0]["drc_context"]["by_type"] == {"short": 2}
    assert patches[0]["drc_context"]["by_layer"] == {"MET2": 2}


def test_iccd_full_v1_extractor_publishes_drc_attribution_inputs(tmp_path: Path):
    import pyarrow.parquet as pq

    ws = _make_workspace(tmp_path)
    result = FoundationExtractor(ws, profile="iccd_full_v1").extract()
    foundation_dir = result.foundation_dir
    manifest = json.loads((foundation_dir / "manifest.json").read_text(encoding="utf-8"))
    schema = json.loads((foundation_dir / "schema.json").read_text(encoding="utf-8"))

    table_meta = manifest["tables"]["drc_violations"]
    rows = pq.read_table(foundation_dir / table_meta["path"]).to_pylist()
    short = next(row for row in rows if row["native_type"] == "short")
    artifact_ids = {
        row["artifact_id"]
        for row in pq.read_table(
            foundation_dir / manifest["tables"]["artifacts"]["path"]
        ).to_pylist()
    }
    drc_provenance = pq.read_table(
        foundation_dir / manifest["tables"]["provenance"]["path"]
    ).to_pylist()

    assert schema["tables"]["drc_violations"]["primary_key"] == [
        "design_id",
        "run_id",
        "stage_name",
        "violation_id",
    ]
    assert len(rows) == 2
    assert {row["stage_name"] for row in rows} == {"drc"}
    assert short["normalized_class"] == "short"
    assert short["layer"] == "MET2"
    assert json.loads(short["bbox_json"]) == {
        "llx": 20.0,
        "lly": 20.0,
        "urx": 80.0,
        "ury": 80.0,
    }
    assert short["availability"] == "available"
    assert short["source_artifact_id"] in artifact_ids
    assert any(
        row["target_table"] == "drc_violations"
        and row["artifact_id"] == short["source_artifact_id"]
        for row in drc_provenance
    )

    inputs = json.loads(
        (foundation_dir / "views" / "agent" / "attribution_inputs.v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert set(inputs) == {"schema_version", "design_id", "run_id", "tables", "profiles"}
    assert inputs["schema_version"] == "foundation_data/ecc/attribution_inputs.v1"
    assert inputs["design_id"] == manifest["design_id"]
    assert inputs["run_id"] == manifest["run_id"]
    assert set(inputs["tables"]) == {
        "drc_violations",
        "wire_segments",
        "run_stage_patch_features",
        "instance_stage_state",
        "pin_stage_state",
        "placement_rows",
        "instance_row_refs",
        "clock_instance_refs",
    }
    assert inputs["tables"]["drc_violations"] == {
        "ref": table_meta["path"],
        "sha256": table_meta["sha256"],
    }
    assert all(set(table) == {"ref", "sha256"} for table in inputs["tables"].values())
    assert manifest["tables"]["placement_rows"]["row_count"] > 0
    assert manifest["tables"]["instance_row_refs"]["row_count"] == 0
    assert manifest["tables"]["clock_instance_refs"]["row_count"] == 0
    assert set(inputs["profiles"]) == {"C1", "R1", "R3", "D1", "D2"}
    assert inputs["profiles"]["R1"]["rule_version"] == "route_local.v1"
    assert inputs["profiles"]["R1"]["availability"] == "available"
    assert inputs["profiles"]["D1"]["rule_version"] == "native_drc_wire_via_open_short.v1"
    assert inputs["profiles"]["D1"]["seed_ids"] == [short["violation_id"]]
    assert len(inputs["profiles"]["R1"]["seed_ids"]) <= 32
    assert all(
        set(profile) == {"availability", "rule_version", "seed_ids"}
        for profile in inputs["profiles"].values()
    )
    assert inputs["profiles"]["C1"]["availability"] == "missing"
    assert inputs["profiles"]["R3"] == {
        "availability": "available",
        "rule_version": "congestion_or_pin_access.v1",
        "seed_ids": ["3", "2", "1", "0"],
    }
    assert inputs["profiles"]["D2"]["availability"] == "missing"


def test_iccd_full_v1_r3_rejects_negative_native_demand_capacity(tmp_path: Path):
    ws = _make_workspace(tmp_path)
    early_router = ws / "place_dreamplace" / "data" / "rt" / "rt_temp_directory" / "early_router"
    for layer in ("MET2", "MET3"):
        _write_csv(early_router / f"net_map_{layer}.csv", [[0, 0], [0, 0]])
        _write_csv(early_router / f"supply_map_{layer}.csv", [[1, 1], [1, 1]])
    for path in (ws / "place_dreamplace" / "feature" / "egr_congestion_map").glob("*.csv"):
        path.unlink()
    for path in (ws / "place_dreamplace" / "feature" / "gcell_patch_map" / "density_map").glob(
        "*pin_density.csv"
    ):
        path.unlink()

    result = FoundationExtractor(ws, profile="iccd_full_v1").extract()
    inputs = json.loads(
        (result.foundation_dir / "views" / "agent" / "attribution_inputs.v1.json").read_text(
            encoding="utf-8"
        )
    )

    assert inputs["profiles"]["R3"] == {
        "availability": "missing",
        "rule_version": "congestion_or_pin_access.v1",
        "seed_ids": [],
    }


def test_iccd_full_v1_r3_prefers_direct_nonnegative_egr_overflow_map(tmp_path: Path):
    ws = _make_workspace(tmp_path)
    map_dir = ws / "place_dreamplace" / "feature" / "egr_congestion_map"
    for path in map_dir.glob("*.csv"):
        path.unlink()
    _write_csv(map_dir / "place_egr_union_overflow.csv", [[0.0, 0.0], [0.0, 9.0]])
    for path in (ws / "place_dreamplace" / "feature" / "gcell_patch_map" / "density_map").glob(
        "*pin_density.csv"
    ):
        path.unlink()

    result = FoundationExtractor(ws, profile="iccd_full_v1").extract()
    inputs = json.loads(
        (result.foundation_dir / "views" / "agent" / "attribution_inputs.v1.json").read_text(
            encoding="utf-8"
        )
    )

    assert inputs["profiles"]["R3"] == {
        "availability": "available",
        "rule_version": "congestion_or_pin_access.v1",
        "seed_ids": ["3"],
    }


def test_instance_row_refs_require_explicit_def_row_lattice_alignment():
    placement_rows = [
        {
            "design_id": "design_1",
            "run_id": "run_1",
            "stage_name": "drc",
            "row_id": "row_1",
            "origin_x": 0.0,
            "origin_y": 20.0,
            "count_x": 2,
            "count_y": 1,
            "step_x": 10.0,
            "step_y": 10.0,
        }
    ]
    instances = [
        {
            "design_id": "design_1",
            "run_id": "run_1",
            "stage_name": "drc",
            "instance_key": "U1",
            "origin_x": 10.0,
            "origin_y": 20.0,
        },
        {
            "design_id": "design_1",
            "run_id": "run_1",
            "stage_name": "drc",
            "instance_key": "U2",
            "origin_x": 5.0,
            "origin_y": 20.0,
        },
    ]

    refs = extractor_module._instance_row_ref_rows(instances, placement_rows)

    assert refs == [
        {
            "design_id": "design_1",
            "run_id": "run_1",
            "stage_name": "drc",
            "instance_key": "U1",
            "row_id": "row_1",
            "relation": "origin_on_row_lattice",
            "availability": "available",
        }
    ]


def test_iccd_fast_profile_skips_audit_and_route_detail_tables(tmp_path: Path):
    import pyarrow.parquet as pq

    ws = _make_workspace(tmp_path)
    result = FoundationExtractor(ws, profile="iccd_full_v1").extract(
        route_completion_mode="space_router_label",
        materialize_audit_tables=False,
        route_detail_level="labels_only",
    )

    foundation_dir = result.foundation_dir
    manifest = json.loads((foundation_dir / "manifest.json").read_text(encoding="utf-8"))
    progressive = json.loads(
        (foundation_dir / "views" / "ml" / "progressive_patch_dataset.json").read_text(
            encoding="utf-8"
        )
    )

    assert manifest["options"]["materialize_audit_tables"] is False
    assert manifest["options"]["route_detail_level"] == "labels_only"
    assert progressive["route_detail_level"] == "labels_only"
    assert manifest["tables"]["run_patch_route_labels"]["row_count"] > 0
    assert manifest["tables"]["run_patch_route_label_layers"]["row_count"] > 0
    for table_name in (
        "provenance",
        "semantic_blocks",
        "patch_entity_refs",
        "wire_segments",
        "wire_patch_intersections",
        "routing_vertices",
        "routing_edges",
    ):
        table = pq.read_table(foundation_dir / manifest["tables"][table_name]["path"])
        assert table.num_rows == 0, table_name


def test_iccd_full_v1_extractor_rejects_unknown_route_detail_level(tmp_path: Path):
    ws = _make_workspace(tmp_path)

    with pytest.raises(ValueError, match="route_detail_level"):
        FoundationExtractor(ws, profile="iccd_full_v1").extract(route_detail_level="wire_heavy")


def test_iccd_full_v1_extractor_records_space_router_label_completion_mode(tmp_path: Path):
    ws = _make_workspace(tmp_path)
    result = FoundationExtractor(ws, profile="iccd_full_v1").extract(
        route_completion_mode="space_router_label"
    )

    foundation_dir = result.foundation_dir
    manifest = json.loads((foundation_dir / "manifest.json").read_text(encoding="utf-8"))
    task_views = json.loads(
        (foundation_dir / "views" / "ml" / "task_views.json").read_text(encoding="utf-8")
    )
    progressive = json.loads(
        (foundation_dir / "views" / "ml" / "progressive_patch_dataset.json").read_text(
            encoding="utf-8"
        )
    )

    assert manifest["route_completion_mode"] == "space_router_label"
    assert manifest["options"]["route_completion_mode"] == "space_router_label"
    assert (
        task_views["tasks"]["progressive_patch_route_demand_capacity"]["route_completion_mode"]
        == "space_router_label"
    )
    assert progressive["route_completion_mode"] == "space_router_label"
    assert progressive["label_source"]["completion_mode"] == "space_router_label"
    assert progressive["leakage_policy"]["route_truth_as_preroute_input"] == "forbidden"


def test_iccd_full_v1_extractor_rejects_unknown_route_completion_mode(tmp_path: Path):
    ws = _make_workspace(tmp_path)

    with pytest.raises(ValueError, match="route_completion_mode"):
        FoundationExtractor(ws, profile="iccd_full_v1").extract(
            route_completion_mode="early_router"
        )


def test_iccd_full_v1_extractor_emits_stage_and_table_progress_logs(tmp_path: Path, caplog):
    ws = _make_workspace(tmp_path)

    with caplog.at_level(logging.INFO, logger="ecos.api.foundation"):
        FoundationExtractor(ws, profile="iccd_full_v1").extract()

    messages = [record.getMessage() for record in caplog.records]
    assert any("foundation_extract start" in message for message in messages)
    assert any("foundation_stage start name=write_vectors" in message for message in messages)
    assert any("foundation_vectors stage_done stage=route" in message for message in messages)
    assert any(
        "foundation_table done name=run_patch_route_labels" in message for message in messages
    )
    assert any("foundation_extract done" in message for message in messages)


def test_parquet_contract_preserves_all_semantic_blocks_and_auditable_views(tmp_path: Path):
    import pyarrow.parquet as pq

    ws = _make_workspace(tmp_path)
    result = FoundationExtractor(ws, profile="iccd_full_v1").extract(export_legacy_debug=True)
    foundation_dir = result.foundation_dir
    schema = json.loads((foundation_dir / "schema.json").read_text(encoding="utf-8"))

    def table_rows(name: str, columns: list[str] | None = None) -> list[dict]:
        return pq.read_table(
            foundation_dir / schema["tables"][name]["path"], columns=columns
        ).to_pylist()

    semantic_rows = table_rows(
        "semantic_blocks",
        [
            "stage_name",
            "entity_type",
            "entity_key",
            "block_name",
            "block_payload",
            "source_doc",
            "source_field_path",
            "preserved_reason",
            "future_normalization_plan",
        ],
    )
    expected = 0
    for stage in ["Floorplan", "place", "CTS", "route", "drc"]:
        for _entity, folder in (
            ("patch", "patches"),
            ("instance", "instances"),
            ("pin", "pins"),
            ("net", "nets"),
            ("wire_segment", "wires"),
            ("routing_graph", "routing_graphs"),
            ("timing_path", "timing_paths"),
        ):
            for record in _read_jsonl(foundation_dir / "vectors" / folder / f"{stage}.jsonl"):
                expected += sum(
                    1
                    for block in ("source_refs", "null_reason", "progressive_metadata")
                    if record.get(block) is not None
                )
    assert len(semantic_rows) == expected
    assert all(row["source_doc"] and row["source_field_path"] for row in semantic_rows)
    assert all(
        row["preserved_reason"] and row["future_normalization_plan"] for row in semantic_rows
    )
    assert not any(
        token in row["block_payload"]
        for row in semantic_rows
        for token in ("vectors/", "maps/", "labels/")
    )

    feature_columns = schema["tables"]["run_stage_patch_features"]["columns"]
    assert {"macro_count", "net_count_overlap"} <= set(feature_columns)
    feature_rows = table_rows("run_stage_patch_features")
    place0 = next(
        row for row in feature_rows if row["stage_name"] == "place" and row["patch_id"] == 0
    )
    assert place0["macro_count"] == 1
    assert place0["net_count_overlap"] == 1

    provenance_rows = table_rows(
        "provenance", ["provenance_id", "artifact_id", "derived_from_artifact_ids"]
    )
    provenance_by_id = {row["provenance_id"]: row for row in provenance_rows}
    artifact_ids = {row["artifact_id"] for row in table_rows("artifacts", ["artifact_id"])}
    for table_name in ("run_stage_patch_maps", "run_stage_patch_features", "stage_deltas"):
        refs = {
            row["provenance_id"]
            for row in table_rows(table_name, ["provenance_id"])
            if row["provenance_id"]
        }
        assert refs <= set(provenance_by_id)
        for ref in refs:
            derived = set(json.loads(provenance_by_id[ref]["derived_from_artifact_ids"] or "[]"))
            direct = provenance_by_id[ref]["artifact_id"]
            assert direct in artifact_ids or (derived and derived <= artifact_ids), ref

    delta_rows = table_rows("stage_deltas", ["entity_type", "change_type", "metric_name"])
    assert any(
        row["entity_type"] == "patch" and row["change_type"] == "metric_changed"
        for row in delta_rows
    )
    assert any(
        row["entity_type"] == "timing_path" and row["change_type"] == "state_changed"
        for row in delta_rows
    )

    top_patches = json.loads(
        (foundation_dir / "views" / "agent" / "top_patches.json").read_text(encoding="utf-8")
    )["items"]
    patch_scores = [item["score"] for item in top_patches]
    assert patch_scores == sorted(patch_scores, reverse=True)
    assert top_patches[0]["patch_id"] == 1
    assert all("score_source" in item and "provenance" in item for item in top_patches)
    assert all(item["provenance"].get("query", {}).get("provenance_id") for item in top_patches)

    top_nets = json.loads(
        (foundation_dir / "views" / "agent" / "top_nets.json").read_text(encoding="utf-8")
    )["items"]
    net_scores = [item["score"] for item in top_nets]
    assert net_scores == sorted(net_scores, reverse=True)
    assert all("score_source" in item and "provenance" in item for item in top_nets)
    assert all(item["provenance"].get("query", {}).get("provenance_id") for item in top_nets)

    progressive = json.loads(
        (foundation_dir / "views" / "ml" / "progressive_patch_dataset.json").read_text(
            encoding="utf-8"
        )
    )
    assert progressive["stage_policy"] == {
        "P1": ["Floorplan"],
        "P2": ["Floorplan", "place"],
        "P3": ["Floorplan", "place", "CTS"],
    }
    assert progressive["leakage_policy"]["route_truth_as_preroute_input"] == "forbidden"
    assert "route" not in progressive["allowed_input_stages"]["P3"]
    assert "run_patch_route_label_layers" in progressive["forbidden_input_tables"]


def test_stage_table_preserves_runtime_and_peak_memory_from_flow(tmp_path: Path):
    import pyarrow.parquet as pq

    ws = _make_workspace(tmp_path)
    flow_path = ws / "home" / "flow.json"
    flow = json.loads(flow_path.read_text(encoding="utf-8"))
    flow["steps"][0].update({"runtime": "0:0:7", "peak memory (mb)": 101.5})
    flow["steps"][1].update({"runtime": "1:02:03", "peak memory (mb)": "202.25"})
    flow["steps"][2].update({"runtime": 4.5, "peak memory (mb)": 303})
    flow["steps"][3].update({"runtime": "bad", "peak memory (mb)": None})
    flow_path.write_text(json.dumps(flow), encoding="utf-8")

    result = FoundationExtractor(ws, profile="iccd_full_v1").extract()
    schema = json.loads((result.foundation_dir / "schema.json").read_text(encoding="utf-8"))
    rows = pq.read_table(
        result.foundation_dir / schema["tables"]["stages"]["path"],
        columns=["stage_name", "runtime_s", "peak_memory_mb"],
    ).to_pylist()
    by_stage = {row["stage_name"]: row for row in rows}

    assert by_stage["Floorplan"]["runtime_s"] == 7.0
    assert by_stage["Floorplan"]["peak_memory_mb"] == 101.5
    assert by_stage["place"]["runtime_s"] == 3723.0
    assert by_stage["place"]["peak_memory_mb"] == 202.25
    assert by_stage["CTS"]["runtime_s"] == 4.5
    assert by_stage["CTS"]["peak_memory_mb"] == 303.0
    assert by_stage["route"]["runtime_s"] is None
    assert by_stage["route"]["peak_memory_mb"] is None


def test_write_tables_passes_iterables_without_eager_list_materialization(
    tmp_path: Path, monkeypatch
):
    import chipcompiler.data.foundation.table_contract as table_contract_module

    captured = {}

    def fake_write_parquet(path: Path, records, *, columns=None, schema=None, batch_size=2048):
        if path.name == "timing_paths.parquet":
            captured["records_type"] = type(records)
            captured["records_is_list"] = isinstance(records, list)
            captured["columns"] = tuple(columns or ())
            captured["schema"] = schema
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"PAR1")
        for _ in records:
            return 1
        return 0

    monkeypatch.setattr(table_contract_module, "write_parquet", fake_write_parquet)
    monkeypatch.setattr(table_contract_module, "file_sha256", lambda path: "sha256")

    def rows():
        yield {
            "design_id": "design:gcd",
            "run_id": "run:gcd",
            "stage_name": "route",
            "path_id": "path:1",
            "startpoint": "{}",
            "endpoint": "{}",
            "delay_type": "max",
            "slack": -0.2,
            "arrival": 1.3,
            "required": 1.1,
            "path_group": "clk",
            "path_length_summary": "{}",
            "criticality": 0.9,
        }

    registry = write_tables(tmp_path / "registry", {"timing_paths": rows()})

    assert captured["records_is_list"] is False
    assert captured["records_type"] is not list
    assert captured["columns"] == TABLE_SPECS["timing_paths"].columns
    assert captured["schema"] == TABLE_SPECS["timing_paths"].arrow_schema()
    assert registry["timing_paths"]["row_count"] == 1


def test_write_parquet_writes_in_batches_when_batch_size_is_set(tmp_path: Path, monkeypatch):
    import pyarrow.parquet as pq

    original_writer = pq.ParquetWriter
    write_sizes: list[int] = []
    close_calls: list[int] = []

    class RecordingWriter:
        def __init__(self, path, schema):
            self._writer = original_writer(path, schema)

        def write_table(self, table):
            write_sizes.append(table.num_rows)
            self._writer.write_table(table)

        def close(self):
            close_calls.append(1)
            self._writer.close()

    monkeypatch.setattr(pq, "ParquetWriter", RecordingWriter)

    rows = (
        {
            "design_id": "design:gcd",
            "run_id": "run:gcd",
            "stage_name": "route",
            "path_id": f"path:{idx}",
            "startpoint": "{}",
            "endpoint": "{}",
            "delay_type": "max",
            "slack": float(-idx),
            "arrival": float(idx),
            "required": 1.1,
            "path_group": "clk",
            "path_length_summary": "{}",
            "criticality": 1.0,
        }
        for idx in range(5)
    )

    row_count = write_parquet(
        tmp_path / "batched.parquet",
        rows,
        columns=TABLE_SPECS["timing_paths"].columns,
        batch_size=2,
    )

    assert row_count == 5
    assert close_calls == [1]
    assert write_sizes == [2, 2, 1]


def test_write_parquet_same_schema_batches_do_not_read_existing_table(tmp_path: Path, monkeypatch):
    import pyarrow.parquet as pq

    def fail_read_table(*args, **kwargs):
        raise AssertionError("same-schema batched writes should not read existing parquet data")

    monkeypatch.setattr(pq, "read_table", fail_read_table)

    rows = ({"a": idx, "b": f"row-{idx}"} for idx in range(6))
    row_count = write_parquet(tmp_path / "same-schema.parquet", rows, batch_size=2)

    assert row_count == 6


def test_write_parquet_contract_schema_does_not_read_back_existing_table(
    tmp_path: Path, monkeypatch
):
    import pyarrow.parquet as pq

    def fail_read_table(*args, **kwargs):
        raise AssertionError(
            "fixed contract schema writes must not read back existing parquet data"
        )

    monkeypatch.setattr(pq, "read_table", fail_read_table)

    rows = [
        {
            "provenance_id": "p0",
            "target_table": "wire_segments",
            "target_key": "wire:0",
            "target_field": "*",
            "artifact_id": None,
            "derived_from_artifact_ids": [],
            "source_section": "foundation_extractor",
            "source_index": None,
            "availability_code": "available",
            "null_reason": None,
            "confidence": 1,
            "notes": {"kind": "dict_payload_should_be_stringified"},
        },
        {
            "provenance_id": "p1",
            "target_table": "wire_segments",
            "target_key": "wire:1",
            "target_field": "*",
            "artifact_id": "artifact:route_def",
            "derived_from_artifact_ids": ["artifact:route_def"],
            "source_section": "foundation_extractor",
            "source_index": 1,
            "availability_code": "available",
            "null_reason": None,
            "confidence": 0.5,
            "notes": "already string",
        },
    ]

    row_count = write_parquet(
        tmp_path / "contract-schema.parquet",
        rows,
        columns=TABLE_SPECS["provenance"].columns,
        schema=TABLE_SPECS["provenance"].arrow_schema(),
        batch_size=1,
    )

    assert row_count == 2


def test_write_parquet_handles_nullable_columns_when_later_batches_introduce_values(tmp_path: Path):
    import pyarrow.parquet as pq

    rows = [
        {
            "provenance_id": "p0",
            "target_table": "run_stage_patch_features",
            "target_key": "k0",
            "target_field": "*",
            "artifact_id": None,
            "derived_from_artifact_ids": "[]",
            "source_section": "foundation_extractor",
            "source_index": None,
            "availability_code": "available",
            "null_reason": None,
            "confidence": 1.0,
            "notes": "first",
        },
        {
            "provenance_id": "p1",
            "target_table": "run_stage_patch_features",
            "target_key": "k1",
            "target_field": "*",
            "artifact_id": None,
            "derived_from_artifact_ids": "[]",
            "source_section": "foundation_extractor",
            "source_index": None,
            "availability_code": "available",
            "null_reason": None,
            "confidence": 1.0,
            "notes": "second",
        },
        {
            "provenance_id": "p2",
            "target_table": "run_stage_patch_features",
            "target_key": "k2",
            "target_field": "*",
            "artifact_id": "artifact:2",
            "derived_from_artifact_ids": '["artifact:2"]',
            "source_section": "foundation_extractor",
            "source_index": None,
            "availability_code": "available",
            "null_reason": None,
            "confidence": 1.0,
            "notes": "third",
        },
    ]

    path = tmp_path / "provenance-batched.parquet"
    row_count = write_parquet(path, rows, columns=TABLE_SPECS["provenance"].columns, batch_size=2)

    assert row_count == 3
    written = pq.read_table(path).to_pylist()
    assert written[2]["artifact_id"] == "artifact:2"


def test_write_parquet_prescans_initial_batches_to_avoid_common_schema_widening_readback(
    tmp_path: Path, monkeypatch
):
    import pyarrow as pa
    import pyarrow.parquet as pq

    def fail_read_table(*args, **kwargs):
        raise AssertionError(
            "initial prescan should avoid readback for common early schema widening"
        )

    monkeypatch.setattr(pq, "read_table", fail_read_table)

    path = tmp_path / "prescan-widening.parquet"
    rows = [{"a": 1}, {"a": 2}, {"a": 1.5}, {"a": "late"}]
    row_count = write_parquet(path, rows, batch_size=2)

    assert row_count == 4
    table = pq.ParquetDataset(path).read()
    assert table.schema.field("a").type == pa.string()
    assert table.to_pylist() == [{"a": "1"}, {"a": "2"}, {"a": "1.5"}, {"a": "late"}]


def test_write_parquet_preserves_float_values_when_later_batches_widen_int_columns(tmp_path: Path):
    import pyarrow.parquet as pq

    path = tmp_path / "schema-widening.parquet"
    row_count = write_parquet(path, [{"a": 1}, {"a": 2}, {"a": 1.5}], batch_size=2)

    assert row_count == 3
    assert pq.read_table(path).to_pylist() == [{"a": 1.0}, {"a": 2.0}, {"a": 1.5}]


def test_write_parquet_preserves_values_when_later_batches_widen_to_string(tmp_path: Path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    path = tmp_path / "schema-string-widening.parquet"
    row_count = write_parquet(path, [{"a": 1}, {"a": 2}, {"a": "late"}], batch_size=2)
    table = pq.read_table(path)

    assert row_count == 3
    assert table.schema.field("a").type == pa.string()
    assert table.to_pylist() == [{"a": "1"}, {"a": "2"}, {"a": "late"}]


def test_parquet_registry_preserves_schema_for_empty_tables(tmp_path: Path):
    import pyarrow.parquet as pq

    registry = write_tables(tmp_path, {})

    assert registry["timing_paths"]["row_count"] == 0
    table = pq.read_table(tmp_path / registry["timing_paths"]["path"])
    assert table.num_rows == 0
    assert table.schema.names == list(TABLE_SPECS["timing_paths"].columns)


def test_write_tables_can_skip_tables_with_registry_overrides(tmp_path: Path, monkeypatch):
    written: list[str] = []

    def fake_write_parquet(path: Path, records, *, columns=None, schema=None, batch_size=2048):
        del records, columns, schema, batch_size
        written.append(path.stem)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"PAR1")
        return 0

    monkeypatch.setattr(table_contract_module, "write_parquet", fake_write_parquet)
    monkeypatch.setattr(table_contract_module, "file_sha256", lambda path: f"sha:{path.stem}")

    override = {
        "path": "../design_base/foundation_data/ecc/tables/patches.parquet",
        "format": "parquet",
        "row_count": 4,
        "sha256": "0" * 64,
        "size_bytes": 123,
    }
    registry = table_contract_module.write_tables(
        tmp_path,
        {},
        skip_tables={"patches"},
        registry_overrides={"patches": override},
    )

    assert "patches" not in written
    assert not (tmp_path / "tables" / "patches.parquet").exists()
    assert registry["patches"] == {
        **override,
        "primary_key": list(TABLE_SPECS["patches"].primary_key),
        "partition_fields": list(TABLE_SPECS["patches"].partition_fields),
    }
    assert "designs" in written


def test_write_tables_requires_registry_override_for_skipped_table(tmp_path: Path):
    with pytest.raises(ValueError, match="missing registry override for skipped table: patches"):
        table_contract_module.write_tables(tmp_path, {}, skip_tables={"patches"})


def test_large_table_builders_return_lazy_iterables(tmp_path: Path):
    ws = _make_workspace(tmp_path)
    extractor = FoundationExtractor(ws, profile="iccd_full_v1")
    extractor.extract(export_legacy_debug=True)
    flow = extractor._read_json(ws / "home" / "flow.json")
    stages = extractor._stage_infos(flow)
    stage_ids = {stage.name: f"stage:{index}" for index, stage in enumerate(stages)}
    canonical_grid = json.loads(
        (extractor.foundation_dir / "canonical_grid.json").read_text(encoding="utf-8")
    )
    canonical_maps = extractor._write_maps(
        extractor._collect_raw_maps(stages),
        canonical_grid,
        stages,
        extractor._collect_def_data(stages),
    )

    lazy_tables = {
        "semantic_blocks": extractor._semantic_block_rows("design:gcd", "run:gcd", stages),
        "run_stage_patch_maps": extractor._patch_map_rows(
            "design:gcd", "run:gcd", stage_ids, canonical_grid, canonical_maps
        ),
        "run_stage_patch_features": extractor._patch_feature_rows(
            "design:gcd", "run:gcd", stage_ids, stages
        ),
        "routing_vertices": extractor._routing_vertex_rows("design:gcd", "run:gcd", stages),
        "routing_edges": extractor._routing_edge_rows("design:gcd", "run:gcd", stages),
        "timing_paths": extractor._timing_path_rows("design:gcd", "run:gcd", stages),
        "patch_entity_refs": extractor._patch_entity_ref_rows("design:gcd", "run:gcd", stages),
        "wire_segments": extractor._wire_segment_rows("design:gcd", "run:gcd", stages),
        "wire_patch_intersections": extractor._wire_patch_intersection_rows(
            "design:gcd", "run:gcd", stages
        ),
        "timing_path_points": extractor._timing_path_point_rows("design:gcd", "run:gcd", stages),
        "timing_edges": extractor._timing_edge_rows("design:gcd", "run:gcd", stages),
        "timing_wire_path_nodes": extractor._timing_wire_path_node_rows(
            "design:gcd", "run:gcd", stages
        ),
        "stage_deltas": extractor._stage_delta_rows("design:gcd", "run:gcd", stages),
    }

    for table_name, rows in lazy_tables.items():
        assert not isinstance(rows, list), table_name
        assert isinstance(rows, Iterable), table_name
        assert next(iter(rows)), table_name


def test_provenance_rows_do_not_materialize_large_table_iterables(tmp_path: Path):
    ws = _make_workspace(tmp_path)
    extractor = FoundationExtractor(ws, profile="iccd_full_v1")

    class OneShotRows:
        def __init__(self, rows):
            self.rows = rows
            self.iterated = False

        def __iter__(self):
            if self.iterated:
                raise AssertionError("large table iterable was consumed more than once")
            self.iterated = True
            yield from self.rows

    tables = {
        "run_stage_patch_maps": OneShotRows(
            [
                {
                    "stage_name": "place",
                    "patch_id": 0,
                    "category": "density",
                    "channel": "cell_density",
                    "provenance_id": "prov:map",
                }
            ]
        ),
        "run_stage_patch_features": OneShotRows(
            [
                {
                    "stage_name": "place",
                    "patch_id": 0,
                    "feature_availability_code": "available",
                    "provenance_id": "prov:feature",
                }
            ]
        ),
        "stage_deltas": OneShotRows(
            [
                {
                    "to_stage": "place",
                    "entity_type": "patch",
                    "entity_key": "patch:0",
                    "metric_name": "available_from",
                    "provenance_id": "prov:delta",
                }
            ]
        ),
        "semantic_blocks": OneShotRows(
            [
                {
                    "stage_name": "place",
                    "entity_type": "patch",
                    "entity_key": "patch:0",
                    "block_name": "source_refs",
                    "source_doc": "vec_patches.md",
                    "preserved_reason": "test",
                }
            ]
        ),
    }

    provenance = extractor._provenance_rows(tables)

    assert {row["provenance_id"] for row in provenance} >= {
        "foundation_contract",
        "prov:map",
        "prov:feature",
        "prov:delta",
    }
    assert all(not isinstance(rows, list) for rows in tables.values())


def test_build_table_rows_reuses_dynamic_rows_for_provenance(tmp_path: Path, monkeypatch):
    ws = _make_workspace(tmp_path)
    extractor = FoundationExtractor(ws, profile="iccd_full_v1")
    extractor.extract(export_legacy_debug=True)
    flow = extractor._read_json(ws / "home" / "flow.json")
    parameters = extractor._read_json(ws / "home" / "parameters.json")
    stages = extractor._stage_infos(flow)
    canonical_grid = json.loads(
        (extractor.foundation_dir / "canonical_grid.json").read_text(encoding="utf-8")
    )
    canonical_maps = extractor._write_maps(
        extractor._collect_raw_maps(stages),
        canonical_grid,
        stages,
        extractor._collect_def_data(stages),
    )
    route_stage = next((stage for stage in stages if stage.name == "route"), None)
    labels = extractor._write_labels(
        parse_route_native_demand_capacity_artifacts(route_stage.directory, canonical_grid)[
            "labels"
        ],
        export_legacy_debug=True,
    )
    metrics = extractor._collect_metrics(stages)
    call_counts = {"maps": 0, "features": 0, "deltas": 0, "semantic": 0}

    original_maps = FoundationExtractor._patch_map_rows
    original_features = FoundationExtractor._patch_feature_rows
    original_deltas = FoundationExtractor._stage_delta_rows
    original_semantic = FoundationExtractor._semantic_block_rows

    def counted_maps(self, *args, **kwargs):
        call_counts["maps"] += 1
        return original_maps(*args, **kwargs)

    def counted_features(self, *args, **kwargs):
        call_counts["features"] += 1
        return original_features(self, *args, **kwargs)

    def counted_deltas(self, *args, **kwargs):
        call_counts["deltas"] += 1
        return original_deltas(self, *args, **kwargs)

    def counted_semantic(self, *args, **kwargs):
        call_counts["semantic"] += 1
        return original_semantic(self, *args, **kwargs)

    monkeypatch.setattr(FoundationExtractor, "_patch_map_rows", counted_maps)
    monkeypatch.setattr(FoundationExtractor, "_patch_feature_rows", counted_features)
    monkeypatch.setattr(FoundationExtractor, "_stage_delta_rows", counted_deltas)
    monkeypatch.setattr(FoundationExtractor, "_semantic_block_rows", counted_semantic)

    table_rows = extractor._build_table_rows(
        flow=flow,
        parameters=parameters,
        stages=stages,
        canonical_grid=canonical_grid,
        canonical_maps=canonical_maps,
        labels=labels,
        metrics=metrics,
    )

    assert call_counts == {"maps": 1, "features": 1, "deltas": 1, "semantic": 1}
    assert table_rows["provenance"]
    assert isinstance(table_rows["run_stage_patch_maps"], list)
    assert isinstance(table_rows["run_stage_patch_features"], list)
    assert isinstance(table_rows["stage_deltas"], list)
    assert isinstance(table_rows["semantic_blocks"], list)


def test_route_native_demand_capacity_jsonl_is_read_streaming(tmp_path: Path, monkeypatch):
    from chipcompiler.data.foundation.parsers import route_native_demand_capacity as parser

    ws = _make_workspace(tmp_path)
    path = (
        ws
        / "route_ecc"
        / "data"
        / "rt"
        / "space_router"
        / "route_native_demand_capacity_final.jsonl"
    )

    original_read_text = Path.read_text
    original_iter_jsonl_records = parser._iter_jsonl_records
    consumed = {"count": 0}

    def fail_target_read_text(self, *args, **kwargs):
        if self == path:
            raise AssertionError(
                "JSONL route demand/capacity input should be streamed line by line"
            )
        return original_read_text(self, *args, **kwargs)

    def one_shot_records(jsonl_path):
        assert jsonl_path == path
        for record in original_iter_jsonl_records(jsonl_path):
            consumed["count"] += 1
            yield record

    monkeypatch.setattr(Path, "read_text", fail_target_read_text)
    monkeypatch.setattr(parser, "_iter_jsonl_records", one_shot_records)

    canonical_grid = {
        "patches": [
            {
                "patch_id": 0,
                "row": 0,
                "col": 0,
                "bbox": {"llx": 0, "lly": 0, "urx": 100, "ury": 100},
            },
            {
                "patch_id": 1,
                "row": 0,
                "col": 1,
                "bbox": {"llx": 100, "lly": 0, "urx": 200, "ury": 100},
            },
            {
                "patch_id": 2,
                "row": 1,
                "col": 0,
                "bbox": {"llx": 0, "lly": 100, "urx": 100, "ury": 200},
            },
            {
                "patch_id": 3,
                "row": 1,
                "col": 1,
                "bbox": {"llx": 100, "lly": 100, "urx": 200, "ury": 200},
            },
        ]
    }

    records = parser._iter_records(path)
    assert not isinstance(records, list)
    labels = parser._labels_from_records(records, canonical_grid, path)

    assert consumed["count"] == 4
    assert labels[0]["horizontal_demand_capacity"] == 3.0
    assert labels[0]["vertical_demand_capacity"] == 2.0
    assert labels[0]["union_demand_capacity"] == 3.0


def test_def_parser_streams_large_def_without_read_text_splitlines(tmp_path: Path, monkeypatch):
    path = tmp_path / "large.def.gz"
    net_lines = []
    for idx in range(1005):
        y = idx % 200
        net_lines.append(f"- n{idx} ( U1 A ) ( PIN OUT )")
        net_lines.append(f"  + ROUTED MET2 ( 0 {y} ) ( 200 * )")
        net_lines.append("  ;")
    payload = "\n".join(
        [
            "VERSION 5.8 ;",
            'DIVIDERCHAR "/" ;',
            'BUSBITCHARS "[]" ;',
            "DESIGN gcd ;",
            "UNITS DISTANCE MICRONS 1000 ;",
            "DIEAREA ( 0 0 ) ( 200 200 ) ;",
            "TRACKS Y 50 DO 1 STEP 100 LAYER MET2 ;",
            "GCELLGRID X 0 DO 3 STEP 100 ;",
            "GCELLGRID Y 0 DO 3 STEP 100 ;",
            "COMPONENTS 1 ;",
            "- U1 NAND2 + PLACED ( 10 20 ) N ;",
            "END COMPONENTS",
            "PINS 1 ;",
            "- OUT + NET n0 + DIRECTION OUTPUT + PLACED ( 180 50 ) N ;",
            "END PINS",
            "NETS 1005 ;",
            *net_lines,
            "END NETS",
            "END DESIGN",
        ]
    )
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(payload)

    original_read_text = Path.read_text
    original_gzip_open = gzip.open

    def fail_target_read_text(self, *args, **kwargs):
        if self == path:
            raise AssertionError("DEF parser should not use Path.read_text for target DEF")
        return original_read_text(self, *args, **kwargs)

    class NoReadAll:
        def __init__(self, handle):
            self._handle = handle

        def __enter__(self):
            self._handle.__enter__()
            return self

        def __exit__(self, *args):
            return self._handle.__exit__(*args)

        def __iter__(self):
            return iter(self._handle)

        def read(self, *args, **kwargs):
            raise AssertionError("DEF parser should stream gzip lines instead of read() all")

    def guarded_gzip_open(*args, **kwargs):
        handle = original_gzip_open(*args, **kwargs)
        if args and Path(args[0]) == path:
            return NoReadAll(handle)
        return handle

    monkeypatch.setattr(Path, "read_text", fail_target_read_text)
    monkeypatch.setattr(gzip, "open", guarded_gzip_open)

    parsed = parse_def(path)

    assert len(parsed.components) == 1
    assert len(parsed.pins) == 1
    assert len(parsed.nets) == 1005
    assert sum(len(net.wires) for net in parsed.nets) == 1005


def test_extractor_jsonl_helper_streams_records(tmp_path: Path, monkeypatch):
    path = tmp_path / "records.jsonl"
    _write_text(path, json.dumps({"a": 1}) + "\n" + json.dumps({"a": 2}) + "\n")

    original_read_text = Path.read_text

    def fail_target_read_text(self, *args, **kwargs):
        if self == path:
            raise AssertionError("extractor JSONL helper should stream line by line")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_target_read_text)

    assert list(extractor_module._iter_jsonl_records(path)) == [{"a": 1}, {"a": 2}]
    assert extractor_module._read_jsonl_records(path) == [{"a": 1}, {"a": 2}]


def test_extractor_fails_when_available_tech_sources_materialize_empty_tables(
    tmp_path: Path, monkeypatch
):
    ws = _make_workspace(tmp_path)

    monkeypatch.setattr(FoundationExtractor, "_tech_layer_rows", lambda self, design_id: iter(()))
    monkeypatch.setattr(FoundationExtractor, "_tech_via_rows", lambda self, design_id: iter(()))
    monkeypatch.setattr(FoundationExtractor, "_library_cell_rows", lambda self, design_id: iter(()))

    with pytest.raises(RuntimeError, match="tech_layers.*source_available.*row_count=0"):
        FoundationExtractor(ws, profile="iccd_full_v1").extract()

    quality = json.loads(
        (ws / "foundation_data" / "ecc" / "quality.json").read_text(encoding="utf-8")
    )
    assert quality["tech"]["materialization_counts"] == {
        "tech_layers": 0,
        "tech_vias": 0,
        "library_cells": 0,
    }
    assert any("tech_layers" in warning for warning in quality["warnings"])
    assert not (ws / "foundation_data" / "ecc" / "manifest.json").exists()


def test_extractor_records_tech_materialization_counts(tmp_path: Path):
    ws = _make_workspace(tmp_path)

    result = FoundationExtractor(ws, profile="iccd_full_v1").extract()
    quality = json.loads((result.foundation_dir / "quality.json").read_text(encoding="utf-8"))

    assert quality["tech"]["materialization_counts"] == {
        "tech_layers": quality["tables"]["tech_layers"]["row_count"],
        "tech_vias": quality["tables"]["tech_vias"]["row_count"],
        "library_cells": quality["tables"]["library_cells"]["row_count"],
    }
    assert quality["tech"]["source_counts"]["record_layers"] > 0
    assert quality["tech"]["source_counts"]["record_vias"] > 0
    assert quality["tech"]["source_counts"]["record_cells"] > 0


def test_default_contract_tech_tables_do_not_depend_on_legacy_vector_json(
    tmp_path: Path, monkeypatch
):
    import pyarrow.parquet as pq

    ws = _make_workspace(tmp_path)
    original_read_json_records = extractor_module._read_json_records

    def fail_if_legacy_tech_json(path: Path):
        normalized = path.as_posix()
        if (
            normalized.endswith("vectors/tech/layers.json")
            or normalized.endswith("vectors/tech/cells.json")
            or normalized.endswith("vectors/tech/vias.json")
        ):
            raise AssertionError(f"legacy tech json should not be read: {normalized}")
        return original_read_json_records(path)

    monkeypatch.setattr(extractor_module, "_read_json_records", fail_if_legacy_tech_json)

    result = FoundationExtractor(ws, profile="iccd_full_v1").extract()
    foundation_dir = result.foundation_dir
    schema = json.loads((foundation_dir / "schema.json").read_text(encoding="utf-8"))

    assert not (foundation_dir / "vectors").exists()

    def read_rows(name: str) -> list[dict[str, object]]:
        return pq.read_table(foundation_dir / schema["tables"][name]["path"]).to_pylist()

    assert read_rows("tech_layers")
    assert read_rows("tech_vias")
    assert read_rows("library_cells")


def test_iccd_full_v1_extractor_writes_full_contract(tmp_path: Path):
    ws = _make_workspace(tmp_path)

    result = FoundationExtractor(ws, profile="iccd_full_v1").extract(export_legacy_debug=True)

    foundation_dir = ws / "foundation_data" / "ecc"
    assert result.foundation_dir == foundation_dir
    for rel in [
        "manifest.json",
        "summary.json",
        "stage_index.json",
        "quality.json",
        "canonical_grid.json",
        "views/ml/dataset_index.json",
        "views/agent/run_summary.json",
        "labels/route_native_demand_capacity.jsonl",
        "vectors/instances/place.jsonl",
        "vectors/tech/layers.json",
        "vectors/tech/cells.json",
        "vectors/tech/vias.json",
        "vectors/nets/route.jsonl",
        "vectors/pins/route.jsonl",
        "vectors/wires/route.jsonl",
        "vectors/routing_graphs/route.jsonl",
        "vectors/timing_paths/route.jsonl",
        "vectors/patches/place.jsonl",
        "maps/place/density.json",
        "maps/place/congestion.json",
    ]:
        assert (foundation_dir / rel).exists(), rel
    assert not (foundation_dir / "maps" / "place" / "egr_overflow.json").exists()

    summary = json.loads((foundation_dir / "summary.json").read_text(encoding="utf-8"))
    assert "profile" not in summary
    assert "created_at" not in summary
    assert "stages" not in summary
    assert all("info" not in step for step in summary["flow"]["steps"])
    assert "Die" not in summary["parameters"]
    assert summary["parameters"]["Core"] == {
        "Utilitization": 0.5,
        "Margin": [2, 2],
        "Aspect ratio": 1,
    }
    assert "PDK Root" not in summary["parameters"]
    control_knobs = summary["parameters"]["control_knobs"]
    assert control_knobs["source"] == "effective_tool_flow_configs"
    assert "base" not in control_knobs
    assert "stage_configs" not in control_knobs
    assert "database_inputs" not in control_knobs
    assert "drc" not in control_knobs
    assert "pnp" not in control_knobs
    assert set(control_knobs) == {"source", "floorplan", "dreamplace", "route"}
    assert control_knobs["floorplan"] == {"tap_distance": 58}
    assert control_knobs["dreamplace"]["num_bins_x"] == 32
    assert control_knobs["dreamplace"]["global_place_stages"][0]["iteration"] == 3000
    assert "target_density" not in control_knobs["dreamplace"]
    assert control_knobs["route"] == {"thread_number": "50", "enable_timing": "0"}
    assert "Max fanout" in summary["parameters"]
    assert "Target density" in summary["parameters"]
    assert "Top layer" in summary["parameters"]
    metrics = summary["metrics"]
    assert metrics["route"]["wire_count"] > 0
    assert metrics["route"]["wire_length"] > 0
    assert metrics["route"]["route_via_count"] > 0
    assert "route_patch_overflow_count" not in metrics["route"]
    assert "features" not in metrics["route"]
    assert "route.step.json" not in metrics["route"]
    assert all(
        all("path" not in key.lower() for key in stage_metrics)
        for stage_metrics in metrics.values()
    )

    manifest = json.loads((foundation_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["contract_name"] == "foundation_data/ecc"
    assert manifest["storage_format"] == "parquet+json_views"
    assert "tables" in manifest
    assert "version" not in manifest
    assert "profile" not in manifest
    assert manifest["created_at"]
    assert manifest["generated_by"]["profile"] == "iccd_full_v1"
    assert manifest["workspace"] == str(ws.resolve())
    assert isinstance(manifest["sources"], list)
    assert "home/flow.json" in manifest["sources"]
    assert "place_dreamplace/analysis/place_metrics.json" in manifest["sources"]
    assert all(not Path(source).is_absolute() for source in manifest["sources"])
    assert all(isinstance(source, str) for source in manifest["sources"])
    assert manifest["artifacts"] == {
        "summary": "foundation_data/ecc/summary.json",
        "stage_index": "foundation_data/ecc/stage_index.json",
        "canonical_grid": "foundation_data/ecc/canonical_grid.json",
        "quality": "foundation_data/ecc/quality.json",
        "schema": "foundation_data/ecc/schema.json",
        "ml_view": "foundation_data/ecc/views/ml/dataset_index.json",
        "agent_view": "foundation_data/ecc/views/agent/run_summary.json",
        "raw_refs": "foundation_data/ecc/raw_refs/artifacts.json",
    }

    grid = json.loads((foundation_dir / "canonical_grid.json").read_text(encoding="utf-8"))

    assert grid["rows"] == 2
    assert grid["cols"] == 2
    assert grid["grid_source"] == "irt_gcell_info"
    assert len(grid["patches"]) == 4
    assert grid["patches"][0]["bbox"] == {"llx": 0.0, "lly": 0.0, "urx": 120.0, "ury": 80.0}
    assert grid["patches"][0]["row"] == 0
    assert grid["patches"][0]["col"] == 0
    assert "gcell" not in grid["patches"][0]

    place_congestion = json.loads(
        (foundation_dir / "maps" / "place" / "congestion.json").read_text()
    )
    assert place_congestion["category"] == "congestion"
    assert [item["value"] for item in place_congestion["maps"]["horizontal"]["values"]] == [
        1.0,
        3.0,
        3.0,
        -4.0,
    ]
    assert [item["value"] for item in place_congestion["maps"]["vertical"]["values"]] == [
        3.0,
        -3.0,
        -1.0,
        7.0,
    ]
    assert [item["value"] for item in place_congestion["maps"]["union"]["values"]] == [
        3.0,
        3.0,
        3.0,
        7.0,
    ]

    indexed_density = json.loads((foundation_dir / "maps" / "place" / "density.json").read_text())
    assert "place_allcell_density" not in indexed_density["maps"]
    assert [item["value"] for item in indexed_density["maps"]["allcell_density"]["values"]] == [
        10.0,
        11.0,
        12.0,
        13.0,
    ]
    assert [item["value"] for item in indexed_density["maps"]["allcell_pin_density"]["values"]] == [
        20.0,
        21.0,
        22.0,
        23.0,
    ]
    assert [item["value"] for item in indexed_density["maps"]["allnet_density"]["values"]] == [
        30.0,
        31.0,
        32.0,
        33.0,
    ]

    indexed_margin = json.loads((foundation_dir / "maps" / "place" / "margin.json").read_text())
    assert [item["value"] for item in indexed_margin["maps"]["union"]["values"]] == [
        40.0,
        41.0,
        42.0,
        43.0,
    ]

    indexed_rudy = json.loads((foundation_dir / "maps" / "place" / "rudy.json").read_text())
    assert [item["value"] for item in indexed_rudy["maps"]["rudy_union"]["values"]] == [
        50.0,
        51.0,
        52.0,
        53.0,
    ]
    assert all("lut" not in key for key in indexed_rudy["maps"])
    assert not (foundation_dir / "maps" / "place" / "ignored.json").exists()
    assert not (foundation_dir / "maps" / "canonical").exists()
    assert not (foundation_dir / "maps" / "raw").exists()

    instances = [
        json.loads(line)
        for line in (foundation_dir / "vectors" / "instances" / "place.jsonl")
        .read_text()
        .splitlines()
    ]
    assert {item["name"] for item in instances} == {"Instance_U1", "Macro_SRAM0"}
    assert all("availability" not in item for item in instances)
    assert all("availability" not in item for item in instances)
    assert any(item["identity"]["is_macro"] for item in instances)
    assert all("is_macro" not in item for item in instances)

    assert not (foundation_dir / "labels" / "route_patch_overflow.jsonl").exists()
    assert not (foundation_dir / "labels" / "route_hotspot_top5.jsonl").exists()
    assert not (foundation_dir / "labels" / "candidate_qor_summary.json").exists()
    assert not (foundation_dir / "labels" / "route_reconstructed_congestion.jsonl").exists()
    assert not (foundation_dir / "labels" / "route_reconstructed_demand_capacity.jsonl").exists()

    native_demand_capacity = [
        json.loads(line)
        for line in (foundation_dir / "labels" / "route_native_demand_capacity.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert {item["source"] for item in native_demand_capacity} == {"irt_space_router_native"}
    assert native_demand_capacity[0]["horizontal_demand"] == 6.0
    assert native_demand_capacity[0]["horizontal_capacity"] == 3.0
    assert native_demand_capacity[0]["horizontal_demand_capacity"] == 3.0
    assert native_demand_capacity[0]["vertical_demand_capacity"] == 2.0
    assert native_demand_capacity[0]["union_demand_capacity"] == 3.0
    assert native_demand_capacity[1]["vertical_demand_capacity"] == 5.0
    assert native_demand_capacity[2]["union_demand_capacity"] == 0.0

    nets = [
        json.loads(line)
        for line in (foundation_dir / "vectors" / "nets" / "route.jsonl").read_text().splitlines()
    ]
    pins = [
        json.loads(line)
        for line in (foundation_dir / "vectors" / "pins" / "route.jsonl").read_text().splitlines()
    ]
    wires = [
        json.loads(line)
        for line in (foundation_dir / "vectors" / "wires" / "route.jsonl").read_text().splitlines()
    ]
    timing_paths = [
        json.loads(line)
        for line in (foundation_dir / "vectors" / "timing_paths" / "route.jsonl")
        .read_text()
        .splitlines()
    ]
    assert nets[0]["name"] == "n1"
    assert all("availability" not in item for item in [*nets, *pins, *wires, *timing_paths])
    assert any(pin["identity"]["pin_name"] == "OUT" for pin in pins)
    assert any(
        wire["geometry"]["layer"] == "MET2" and wire["geometry"]["direction"] == "horizontal"
        for wire in wires
    )
    assert timing_paths
    timing_path = timing_paths[0]
    assert list(timing_path) == [
        "id",
        "stage",
        "path_key",
        "source",
        "identity",
        "analysis_context",
        "endpoints",
        "path_timing",
        "path_electrical",
        "path_points",
        "timing_edges",
        "wire_path_nodes",
        "path_spatial",
        "progressive_metadata",
        "coverage",
        "source_refs",
        "null_reason",
    ]
    assert timing_path["path_timing"]["slack"] == 1.0
    assert timing_path["path_timing"]["rank_in_stage"] == 0
    assert timing_path["path_timing"]["is_worst_path"] is True
    assert timing_path["path_timing"]["is_near_critical"] is True
    assert timing_path["path_timing"]["normalized_criticality"] is None
    assert (
        timing_path["null_reason"]["path_timing"]["normalized_criticality"]
        == "constant_slack_range"
    )
    assert timing_path["path_points"][0]["raw_name"] == "U1/A"
    assert timing_path["path_points"][0]["pin_key"] == "U1:A"
    assert timing_path["timing_edges"][0]["edge_kind"] == "cell_arc"
    assert timing_path["timing_edges"][0]["net_key"] is None
    assert timing_path["path_electrical"]["capacitance_sum"] == 0.5
    assert timing_path["path_electrical"]["max_slew"] == 0.6
    assert timing_path["path_electrical"]["resistance_sum"] == 1.5
    assert timing_path["wire_path_nodes"][0]["pin_key"] == "U1:A"
    assert timing_path["coverage"]["has_wire_path"] is True
    assert (
        timing_path["path_spatial"]["anchor_source_policy"]
        == "prefer_pin_geometry_fallback_parent_instance"
    )

    patches = [
        json.loads(line)
        for line in (foundation_dir / "vectors" / "patches" / "route.jsonl")
        .read_text()
        .splitlines()
    ]
    patch0 = patches[0]
    assert list(patch0) == [
        "id",
        "stage",
        "patch_key",
        "source",
        "identity",
        "geometry",
        "local_density",
        "local_connectivity",
        "pre_route_estimators",
        "neighbor_context",
        "entity_refs",
        "timing_context",
        "electrical_context",
        "route_oracle",
        "label_refs",
        "drc_context",
        "progressive_metadata",
        "source_refs",
        "null_reason",
    ]
    assert "bbox" not in patch0
    assert "availability" not in patch0
    assert "route_true_overflow" not in patch0
    assert "route_reconstructed_congestion" not in patch0
    assert "route_native_demand_capacity" not in patch0
    assert "route_reconstructed_demand_capacity" not in patch0
    assert "route_demand_capacity" not in patch0
    assert "timing" not in patch0
    assert "electrical" not in patch0
    assert patch0["entity_refs"]["net_count"] >= 1
    assert patch0["route_oracle"]["wire_length_by_layer"]["MET2"] > 0
    native = patch0["route_oracle"]["native_demand_capacity"]
    assert native["horizontal_demand"] == 6.0
    assert native["horizontal_capacity"] == 3.0
    assert native["horizontal_demand_capacity"] == 3.0
    assert native["vertical_demand_capacity"] == 2.0
    assert native["union_demand_capacity"] == 3.0
    assert "horizontal_overflow" not in native
    assert "vertical_overflow" not in native
    assert "union_overflow" not in native
    assert native["union_utilization"] == 2.0
    assert native["tightness_class"] == "over_capacity"
    assert patch0["route_oracle"]["feature_role"] == "route_only_oracle"
    assert patch0["route_oracle"]["available_for_training_input"] is False
    assert patch0["timing_context"]["worst_slack_min"] == 1.0
    assert patch0["electrical_context"]["capacitance_sum"] == 0.5
    assert patch0["electrical_context"]["max_slew"] == 0.6

    drc_patches = [
        json.loads(line)
        for line in (foundation_dir / "vectors" / "patches" / "drc.jsonl").read_text().splitlines()
    ]
    assert drc_patches[0]["drc_context"]["count"] == 2
    assert drc_patches[0]["drc_context"]["by_type"] == {"short": 2}
    assert drc_patches[-1]["drc_context"]["count"] == 1

    quality = json.loads((foundation_dir / "quality.json").read_text(encoding="utf-8"))
    assert "profile" not in quality
    assert quality["availability"]["instances"]["place"] == "available"
    assert quality["availability"]["labels"]["route_native_demand_capacity"] == "available"
    assert "route_reconstructed_demand_capacity" not in quality["availability"]["labels"]
    assert "route_reconstructed_congestion" not in quality["availability"]["labels"]
    assert "route_patch_overflow" not in quality["availability"]["labels"]
    assert quality["availability"]["drc"]["drc"] == "available"
    assert quality["availability"]["timing_paths"]["route"] == "available"
    assert "null_reason" in quality
    assert "route_reconstructed_congestion_count" not in summary["labels"]
    assert "route_reconstructed_demand_capacity_count" not in summary["labels"]


def test_iccd_full_v1_extractor_records_base_delta_scope_sources(tmp_path: Path, monkeypatch):
    written_tables: list[str] = []
    original_write_parquet = table_contract_module.write_parquet

    def recording_write_parquet(path: Path, records, *, columns=None, schema=None, batch_size=2048):
        written_tables.append(path.stem)
        return original_write_parquet(
            path, records, columns=columns, schema=schema, batch_size=batch_size
        )

    monkeypatch.setattr(table_contract_module, "write_parquet", recording_write_parquet)

    base_manifest = (
        tmp_path / "design_base" / "bench" / "design" / "foundation_data" / "ecc" / "manifest.json"
    )
    base_manifest.parent.mkdir(parents=True)
    static_tables = {
        "designs",
        "tech_layers",
        "tech_vias",
        "library_cells",
        "patches",
        "patch_neighbors",
    }
    base_manifest.write_text(
        json.dumps(
            {
                "tables": {
                    name: {
                        "path": "tables/patches.parquet",
                        "format": "parquet",
                        "row_count": 4,
                        "sha256": "0" * 64,
                        "size_bytes": 123,
                    }
                    for name in static_tables
                }
            }
        ),
        encoding="utf-8",
    )
    ws = _make_workspace(tmp_path)
    result = FoundationExtractor(ws, profile="iccd_full_v1").extract(
        scope="variant_delta",
        base_manifest_path=str(base_manifest),
    )

    manifest = json.loads((result.foundation_dir / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["storage_layout"] == "base_delta_v1"
    assert manifest["base_manifest_path"] == str(base_manifest)
    assert manifest["tables"]["patches"]["sources"] == [
        {"root": "design_base", "path": "tables/patches.parquet"}
    ]
    assert manifest["tables"]["patches"]["sha256"] == "0" * 64
    assert not (result.foundation_dir / "tables" / "patches.parquet").exists()
    assert manifest["tables"]["run_patch_route_labels"]["sources"] == [
        {"root": "variant_delta", "path": "tables/run_patch_route_labels.parquet"}
    ]
    assert not (static_tables & set(written_tables))


def test_variant_delta_does_not_construct_skipped_static_rows(tmp_path: Path, monkeypatch):
    base_manifest = (
        tmp_path / "design_base" / "bench" / "design" / "foundation_data" / "ecc" / "manifest.json"
    )
    base_manifest.parent.mkdir(parents=True)
    static_tables = {
        "designs",
        "tech_layers",
        "tech_vias",
        "library_cells",
        "patches",
        "patch_neighbors",
    }
    base_manifest.write_text(
        json.dumps(
            {
                "tables": {
                    name: {
                        "path": f"tables/{name}.parquet",
                        "format": "parquet",
                        "row_count": 4,
                        "sha256": "0" * 64,
                        "size_bytes": 123,
                    }
                    for name in static_tables
                }
            }
        ),
        encoding="utf-8",
    )
    ws = _make_workspace(tmp_path)

    def fail_static_builder(*args, **kwargs):
        raise AssertionError("variant_delta should not construct skipped static table rows")

    monkeypatch.setattr(FoundationExtractor, "_patch_table_rows", fail_static_builder)
    monkeypatch.setattr(FoundationExtractor, "_patch_neighbor_rows", fail_static_builder)
    monkeypatch.setattr(FoundationExtractor, "_tech_layer_rows", fail_static_builder)
    monkeypatch.setattr(FoundationExtractor, "_tech_via_rows", fail_static_builder)
    monkeypatch.setattr(FoundationExtractor, "_library_cell_rows", fail_static_builder)

    result = FoundationExtractor(ws, profile="iccd_full_v1").extract(
        scope="variant_delta",
        base_manifest_path=str(base_manifest),
    )

    manifest = json.loads((result.foundation_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["tables"]["patches"]["sources"] == [
        {"root": "design_base", "path": "tables/patches.parquet"}
    ]


def test_iccd_full_v1_variant_delta_requires_static_tables_in_base_manifest(tmp_path: Path):
    base_manifest = tmp_path / "design_base" / "foundation_data" / "ecc" / "manifest.json"
    base_manifest.parent.mkdir(parents=True)
    base_manifest.write_text(
        json.dumps({"tables": {"designs": {"path": "tables/designs.parquet"}}}), encoding="utf-8"
    )
    ws = _make_workspace(tmp_path)

    with pytest.raises(ValueError, match="base manifest missing static foundation tables"):
        FoundationExtractor(ws, profile="iccd_full_v1").extract(
            scope="variant_delta",
            base_manifest_path=str(base_manifest),
        )


def test_iccd_full_v1_design_id_is_stable_across_variant_parameters(tmp_path: Path):
    ws_a = _make_workspace(tmp_path / "a")
    ws_b = _make_workspace(tmp_path / "b")
    params_b = json.loads((ws_b / "home" / "parameters.json").read_text(encoding="utf-8"))
    params_b["Target density"] = 0.66
    params_b["Target overflow"] = 0.06
    params_b["Cell padding x"] = 800
    (ws_b / "home" / "parameters.json").write_text(json.dumps(params_b), encoding="utf-8")
    flow_b = json.loads((ws_b / "home" / "flow.json").read_text(encoding="utf-8"))
    flow_b["steps"][1]["runtime"] = "0:0:42"
    (ws_b / "home" / "flow.json").write_text(json.dumps(flow_b), encoding="utf-8")

    result_a = FoundationExtractor(ws_a, profile="iccd_full_v1").extract()
    result_b = FoundationExtractor(ws_b, profile="iccd_full_v1").extract()

    manifest_a = json.loads((result_a.foundation_dir / "manifest.json").read_text(encoding="utf-8"))
    manifest_b = json.loads((result_b.foundation_dir / "manifest.json").read_text(encoding="utf-8"))

    assert manifest_a["design_id"] == manifest_b["design_id"]
    assert manifest_a["run_id"] != manifest_b["run_id"]


def test_iccd_full_v1_orders_instance_record_fields_like_documented_schema(tmp_path: Path):
    ws = _make_workspace(tmp_path)

    FoundationExtractor(ws, profile="iccd_full_v1").extract(
        export_legacy_debug=True, stages=["place"]
    )

    row = json.loads(
        (ws / "foundation_data" / "ecc" / "vectors" / "instances" / "place.jsonl")
        .read_text()
        .splitlines()[0]
    )
    assert list(row) == [
        "id",
        "stage",
        "name",
        "source",
        "identity",
        "physical_state",
        "connectivity_summary",
        "patch_anchor",
        "progressive_metadata",
        "clock_tree",
        "route_analysis",
        "null_reason",
    ]


def test_iccd_full_v1_timing_criticality_is_scoped_by_analysis_context(tmp_path: Path):
    ws = _make_workspace(tmp_path)
    _write_json(
        ws / "route_ecc" / "data" / "sta" / "gcd.rpt.json",
        {
            "summary": [
                {
                    "endpoint": "U1/Y",
                    "clock_group": "clk",
                    "delay_type": "max",
                    "path_delay": "1.0",
                    "path_required": "2.0",
                    "slack": "1.0",
                },
                {
                    "endpoint": "U1/Y",
                    "clock_group": "clk",
                    "delay_type": "max",
                    "path_delay": "0.5",
                    "path_required": "2.5",
                    "slack": "2.0",
                },
                {
                    "endpoint": "U1/Y",
                    "clock_group": "clk",
                    "delay_type": "min",
                    "path_delay": "0.4",
                    "path_required": "0.3",
                    "slack": "-0.1",
                },
                {
                    "endpoint": "U1/Y",
                    "clock_group": "clk",
                    "delay_type": "min",
                    "path_delay": "0.2",
                    "path_required": "0.3",
                    "slack": "0.1",
                },
            ],
            "detail": [
                {
                    "start_point": "U1/A",
                    "end_point": "U1/Y",
                    "type": "max",
                    "detail": [
                        {"name": "U1/A", "incr_delay": "0.0", "path_delay": "0.0 r"},
                        {"name": "U1/Y", "incr_delay": "1.0", "path_delay": "1.0 r"},
                    ],
                },
                {
                    "start_point": "U1/A",
                    "end_point": "U1/Y",
                    "type": "max",
                    "detail": [
                        {"name": "U1/A", "incr_delay": "0.0", "path_delay": "0.0 r"},
                        {"name": "U1/Y", "incr_delay": "0.5", "path_delay": "0.5 r"},
                    ],
                },
                {
                    "start_point": "U1/A",
                    "end_point": "U1/Y",
                    "type": "min",
                    "detail": [
                        {"name": "U1/A", "incr_delay": "0.0", "path_delay": "0.0 r"},
                        {"name": "U1/Y", "incr_delay": "0.4", "path_delay": "0.4 r"},
                    ],
                },
                {
                    "start_point": "U1/A",
                    "end_point": "U1/Y",
                    "type": "min",
                    "detail": [
                        {"name": "U1/A", "incr_delay": "0.0", "path_delay": "0.0 r"},
                        {"name": "U1/Y", "incr_delay": "0.2", "path_delay": "0.2 r"},
                    ],
                },
            ],
            "slack": [
                {"clock": "clk", "delay_type": "max", "TNS": "0.0", "WNS": "1.0"},
                {"clock": "clk", "delay_type": "min", "TNS": "-0.1", "WNS": "-0.1"},
            ],
        },
    )
    for idx in range(1, 5):
        _write_json(
            ws / "route_ecc" / "data" / "sta" / "wire_paths" / f"wire_path_{idx}.json",
            [
                {
                    "node_0": {
                        "Point": "U1/A",
                        "Capacitance": 0.1,
                        "slew": 0.2,
                        "trans_type": "rise",
                    }
                },
                {"net_arc_0": {"Incr": 0.3, "Resistance": 1.5}},
                {
                    "node_1": {
                        "Point": "U1/Y",
                        "Capacitance": 0.4,
                        "slew": 0.6,
                        "trans_type": "fall",
                    }
                },
            ],
        )

    FoundationExtractor(ws, profile="iccd_full_v1").extract(
        export_legacy_debug=True, stages=["route"]
    )

    records = [
        json.loads(line)
        for line in (ws / "foundation_data" / "ecc" / "vectors" / "timing_paths" / "route.jsonl")
        .read_text()
        .splitlines()
    ]
    assert [record["path_timing"]["is_worst_path"] for record in records] == [
        True,
        False,
        True,
        False,
    ]
    assert [record["path_timing"]["normalized_criticality"] for record in records] == [
        1.0,
        0.0,
        1.0,
        0.0,
    ]
    assert [record["path_timing"]["is_near_critical"] for record in records] == [
        True,
        False,
        True,
        False,
    ]


def test_iccd_full_v1_timing_paths_use_semantic_nulls_for_missing_spatial_maps(tmp_path: Path):
    ws = _make_workspace(tmp_path, include_route_maps=False)

    FoundationExtractor(ws, profile="iccd_full_v1").extract(
        export_legacy_debug=True, stages=["route"]
    )

    record = json.loads(
        (ws / "foundation_data" / "ecc" / "vectors" / "timing_paths" / "route.jsonl")
        .read_text()
        .splitlines()[0]
    )
    assert record["path_spatial"]["patch_count"] > 0
    assert all(
        summary["count"] == 0 for summary in record["path_spatial"]["stage_map_summary"].values()
    )
    assert record["null_reason"]["path_spatial"]["stage_map_summary"] == "missing_stage_maps"


def test_iccd_full_v1_timing_paths_mark_missing_spatial_anchors_semantically(tmp_path: Path):
    ws = _make_workspace(tmp_path)
    _write_text(
        ws / "Floorplan_ecc" / "output" / "gcd_Floorplan.def",
        """
VERSION 5.8 ;
DIVIDERCHAR "/" ;
BUSBITCHARS "[]" ;
DESIGN gcd ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 200 200 ) ;
COMPONENTS 1 ;
- U1 NAND2 ;
END COMPONENTS
NETS 1 ;
- n1 ( U1 A ) ( U1 Y ) ;
END NETS
END DESIGN
""".strip()
        + "\n",
    )
    _write_json(
        ws / "Floorplan_ecc" / "output" / "gcd_Floorplan.json",
        {
            "design name": "gcd",
            "diearea": {"path": [[0, 0], [200, 0], [200, 200], [0, 200], [0, 0]]},
            "layerInfo": [{"id": 0, "layername": "cell"}],
            "data": [
                {
                    "type": "group",
                    "struct name": "Instance_U1",
                    "children": [
                        {
                            "type": "box",
                            "layer": 0,
                            "path": [[0, 0], [0, 0], [0, 0], [0, 0], [0, 0]],
                        }
                    ],
                }
            ],
        },
    )
    _write_json(
        ws / "Floorplan_ecc" / "data" / "sta" / "gcd.rpt.json",
        {
            "summary": [
                {
                    "endpoint": "U1/Y",
                    "clock_group": "clk",
                    "delay_type": "max",
                    "path_delay": "1.0",
                    "path_required": "2.0",
                    "slack": "1.0",
                }
            ],
            "detail": [
                {
                    "start_point": "U1/A",
                    "end_point": "U1/Y",
                    "type": "max",
                    "detail": [
                        {"name": "U1/A", "incr_delay": "0.0", "path_delay": "0.0 r"},
                        {"name": "U1/Y", "incr_delay": "1.0", "path_delay": "1.0 r"},
                    ],
                }
            ],
            "slack": [{"clock": "clk", "delay_type": "max", "TNS": "0.0", "WNS": "1.0"}],
        },
    )
    _write_json(
        ws / "Floorplan_ecc" / "data" / "sta" / "wire_paths" / "wire_path_1.json",
        [
            {"node_0": {"Point": "U1/A", "Capacitance": 0.1, "slew": 0.2, "trans_type": "rise"}},
            {"node_1": {"Point": "U1/Y", "Capacitance": 0.4, "slew": 0.6, "trans_type": "fall"}},
        ],
    )

    FoundationExtractor(ws, profile="iccd_full_v1").extract(
        export_legacy_debug=True, stages=["Floorplan"]
    )

    record = json.loads(
        (ws / "foundation_data" / "ecc" / "vectors" / "timing_paths" / "Floorplan.jsonl")
        .read_text()
        .splitlines()[0]
    )
    assert {point["spatial_anchor_source"] for point in record["path_points"]} == {"missing"}
    assert record["path_spatial"]["has_missing_spatial_anchor"] is True
    assert record["null_reason"]["path_spatial"]["spatial_anchor"] == "missing_spatial_anchor"


def test_iccd_full_v1_enriches_instances_from_def_components(tmp_path: Path):
    ws = _make_workspace(tmp_path)
    _write_text(
        ws / "place_dreamplace" / "output" / "gcd_place.def",
        """
VERSION 5.8 ;
DIVIDERCHAR "/" ;
BUSBITCHARS "[]" ;
DESIGN gcd ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 200 200 ) ;
COMPONENTS 2 ;
- U1 DFFHQNX1H7L + PLACED ( 10 20 ) N ;
- U2 BUFX1P4H7L + PLACED ( 50 60 ) FS ;
END COMPONENTS
NETS 1 ;
- clk ( U1 CK ) ( U2 A ) ;
END NETS
END DESIGN
""".strip()
        + "\n",
    )
    _write_json(
        ws / "place_dreamplace" / "output" / "gcd_place.json",
        {
            "design name": "gcd",
            "diearea": {"path": [[0, 0], [200, 0], [200, 200], [0, 200], [0, 0]]},
            "layerInfo": [{"id": 0, "layername": "cell"}],
            "data": [
                {
                    "type": "group",
                    "struct name": "Instance_U1",
                    "children": [
                        {
                            "type": "box",
                            "layer": 0,
                            "path": [[10, 20], [30, 20], [30, 40], [10, 40], [10, 20]],
                        }
                    ],
                },
                {
                    "type": "group",
                    "struct name": "Instance_U2",
                    "children": [
                        {
                            "type": "box",
                            "layer": 0,
                            "path": [[50, 60], [60, 60], [60, 70], [50, 70], [50, 60]],
                        }
                    ],
                },
            ],
        },
    )

    FoundationExtractor(ws, profile="iccd_full_v1").extract(
        export_legacy_debug=True, stages=["place"]
    )

    foundation_dir = ws / "foundation_data" / "ecc"
    instances = [
        json.loads(line)
        for line in (foundation_dir / "vectors" / "instances" / "place.jsonl")
        .read_text()
        .splitlines()
    ]
    first = instances[0]
    assert first["identity"]["instance_key"] == "U1"
    assert first["identity"]["master"] == "DFFHQNX1H7L"
    assert first["identity"]["cell_class"] == "sequential"
    assert first["physical_state"]["origin"] == {"x": 10.0, "y": 20.0}
    assert first["physical_state"]["orientation"] == "N"
    assert first["physical_state"]["placement_status"] == "placed"
    assert "master" not in first
    assert "orientation" not in first


def test_iccd_full_v1_uses_semantic_null_for_floorplan_unplaced_stdcells(tmp_path: Path):
    ws = _make_workspace(tmp_path)
    _write_text(
        ws / "Floorplan_ecc" / "output" / "gcd_Floorplan.def",
        """
VERSION 5.8 ;
DIVIDERCHAR "/" ;
BUSBITCHARS "[]" ;
DESIGN gcd ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 200 200 ) ;
COMPONENTS 1 ;
- U1 NAND2 ;
END COMPONENTS
NETS 1 ;
- n1 ( U1 A ) ;
END NETS
END DESIGN
""".strip()
        + "\n",
    )
    _write_json(
        ws / "Floorplan_ecc" / "output" / "gcd_Floorplan.json",
        {
            "design name": "gcd",
            "diearea": {"path": [[0, 0], [200, 0], [200, 200], [0, 200], [0, 0]]},
            "layerInfo": [{"id": 0, "layername": "cell"}],
            "data": [
                {
                    "type": "group",
                    "struct name": "Instance_U1",
                    "children": [
                        {
                            "type": "box",
                            "layer": 0,
                            "path": [[0, 0], [0, 0], [0, 0], [0, 0], [0, 0]],
                        }
                    ],
                }
            ],
        },
    )

    FoundationExtractor(ws, profile="iccd_full_v1").extract(
        export_legacy_debug=True, stages=["Floorplan"]
    )

    row = json.loads(
        (ws / "foundation_data" / "ecc" / "vectors" / "instances" / "Floorplan.jsonl").read_text()
    )
    assert row["physical_state"]["placement_status"] == "unplaced"
    assert row["physical_state"]["origin"] is None
    assert row["physical_state"]["bbox"] is None
    assert row["physical_state"]["center"] is None
    assert row["physical_state"]["area"] is None
    assert row["null_reason"]["physical_state_bbox"] == "not_available_before_placement"


def test_iccd_full_v1_adds_instance_patch_anchor(tmp_path: Path):
    ws = _make_workspace(tmp_path)
    _write_csv(
        ws
        / "place_dreamplace"
        / "feature"
        / "gcell_patch_map"
        / "density_map"
        / "place_allcell_density.csv",
        [[0.5, 0.0], [0.0, 0.0]],
    )
    _write_csv(
        ws
        / "place_dreamplace"
        / "feature"
        / "gcell_patch_map"
        / "density_map"
        / "place_allcell_pin_density.csv",
        [[2.0, 0.0], [0.0, 0.0]],
    )
    _write_csv(
        ws
        / "place_dreamplace"
        / "feature"
        / "gcell_patch_map"
        / "RUDY_map"
        / "place_rudy_union.csv",
        [[0.01, 0.0], [0.0, 0.0]],
    )
    _write_csv(
        ws / "place_dreamplace" / "feature" / "egr_congestion_map" / "place_egr_union_overflow.csv",
        [[3.0, 0.0], [0.0, 0.0]],
    )
    for path in (ws / "place_dreamplace" / "feature" / "gcell_patch_map" / "density_map").glob(
        "place_*density.csv"
    ):
        if path.name not in {"place_allcell_density.csv", "place_allcell_pin_density.csv"}:
            path.unlink()
    for path in (ws / "place_dreamplace" / "feature" / "gcell_patch_map" / "RUDY_map").glob(
        "place_*rudy*.csv"
    ):
        if path.name != "place_rudy_union.csv":
            path.unlink()

    FoundationExtractor(ws, profile="iccd_full_v1").extract(
        export_legacy_debug=True, stages=["place"]
    )

    record = json.loads(
        (ws / "foundation_data" / "ecc" / "vectors" / "instances" / "place.jsonl")
        .read_text()
        .splitlines()[0]
    )
    assert record["patch_anchor"]["primary_patch_id"] == 0
    assert record["patch_anchor"]["overlap_patch_ids"] == [0]
    assert record["physical_state"]["patch_id"] == 0
    assert record["physical_state"]["overlap_patch_ids"] == [0]
    assert record["patch_anchor"]["local_cell_density"] == 0.5
    assert record["patch_anchor"]["local_pin_density"] == 2.0
    assert record["patch_anchor"]["local_rudy"] == 0.01
    assert record["patch_anchor"]["local_egr_overflow"] == 3.0


def test_patch_anchor_uses_grid_lookup_without_scanning_all_patches():
    canonical_grid = build_patch_grid(
        128, 128, {"llx": 0.0, "lly": 0.0, "urx": 1280.0, "ury": 1280.0}
    )
    record = {
        "physical_state": {
            "bbox": {"llx": 15.0, "lly": 25.0, "urx": 35.0, "ury": 45.0},
            "center": {"x": 25.0, "y": 35.0},
        }
    }
    original_patch_for_point = extractor_module._patch_for_point
    original_overlap_patch_ids = extractor_module._overlap_patch_ids
    try:
        extractor_module._patch_for_point = lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("slow point scan used")
        )
        extractor_module._overlap_patch_ids = lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("slow overlap scan used")
        )

        extractor_module._attach_patch_anchor(record, canonical_grid, {})
    finally:
        extractor_module._patch_for_point = original_patch_for_point
        extractor_module._overlap_patch_ids = original_overlap_patch_ids

    assert record["patch_anchor"]["primary_patch_id"] == 386
    assert record["patch_anchor"]["overlap_patch_ids"] == [
        257,
        258,
        259,
        385,
        386,
        387,
        513,
        514,
        515,
    ]
    assert record["physical_state"]["patch_id"] == 386


def test_iccd_full_v1_adds_instance_connectivity_summary(tmp_path: Path):
    ws = _make_workspace(tmp_path)
    _write_text(
        ws / "place_dreamplace" / "output" / "gcd_place.def",
        """
VERSION 5.8 ;
DIVIDERCHAR "/" ;
BUSBITCHARS "[]" ;
DESIGN gcd ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 240 200 ) ;
COMPONENTS 3 ;
- U1 DFFHQNX1H7L + PLACED ( 10 20 ) N ;
- U2 BUFX1P4H7L + PLACED ( 180 20 ) N ;
- U3 NAND2 + PLACED ( 10 140 ) N ;
END COMPONENTS
NETS 2 ;
- clk ( U1 CK ) ( U2 A ) ( U3 A ) ;
- data ( U1 D ) ( U2 Y ) ;
END NETS
END DESIGN
""".strip()
        + "\n",
    )
    _write_json(
        ws / "place_dreamplace" / "output" / "gcd_place.json",
        {
            "design name": "gcd",
            "diearea": {"path": [[0, 0], [240, 0], [240, 200], [0, 200], [0, 0]]},
            "layerInfo": [{"id": 0, "layername": "cell"}],
            "data": [
                {
                    "type": "group",
                    "struct name": "Instance_U1",
                    "children": [
                        {
                            "type": "box",
                            "layer": 0,
                            "path": [[10, 20], [30, 20], [30, 40], [10, 40], [10, 20]],
                        }
                    ],
                },
                {
                    "type": "group",
                    "struct name": "Instance_U2",
                    "children": [
                        {
                            "type": "box",
                            "layer": 0,
                            "path": [[180, 20], [200, 20], [200, 40], [180, 40], [180, 20]],
                        }
                    ],
                },
                {
                    "type": "group",
                    "struct name": "Instance_U3",
                    "children": [
                        {
                            "type": "box",
                            "layer": 0,
                            "path": [[10, 140], [30, 140], [30, 160], [10, 160], [10, 140]],
                        }
                    ],
                },
            ],
        },
    )

    FoundationExtractor(ws, profile="iccd_full_v1").extract(
        export_legacy_debug=True, stages=["place"]
    )

    rows = [
        json.loads(line)
        for line in (ws / "foundation_data" / "ecc" / "vectors" / "instances" / "place.jsonl")
        .read_text()
        .splitlines()
    ]
    record = next(row for row in rows if row["identity"]["instance_key"] == "U1")
    summary = record["connectivity_summary"]
    assert summary["pin_count"] == 2
    assert summary["connected_net_count"] == 2
    assert summary["clock_pin_count"] == 1
    assert summary["max_net_degree"] >= 2
    assert summary["sum_connected_hpwl"] is not None
    assert summary["max_connected_hpwl"] is not None
    assert summary["cross_patch_net_count"] >= 1
    assert "route_wire_length" not in summary
    assert "rudy" not in summary
    assert "egr_overflow" not in summary


def test_iccd_full_v1_tracks_cts_inserted_instances(tmp_path: Path):
    ws = _make_workspace(tmp_path)
    _write_text(
        ws / "place_dreamplace" / "output" / "gcd_place.def",
        """
VERSION 5.8 ;
DIVIDERCHAR "/" ;
BUSBITCHARS "[]" ;
DESIGN gcd ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 200 200 ) ;
COMPONENTS 1 ;
- U1 DFFHQNX1H7L + PLACED ( 10 20 ) N ;
END COMPONENTS
NETS 1 ;
- clk ( U1 CK ) ;
END NETS
END DESIGN
""".strip()
        + "\n",
    )
    _write_json(
        ws / "place_dreamplace" / "output" / "gcd_place.json",
        {
            "design name": "gcd",
            "diearea": {"path": [[0, 0], [200, 0], [200, 200], [0, 200], [0, 0]]},
            "layerInfo": [{"id": 0, "layername": "cell"}],
            "data": [
                {
                    "type": "group",
                    "struct name": "Instance_U1",
                    "children": [
                        {
                            "type": "box",
                            "layer": 0,
                            "path": [[10, 20], [30, 20], [30, 40], [10, 40], [10, 20]],
                        }
                    ],
                }
            ],
        },
    )
    _write_text(
        ws / "CTS_ecc" / "output" / "gcd_CTS.def",
        """
VERSION 5.8 ;
DIVIDERCHAR "/" ;
BUSBITCHARS "[]" ;
DESIGN gcd ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 200 200 ) ;
COMPONENTS 2 ;
- U1 DFFHQNX1H7L + PLACED ( 12 22 ) N ;
- clk_leaf_0_0_buf BUFX1P4H7L + PLACED ( 80 80 ) N ;
END COMPONENTS
NETS 2 ;
- clk ( clk_leaf_0_0_buf A ) ;
- clk_leaf ( clk_leaf_0_0_buf Y ) ( U1 CK ) ;
END NETS
END DESIGN
""".strip()
        + "\n",
    )
    _write_json(
        ws / "CTS_ecc" / "output" / "gcd_CTS.json",
        {
            "design name": "gcd",
            "diearea": {"path": [[0, 0], [200, 0], [200, 200], [0, 200], [0, 0]]},
            "layerInfo": [{"id": 0, "layername": "cell"}],
            "data": [
                {
                    "type": "group",
                    "struct name": "Instance_U1",
                    "children": [
                        {
                            "type": "box",
                            "layer": 0,
                            "path": [[12, 22], [32, 22], [32, 42], [12, 42], [12, 22]],
                        }
                    ],
                },
                {
                    "type": "group",
                    "struct name": "clk_leaf_0_0_buf",
                    "children": [
                        {
                            "type": "box",
                            "layer": 0,
                            "path": [[80, 80], [90, 80], [90, 90], [80, 90], [80, 80]],
                        }
                    ],
                },
            ],
        },
    )

    FoundationExtractor(ws, profile="iccd_full_v1").extract(
        export_legacy_debug=True, stages=["place", "CTS"]
    )

    cts_instances = [
        json.loads(line)
        for line in (ws / "foundation_data" / "ecc" / "vectors" / "instances" / "CTS.jsonl")
        .read_text()
        .splitlines()
    ]
    cts_buf = next(item for item in cts_instances if item["name"] == "clk_leaf_0_0_buf")
    assert cts_buf["progressive_metadata"]["created_stage"] == "CTS"
    assert cts_buf["progressive_metadata"]["created_stage_source"] == "first_observed"
    assert cts_buf["progressive_metadata"]["exists_in_prev_stage"] is False
    assert cts_buf["progressive_metadata"]["exists_in_place"] is False
    assert cts_buf["clock_tree"]["is_clock_tree_node"] is True
    assert cts_buf["clock_tree"]["clock_tree_role"] in {
        "root_buffer",
        "internal_buffer",
        "leaf_buffer",
        "clock_buffer",
    }
    moved = next(item for item in cts_instances if item["identity"]["instance_key"] == "U1")
    assert moved["progressive_metadata"]["exists_in_prev_stage"] is True
    assert moved["progressive_metadata"]["moved_from_prev_stage"] is True
    assert moved["progressive_metadata"]["dx_from_prev_stage"] == 2.0
    assert moved["progressive_metadata"]["dy_from_prev_stage"] == 2.0

    import pyarrow.parquet as pq

    foundation_dir = ws / "foundation_data" / "ecc"
    delta_rows = pq.read_table(
        foundation_dir / "tables" / "stage_deltas.parquet",
        columns=["entity_type", "entity_key", "change_type", "metric_name", "delta_value"],
    ).to_pylist()
    assert any(
        row["entity_type"] == "instance"
        and row["entity_key"] == "Instance_U1"
        and row["change_type"] == "moved"
        and row["metric_name"] == "moved_from_prev_stage"
        for row in delta_rows
    )
    assert any(
        row["entity_type"] == "instance"
        and row["entity_key"] == "Instance_U1"
        and row["metric_name"] == "dx_from_prev_stage"
        and row["delta_value"] == 2.0
        for row in delta_rows
    )


def test_iccd_full_v1_writes_patch_indexed_stage_maps_for_floorplan_place_cts(tmp_path: Path):
    ws = _make_workspace(tmp_path)
    _write_sample_gcell_info(ws / "CTS_ecc")
    _write_sample_egr_demand_capacity(ws / "CTS_ecc")
    _write_csv(
        ws / "CTS_ecc" / "feature" / "gcell_patch_map" / "density_map" / "cts_allcell_density.csv",
        [[100, 101], [102, 103]],
    )
    _write_csv(
        ws
        / "CTS_ecc"
        / "feature"
        / "gcell_patch_map"
        / "density_map"
        / "cts_allcell_pin_density.csv",
        [[104, 105], [106, 107]],
    )
    _write_csv(
        ws / "CTS_ecc" / "feature" / "gcell_patch_map" / "density_map" / "cts_allnet_density.csv",
        [[108, 109], [110, 111]],
    )
    _write_csv(
        ws
        / "CTS_ecc"
        / "feature"
        / "gcell_patch_map"
        / "density_map"
        / "cts_global_net_density.csv",
        [[112, 113], [114, 115]],
    )
    _write_csv(
        ws
        / "CTS_ecc"
        / "feature"
        / "gcell_patch_map"
        / "density_map"
        / "cts_local_net_density.csv",
        [[116, 117], [118, 119]],
    )
    _write_csv(
        ws / "CTS_ecc" / "feature" / "gcell_patch_map" / "density_map" / "cts_macro_density.csv",
        [[0, 0], [0, 0]],
    )
    _write_csv(
        ws
        / "CTS_ecc"
        / "feature"
        / "gcell_patch_map"
        / "density_map"
        / "cts_macro_pin_density.csv",
        [[124, 125], [126, 127]],
    )
    _write_csv(
        ws / "CTS_ecc" / "feature" / "gcell_patch_map" / "density_map" / "cts_stdcell_density.csv",
        [[100, 101], [102, 103]],
    )
    _write_csv(
        ws
        / "CTS_ecc"
        / "feature"
        / "gcell_patch_map"
        / "density_map"
        / "cts_stdcell_pin_density.csv",
        [[132, 133], [134, 135]],
    )
    _write_csv(
        ws / "CTS_ecc" / "feature" / "gcell_patch_map" / "RUDY_map" / "cts_rudy_union.csv",
        [[110, 111], [112, 113]],
    )
    _write_csv(
        ws / "CTS_ecc" / "feature" / "gcell_patch_map" / "margin_map" / "cts_union_margin.csv",
        [[120, 121], [122, 123]],
    )
    floorplan_layout = json.loads(
        (ws / "Floorplan_ecc" / "output" / "gcd_Floorplan.json").read_text(encoding="utf-8")
    )
    floorplan_layout["data"].append(
        {
            "type": "group",
            "struct name": "Instance_ENDCAP_0",
            "children": [
                {"type": "box", "layer": 0, "path": [[0, 0], [50, 0], [50, 20], [0, 20], [0, 0]]}
            ],
        }
    )
    _write_json(ws / "Floorplan_ecc" / "output" / "gcd_Floorplan.json", floorplan_layout)

    FoundationExtractor(ws, profile="iccd_full_v1").extract(export_legacy_debug=True)

    foundation_dir = ws / "foundation_data" / "ecc"
    for rel in [
        "maps/Floorplan/density.json",
        "maps/Floorplan/floorplan.json",
        "maps/place/density.json",
        "maps/place/congestion.json",
        "maps/CTS/density.json",
        "maps/CTS/congestion.json",
    ]:
        assert (foundation_dir / rel).exists(), rel

    floorplan_density = json.loads(
        (foundation_dir / "maps" / "Floorplan" / "density.json").read_text(encoding="utf-8")
    )
    assert set(floorplan_density["maps"]) == {
        "allcell_density",
        "macro_density",
        "stdcell_density",
        "allcell_pin_density",
        "macro_pin_density",
        "stdcell_pin_density",
        "allnet_density",
        "local_net_density",
        "global_net_density",
    }
    assert [item["value"] for item in floorplan_density["maps"]["allcell_density"]["values"]] == [
        0.0,
        0.0,
        0.0,
        0.0,
    ]

    floorplan_specific = json.loads(
        (foundation_dir / "maps" / "Floorplan" / "floorplan.json").read_text(encoding="utf-8")
    )
    assert floorplan_specific["category"] == "floorplan"
    assert [item["value"] for item in floorplan_specific["maps"]["io_pin_density"]["values"]] == [
        0.0,
        1.0,
        0.0,
        0.0,
    ]
    assert [
        item["value"] for item in floorplan_specific["maps"]["physical_only_cell_density"]["values"]
    ] == [0.10416666666666667, 0.0, 0.0, 0.0]
    assert [
        item["value"] for item in floorplan_specific["maps"]["power_grid_density"]["values"]
    ] == [0.125, 0.125, 0.0, 0.0]

    import pyarrow.parquet as pq

    map_rows = pq.read_table(
        foundation_dir / "tables" / "run_stage_patch_maps.parquet",
        columns=["stage_name", "patch_id", "category", "channel", "value"],
    ).to_pylist()
    floorplan_map_values = {
        (row["channel"], row["patch_id"]): row["value"]
        for row in map_rows
        if row["stage_name"] == "Floorplan" and row["category"] == "floorplan"
    }
    assert set(channel for channel, _ in floorplan_map_values) == {
        "io_pin_density",
        "physical_only_cell_density",
        "power_grid_density",
        "pg_net_count",
    }
    assert [floorplan_map_values[("io_pin_density", patch_id)] for patch_id in range(4)] == [
        0.0,
        1.0,
        0.0,
        0.0,
    ]
    assert [
        floorplan_map_values[("physical_only_cell_density", patch_id)] for patch_id in range(4)
    ] == [0.10416666666666667, 0.0, 0.0, 0.0]
    assert [floorplan_map_values[("power_grid_density", patch_id)] for patch_id in range(4)] == [
        0.125,
        0.125,
        0.0,
        0.0,
    ]
    assert [floorplan_map_values[("pg_net_count", patch_id)] for patch_id in range(4)] == [
        1.0,
        1.0,
        0.0,
        0.0,
    ]

    feature_rows = pq.read_table(
        foundation_dir / "tables" / "run_stage_patch_features.parquet",
        columns=["stage_name", "patch_id", "pg_net_count"],
    ).to_pylist()
    floorplan_pg_counts = {
        row["patch_id"]: row["pg_net_count"]
        for row in feature_rows
        if row["stage_name"] == "Floorplan"
    }
    assert floorplan_pg_counts == {0: 1, 1: 1, 2: 0, 3: 0}

    place_density = json.loads(
        (foundation_dir / "maps" / "place" / "density.json").read_text(encoding="utf-8")
    )
    assert set(place_density["maps"]) == set(floorplan_density["maps"])
    assert place_density["maps"]["allcell_density"]["values"][0] == {
        "patch_id": 0,
        "row": 0,
        "col": 0,
        "value": 10.0,
    }

    place_congestion = json.loads(
        (foundation_dir / "maps" / "place" / "congestion.json").read_text(encoding="utf-8")
    )
    assert place_congestion["grid"] == {"source": "irt_gcell_info", "rows": 2, "cols": 2}
    assert [item["value"] for item in place_congestion["maps"]["union"]["values"]] == [
        3.0,
        3.0,
        3.0,
        7.0,
    ]
    assert "strictly_aligned" not in json.dumps(place_congestion)

    cts_density = json.loads(
        (foundation_dir / "maps" / "CTS" / "density.json").read_text(encoding="utf-8")
    )
    assert set(cts_density["maps"]) == set(place_density["maps"])
    assert cts_density["maps"]["allcell_density"]["values"][3] == {
        "patch_id": 3,
        "row": 1,
        "col": 1,
        "value": 103.0,
    }

    quality = json.loads((foundation_dir / "quality.json").read_text(encoding="utf-8"))
    assert quality["availability"]["maps"]["Floorplan"] == "available"


def test_iccd_full_v1_drops_legacy_map_dirs_lutrudy_and_filler_from_allcell_density(tmp_path: Path):
    ws = _make_workspace(tmp_path)
    _write_sample_gcell_info(ws / "CTS_ecc")
    _write_csv(
        ws / "CTS_ecc" / "feature" / "gcell_patch_map" / "density_map" / "cts_allcell_density.csv",
        [[0.4, 0.5], [0.6, 0.7]],
    )
    _write_csv(
        ws / "CTS_ecc" / "feature" / "gcell_patch_map" / "density_map" / "cts_macro_density.csv",
        [[0, 0.01], [0.02, 0]],
    )
    _write_csv(
        ws / "CTS_ecc" / "feature" / "gcell_patch_map" / "density_map" / "cts_stdcell_density.csv",
        [[0.1, 0.2], [0.3, 0.4]],
    )
    _write_csv(
        ws
        / "CTS_ecc"
        / "feature"
        / "gcell_patch_map"
        / "density_map"
        / "cts_allcell_pin_density.csv",
        [[10, 11], [12, 13]],
    )
    _write_csv(
        ws
        / "CTS_ecc"
        / "feature"
        / "gcell_patch_map"
        / "density_map"
        / "cts_macro_pin_density.csv",
        [[0, 1], [2, 0]],
    )
    _write_csv(
        ws
        / "CTS_ecc"
        / "feature"
        / "gcell_patch_map"
        / "density_map"
        / "cts_stdcell_pin_density.csv",
        [[1, 2], [3, 4]],
    )
    _write_csv(
        ws / "CTS_ecc" / "feature" / "gcell_patch_map" / "RUDY_map" / "cts_rudy_union.csv",
        [[1, 2], [3, 4]],
    )
    _write_csv(
        ws / "CTS_ecc" / "feature" / "gcell_patch_map" / "RUDY_map" / "cts_lut_rudy_union.csv",
        [[5, 6], [7, 8]],
    )

    FoundationExtractor(ws, profile="iccd_full_v1").extract(export_legacy_debug=True)

    foundation_dir = ws / "foundation_data" / "ecc"
    assert not (foundation_dir / "maps" / "canonical").exists()
    assert not (foundation_dir / "maps" / "raw").exists()

    cts_density = json.loads(
        (foundation_dir / "maps" / "CTS" / "density.json").read_text(encoding="utf-8")
    )
    allcell = [item["value"] for item in cts_density["maps"]["allcell_density"]["values"]]
    macro = [item["value"] for item in cts_density["maps"]["macro_density"]["values"]]
    assert macro == [0.0, 0.01, 0.02, 0.0]
    assert allcell == [0.1, 0.21000000000000002, 0.32, 0.4]
    allcell_pin = [item["value"] for item in cts_density["maps"]["allcell_pin_density"]["values"]]
    stdcell_pin = [item["value"] for item in cts_density["maps"]["stdcell_pin_density"]["values"]]
    macro_pin = [item["value"] for item in cts_density["maps"]["macro_pin_density"]["values"]]
    assert macro_pin == [0.0, 1.0, 2.0, 0.0]
    assert stdcell_pin == [1.0, 2.0, 3.0, 4.0]
    assert allcell_pin == [1.0, 3.0, 5.0, 4.0]

    cts_rudy = json.loads(
        (foundation_dir / "maps" / "CTS" / "rudy.json").read_text(encoding="utf-8")
    )
    assert set(cts_rudy["maps"]) == {"rudy_union"}
    assert not (foundation_dir / "maps" / "CTS" / "ignored.json").exists()
    raw_refs = json.loads(
        (foundation_dir / "raw_refs" / "artifacts.json").read_text(encoding="utf-8")
    )
    assert "lut_rudy" not in json.dumps(raw_refs)


def test_iccd_full_v1_marks_labels_missing_without_true_route_artifacts(tmp_path: Path):
    ws = _make_workspace(tmp_path, include_route_artifacts=False, include_route_maps=True)

    FoundationExtractor(ws, profile="iccd_full_v1").extract(export_legacy_debug=True)

    foundation_dir = ws / "foundation_data" / "ecc"
    quality = json.loads((foundation_dir / "quality.json").read_text(encoding="utf-8"))
    summary = json.loads((foundation_dir / "summary.json").read_text(encoding="utf-8"))

    assert not (foundation_dir / "labels" / "route_patch_overflow.jsonl").exists()
    assert not (foundation_dir / "labels" / "candidate_qor_summary.json").exists()
    assert "route_patch_overflow" not in quality["availability"].get("labels", {})
    assert quality["availability"]["labels"]["route_native_demand_capacity"] == "missing"
    assert (
        quality["null_reason"]["labels"]["route_native_demand_capacity"]
        == "missing_irt_space_router_native_demand_capacity_artifact"
    )
    assert "route_patch_overflow_count" not in summary["labels"]
    assert summary["labels"]["route_native_demand_capacity_count"] == 0


def test_iccd_full_v1_keeps_native_missing_without_reconstructed_fallback(tmp_path: Path):
    ws = _make_workspace(tmp_path, include_native_demand_capacity=False)

    FoundationExtractor(ws, profile="iccd_full_v1").extract(export_legacy_debug=True)

    foundation_dir = ws / "foundation_data" / "ecc"
    quality = json.loads((foundation_dir / "quality.json").read_text(encoding="utf-8"))
    patches = [
        json.loads(line)
        for line in (foundation_dir / "vectors" / "patches" / "route.jsonl")
        .read_text()
        .splitlines()
    ]

    assert not (foundation_dir / "labels" / "route_patch_overflow.jsonl").exists()
    assert not (foundation_dir / "labels" / "route_reconstructed_congestion.jsonl").exists()
    assert not (foundation_dir / "labels" / "route_reconstructed_demand_capacity.jsonl").exists()
    native = (foundation_dir / "labels" / "route_native_demand_capacity.jsonl").read_text(
        encoding="utf-8"
    )
    assert "route_true_overflow" not in patches[0]
    assert "route_native_demand_capacity" not in patches[0]
    assert patches[0]["route_oracle"]["native_demand_capacity"]["union_demand_capacity"] is None
    assert "union_overflow" not in patches[0]["route_oracle"]["native_demand_capacity"]
    assert "route_reconstructed_demand_capacity" not in patches[0]
    assert "route_reconstructed_congestion" not in patches[0]
    assert "route_demand_capacity" not in patches[0]
    assert patches[0]["label_refs"]["label_source_status"] == "missing"
    assert (
        patches[0]["null_reason"]["route_oracle"]
        == "missing_router_native_route_demand_capacity_artifact"
    )
    assert not (foundation_dir / "labels" / "candidate_qor_summary.json").exists()
    assert native == ""
    assert quality["availability"]["labels"]["route_native_demand_capacity"] == "missing"
    assert (
        quality["null_reason"]["labels"]["route_native_demand_capacity"]
        == "missing_irt_space_router_native_demand_capacity_artifact"
    )
    assert "route_patch_overflow" not in quality["availability"].get("labels", {})
    assert "route_reconstructed_congestion" not in quality["availability"]["labels"]
    assert "route_reconstructed_demand_capacity" not in quality["availability"]["labels"]


def test_iccd_full_v1_uses_json_native_route_file_under_space_router(tmp_path: Path):
    ws = _make_workspace(tmp_path, include_native_demand_capacity=False)
    _write_json(
        ws
        / "route_ecc"
        / "data"
        / "rt"
        / "space_router"
        / "route_native_demand_capacity_final.json",
        {
            "records": [
                {
                    "row": 0,
                    "col": 0,
                    "layer": "MET2",
                    "direction": "horizontal",
                    "demand": 6.0,
                    "capacity": 3.0,
                }
            ]
        },
    )

    FoundationExtractor(ws, profile="iccd_full_v1").extract(export_legacy_debug=True)

    foundation_dir = ws / "foundation_data" / "ecc"
    quality = json.loads((foundation_dir / "quality.json").read_text(encoding="utf-8"))
    summary = json.loads((foundation_dir / "summary.json").read_text(encoding="utf-8"))

    assert quality["availability"]["labels"]["route_native_demand_capacity"] == "available"
    assert summary["labels"]["route_native_demand_capacity_count"] == 4


def test_iccd_full_v1_ignores_route_native_files_outside_space_router(tmp_path: Path):
    ws = _make_workspace(tmp_path, include_native_demand_capacity=False)
    _write_text(
        ws / "route_ecc" / "data" / "rt" / "route_native_demand_capacity_final.jsonl",
        json.dumps(
            {
                "row": 0,
                "col": 0,
                "layer": "MET2",
                "direction": "horizontal",
                "demand": 6.0,
                "capacity": 3.0,
            }
        )
        + "\n",
    )

    FoundationExtractor(ws, profile="iccd_full_v1").extract(export_legacy_debug=True)

    foundation_dir = ws / "foundation_data" / "ecc"
    quality = json.loads((foundation_dir / "quality.json").read_text(encoding="utf-8"))
    summary = json.loads((foundation_dir / "summary.json").read_text(encoding="utf-8"))

    assert quality["availability"]["labels"]["route_native_demand_capacity"] == "missing"
    assert (
        quality["null_reason"]["labels"]["route_native_demand_capacity"]
        == "missing_irt_space_router_native_demand_capacity_artifact"
    )
    assert summary["labels"]["route_native_demand_capacity_count"] == 0


def test_source_signature_is_cached_until_reset(tmp_path: Path):
    ws = _make_workspace(tmp_path)
    extractor = FoundationExtractor(ws, profile="iccd_full_v1")

    first = extractor._source_signature()
    new_file = ws / "place_dreamplace" / "output" / "new_after_cache.txt"
    new_file.write_text("new", encoding="utf-8")
    second = extractor._source_signature()

    assert second == first
    extractor._source_signature_cache = None
    third = extractor._source_signature()
    assert "place_dreamplace/output/new_after_cache.txt" in third


def test_precomputed_timing_electrical_context_matches_legacy_helpers():
    timing_paths = [
        {
            "id": "p0-p1",
            "path_spatial": {"touched_patch_ids": [0, 1]},
            "endpoints": {"startpoint": {"patch_id": 0}, "endpoint": {"patch_id": 1}},
            "path_timing": {"slack": -0.2},
            "path_electrical": {
                "max_slew": 0.7,
                "capacitance_list": [1.0, 2.0],
                "slew_list": [0.3, 0.7],
                "resistance_list": [4.0],
                "incr_delay_list": [0.1, 0.2],
            },
        },
        {
            "id": "p2",
            "path_points": [{"patch_id": 2}],
            "endpoints": {"startpoint": {"patch_id": 2}, "endpoint": {"patch_id": 2}},
            "slack": 0.1,
            "path_electrical": {"capacitance_list": [3.0], "slew_list": [0.5]},
        },
    ]

    precomputed = extractor_module._timing_electrical_contexts_by_patch(timing_paths, stage="place")

    for patch_id in [0, 1, 2]:
        timing_context, electrical_context = precomputed[patch_id]
        assert timing_context == extractor_module._timing_for_patch(timing_paths, patch_id, "place")
        assert electrical_context == extractor_module._electrical_for_patch(
            timing_paths, patch_id, "place"
        )


def test_iccd_full_v1_patch_records_follow_vec_patches_schema(tmp_path: Path):
    ws = _make_workspace(tmp_path)

    FoundationExtractor(ws, profile="iccd_full_v1").extract(export_legacy_debug=True)

    foundation_dir = ws / "foundation_data" / "ecc"
    place_patches = [
        json.loads(line)
        for line in (foundation_dir / "vectors" / "patches" / "place.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    route_patches = [
        json.loads(line)
        for line in (foundation_dir / "vectors" / "patches" / "route.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    place0 = place_patches[0]
    route0 = route_patches[0]

    assert list(place0) == [
        "id",
        "stage",
        "patch_key",
        "source",
        "identity",
        "geometry",
        "local_density",
        "local_connectivity",
        "pre_route_estimators",
        "neighbor_context",
        "entity_refs",
        "timing_context",
        "electrical_context",
        "route_oracle",
        "label_refs",
        "drc_context",
        "progressive_metadata",
        "source_refs",
        "null_reason",
    ]
    legacy_flat_fields = {
        "patch_id",
        "row",
        "col",
        "instance_count",
        "instance_area",
        "macro_area",
        "net_count",
        "pin_count",
        "wire_length_by_layer",
        "route_native_demand_capacity",
        "route_demand_capacity",
        "drc",
        "timing",
        "electrical",
        "cell_density",
        "pin_density",
        "net_density",
        "macro_density",
        "rudy_congestion",
        "margin_horizontal",
        "margin_vertical",
        "congestion_horizontal",
        "congestion_vertical",
        "congestion_union",
    }
    assert not (set(place0) & legacy_flat_fields)
    assert place0["local_density"] == {
        "feature_role": "progressive_input",
        "available_for_training_input": True,
        "instance_count_center": 2,
        "instance_count_overlap": 2,
        "stdcell_count_center": 1,
        "macro_count_overlap": 1,
        "physical_only_count_overlap": 0,
        "stdcell_area_overlap": 200.0,
        "macro_area_overlap": 1500.0,
        "instance_area_overlap": 1700.0,
        "cell_density": 10.0,
        "macro_density": 0.0,
        "pin_count_anchor": 1,
        "pin_count_overlap": 0,
        "pin_density": 20.0,
        "net_density": 30.0,
        "wire_length": 0.0,
        "wire_length_by_layer": {},
        "via_count": 0,
        "source": "maps_and_vectors",
    }
    assert place0["local_connectivity"]["net_count_anchor"] == 1
    assert place0["local_connectivity"]["cross_patch_net_count"] == 1
    assert place0["local_connectivity"]["signal_net_count"] == 1
    assert place0["local_connectivity"]["local_hpwl_sum"] == 215.0
    assert place0["pre_route_estimators"] == {
        "feature_role": "progressive_input",
        "available_for_training_input": True,
        "rudy_horizontal": None,
        "rudy_vertical": None,
        "rudy_union": 50.0,
        "egr_overflow_horizontal": 1.0,
        "egr_overflow_vertical": 3.0,
        "egr_overflow_union": 3.0,
        "margin_horizontal": None,
        "margin_vertical": None,
        "source": "canonical_maps",
    }
    assert place0["neighbor_context"]["feature_role"] == "progressive_input"
    assert place0["neighbor_context"]["available_for_training_input"] is True
    assert place0["neighbor_context"]["window_3x3_patch_ids"] == [0, 1, 2, 3]
    assert place0["neighbor_context"]["window_3x3_valid_count"] == 4
    assert place0["neighbor_context"]["edge_position"] == "corner"
    assert place0["neighbor_context"]["window_3x3_cell_density_mean"] == 11.5
    assert place0["neighbor_context"]["window_3x3_pin_count_sum"] == 2
    assert place0["entity_refs"]["anchor_semantics"] == "primary_patch_or_center"
    assert place0["entity_refs"]["overlap_semantics"] == "bbox_or_segment_intersection"
    assert place0["entity_refs"]["instance_count"] == 2
    assert place0["entity_refs"]["pin_count"] == 1
    assert place0["entity_refs"]["net_count"] == 1
    assert place0["entity_refs"]["refs_truncated"] is False
    assert place0["entity_refs"]["sample_instance_keys"] == ["U1", "SRAM0"]
    assert place0["timing_context"]["feature_role"] == "stage_qor_context"
    assert place0["timing_context"]["available_for_training_input"] is True
    assert place0["timing_context"]["critical_path_count"] == 0
    assert place0["timing_context"]["worst_slack_min"] is None
    assert place0["electrical_context"]["feature_role"] == "stage_qor_context"
    assert place0["electrical_context"]["scope"] == "patch"
    assert place0["electrical_context"]["availability"] == "missing"
    assert place0["route_oracle"] is None
    assert place0["label_refs"]["label_source_status"] == "missing"
    assert place0["drc_context"]["feature_role"] == "route_or_drc_analysis"
    assert place0["drc_context"]["available_for_training_input"] is False
    assert place0["progressive_metadata"]["available_from"] == "Floorplan"
    assert place0["progressive_metadata"]["stage_order_index"] == 1
    assert place0["progressive_metadata"]["is_progressive_input_stage"] is True
    assert place0["progressive_metadata"]["is_route_oracle_stage"] is False
    assert "route_oracle" not in place0["progressive_metadata"]["input_blocks"]
    assert place0["progressive_metadata"]["oracle_blocks"] == []
    assert place0["source_refs"]["stage_def"] == "place_dreamplace/output/gcd_place.def"
    assert place0["source_refs"]["density_maps"] == "maps/place/density.json"
    assert place0["source_refs"]["route_label_definition"] is None
    assert place0["null_reason"]["route_oracle"] == "not_route_stage"

    native = route0["route_oracle"]["native_demand_capacity"]
    assert route0["route_oracle"]["feature_role"] == "route_only_oracle"
    assert route0["route_oracle"]["wire_length"] > 0
    assert native["horizontal_demand"] == 6.0
    assert native["horizontal_capacity"] == 3.0
    assert native["horizontal_demand_capacity"] == 3.0
    assert native["horizontal_utilization"] == 2.0
    assert native["vertical_demand"] == 4.0
    assert native["vertical_capacity"] == 2.0
    assert native["vertical_demand_capacity"] == 2.0
    assert native["vertical_utilization"] == 2.0
    assert native["union_demand_capacity"] == 3.0
    assert "horizontal_overflow" not in native
    assert "vertical_overflow" not in native
    assert "union_overflow" not in native
    assert native["union_utilization"] == 2.0
    assert native["tightness_class"] == "over_capacity"
    assert (
        route0["label_refs"]["route_native_demand_capacity"]
        == "labels/route_native_demand_capacity.jsonl#patch_id=0"
    )
    assert route0["label_refs"]["label_source_status"] == "available"
    assert route0["progressive_metadata"]["is_progressive_input_stage"] is False
    assert route0["progressive_metadata"]["is_route_oracle_stage"] is True
    assert route0["progressive_metadata"]["oracle_blocks"] == ["route_oracle"]
    assert (
        route0["source_refs"]["route_label_definition"]
        == "route_oracle.native_demand_capacity.union_demand_capacity=max(horizontal_demand_capacity,vertical_demand_capacity); union_utilization=max(horizontal_utilization,vertical_utilization); tightness_class={over_capacity,near_capacity,relaxed,unknown}"
    )


def test_iccd_full_v1_patch_records_compute_progressive_deltas_and_quality_stats(tmp_path: Path):
    ws = _make_workspace(tmp_path)
    _write_sample_gcell_info(ws / "CTS_ecc")
    _write_sample_egr_demand_capacity(ws / "CTS_ecc")
    _write_csv(
        ws / "CTS_ecc" / "feature" / "gcell_patch_map" / "density_map" / "cts_allcell_density.csv",
        [[100, 101], [102, 103]],
    )
    _write_csv(
        ws
        / "CTS_ecc"
        / "feature"
        / "gcell_patch_map"
        / "density_map"
        / "cts_allcell_pin_density.csv",
        [[104, 105], [106, 107]],
    )
    _write_csv(
        ws / "CTS_ecc" / "feature" / "gcell_patch_map" / "density_map" / "cts_allnet_density.csv",
        [[108, 109], [110, 111]],
    )
    _write_csv(
        ws / "CTS_ecc" / "feature" / "gcell_patch_map" / "density_map" / "cts_macro_density.csv",
        [[0, 0], [0, 0]],
    )
    _write_csv(
        ws / "CTS_ecc" / "feature" / "gcell_patch_map" / "density_map" / "cts_stdcell_density.csv",
        [[100, 101], [102, 103]],
    )
    _write_csv(
        ws
        / "CTS_ecc"
        / "feature"
        / "gcell_patch_map"
        / "density_map"
        / "cts_stdcell_pin_density.csv",
        [[104, 105], [106, 107]],
    )
    _write_csv(
        ws
        / "CTS_ecc"
        / "feature"
        / "gcell_patch_map"
        / "density_map"
        / "cts_macro_pin_density.csv",
        [[0, 0], [0, 0]],
    )
    _write_csv(
        ws / "CTS_ecc" / "feature" / "gcell_patch_map" / "RUDY_map" / "cts_rudy_union.csv",
        [[110, 111], [112, 113]],
    )

    FoundationExtractor(ws, profile="iccd_full_v1").extract(export_legacy_debug=True)

    foundation_dir = ws / "foundation_data" / "ecc"
    place0 = json.loads(
        (foundation_dir / "vectors" / "patches" / "place.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    cts0 = json.loads(
        (foundation_dir / "vectors" / "patches" / "CTS.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    route0 = json.loads(
        (foundation_dir / "vectors" / "patches" / "route.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    drc0 = json.loads(
        (foundation_dir / "vectors" / "patches" / "drc.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    quality = json.loads((foundation_dir / "quality.json").read_text(encoding="utf-8"))

    assert place0["progressive_metadata"]["density_delta_from_prev_stage"] == 10.0
    assert place0["progressive_metadata"]["pin_count_delta_from_prev_stage"] == -1.0
    assert place0["progressive_metadata"]["rudy_delta_from_prev_stage"] is None
    assert place0["progressive_metadata"]["egr_overflow_delta_from_prev_stage"] is None
    assert cts0["progressive_metadata"]["density_delta_from_prev_stage"] == 90.0
    assert cts0["progressive_metadata"]["pin_count_delta_from_prev_stage"] == -1.0
    assert cts0["progressive_metadata"]["rudy_delta_from_prev_stage"] == 60.0
    assert cts0["progressive_metadata"]["egr_overflow_delta_from_prev_stage"] == 0.0

    for block_name in (
        "local_density",
        "local_connectivity",
        "pre_route_estimators",
        "neighbor_context",
        "timing_context",
        "electrical_context",
        "drc_context",
    ):
        assert route0[block_name]["available_for_training_input"] is False
    assert route0["route_oracle"]["available_for_training_input"] is False
    assert drc0["progressive_metadata"]["is_progressive_input_stage"] is False
    assert drc0["progressive_metadata"]["input_blocks"] == []
    for block_name in (
        "local_density",
        "local_connectivity",
        "pre_route_estimators",
        "neighbor_context",
        "timing_context",
        "electrical_context",
        "drc_context",
    ):
        assert drc0[block_name]["available_for_training_input"] is False

    patch_quality = quality["patches"]
    assert patch_quality["rows_by_stage"] == {
        "Floorplan": 4,
        "place": 4,
        "CTS": 4,
        "route": 4,
        "drc": 4,
    }
    assert patch_quality["schema_coverage_by_stage"]["route"]["complete_records"] == 4
    assert patch_quality["pre_route_estimators_availability_by_stage"]["place"] == {
        "available": 4,
        "missing": 0,
        "not_applicable": 0,
    }
    assert patch_quality["pre_route_estimators_availability_by_stage"]["route"] == {
        "available": 0,
        "missing": 0,
        "not_applicable": 4,
    }
    assert patch_quality["route_label_availability"] == {"available": 4, "missing": 0, "partial": 0}
    assert patch_quality["route_oracle_tightness_class_distribution"] == {
        "over_capacity": 2,
        "near_capacity": 0,
        "relaxed": 2,
        "unknown": 0,
    }
    assert patch_quality["refs_truncated_count_by_stage"]["route"] == 0
    assert patch_quality["timing_context_availability_by_stage"]["route"] == {
        "available": 1,
        "missing": 3,
        "not_applicable": 0,
    }
    assert patch_quality["electrical_context_availability_by_stage"]["route"] == {
        "available": 1,
        "missing": 3,
        "not_applicable": 0,
    }
    assert patch_quality["drc_context_availability_by_stage"]["drc"]["available"] == 4
    null_reason_counts = {
        item["reason"]: item["count"] for item in patch_quality["null_reason_topk"]
    }
    assert null_reason_counts["route_oracle=not_route_stage"] == 16


def test_iccd_full_v1_cleans_stale_outputs_before_rewrite(tmp_path: Path):
    ws = _make_workspace(tmp_path)
    foundation_dir = ws / "foundation_data" / "ecc"
    stale = foundation_dir / "vectors" / "instances" / "old-00000.jsonl"
    stale.parent.mkdir(parents=True)
    stale.write_text('{"stale": true}\n', encoding="utf-8")

    FoundationExtractor(ws, profile="iccd_full_v1").extract(export_legacy_debug=True)

    assert not stale.exists()


def test_iccd_full_v1_honors_stage_filter_and_raw_refs_option(tmp_path: Path):
    ws = _make_workspace(tmp_path)

    FoundationExtractor(ws, profile="iccd_full_v1").extract(
        export_legacy_debug=True, stages=["place"], include_raw_refs=False
    )

    foundation_dir = ws / "foundation_data" / "ecc"
    summary = json.loads((foundation_dir / "summary.json").read_text(encoding="utf-8"))
    manifest = json.loads((foundation_dir / "manifest.json").read_text(encoding="utf-8"))
    evidence = json.loads(
        (foundation_dir / "views" / "agent" / "evidence_index.json").read_text(encoding="utf-8")
    )
    quality = json.loads((foundation_dir / "quality.json").read_text(encoding="utf-8"))

    assert "stages" not in summary
    assert [item["name"] for item in summary["flow"]["steps"]] == ["place"]
    assert (foundation_dir / "vectors" / "instances" / "place.jsonl").exists()
    assert not (foundation_dir / "vectors" / "instances" / "route.jsonl").exists()
    assert not (foundation_dir / "raw_refs" / "artifacts.json").exists()
    assert manifest["options"]["stages"] == ["place"]
    assert manifest["options"]["include_raw_refs"] is False
    assert "raw_refs" not in manifest["artifacts"]
    assert evidence["raw_refs"] is None
    assert evidence["raw_refs_disabled"] is True
    assert "route_patch_overflow" not in quality["availability"].get("labels", {})


def test_iccd_full_v1_rejects_unknown_stage_filter(tmp_path: Path):
    ws = _make_workspace(tmp_path)

    try:
        FoundationExtractor(ws, profile="iccd_full_v1").extract(
            export_legacy_debug=True, stages=["missing_stage"]
        )
    except ValueError as exc:
        assert "unknown foundation extraction stage" in str(exc)
    else:
        raise AssertionError("expected unknown stage to fail")


def test_iccd_full_v1_writes_canonical_pin_records_without_flat_fields(tmp_path: Path):
    ws = _make_workspace(tmp_path)
    _write_text(
        ws / "place_dreamplace" / "output" / "gcd_place.def",
        """
VERSION 5.8 ;
DIVIDERCHAR "/" ;
BUSBITCHARS "[]" ;
DESIGN gcd ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 200 200 ) ;
COMPONENTS 1 ;
- U1 NAND2 + PLACED ( 10 20 ) N ;
END COMPONENTS
PINS 1 ;
- OUT + NET n1 + DIRECTION OUTPUT + USE SIGNAL + LAYER MET2 ( -5 -5 ) ( 5 5 ) + PLACED ( 180 50 ) N ;
END PINS
NETS 1 ;
- n1 ( U1 A ) ( PIN OUT ) ;
END NETS
END DESIGN
""".strip()
        + "\n",
    )

    FoundationExtractor(ws, profile="iccd_full_v1").extract(
        export_legacy_debug=True, stages=["place"]
    )

    rows = [
        json.loads(line)
        for line in (ws / "foundation_data" / "ecc" / "vectors" / "pins" / "place.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    io_pin = next(row for row in rows if row["pin_key"] == "PIN:OUT")
    inst_pin = next(row for row in rows if row["pin_key"] == "U1:A")

    assert list(io_pin) == [
        "id",
        "stage",
        "pin_key",
        "source",
        "identity",
        "electrical_context",
        "parent_instance",
        "geometry",
        "connectivity_context",
        "timing_context",
        "patch_anchor",
        "route_context",
        "progressive_metadata",
        "source_refs",
        "null_reason",
    ]
    assert {
        "instance",
        "net",
        "pin_name",
        "direction",
        "bbox",
        "center",
        "layer",
        "patch_id",
    }.isdisjoint(io_pin)
    assert io_pin["identity"] == {
        "pin_key": "PIN:OUT",
        "pin_kind": "io_port",
        "instance": "PIN",
        "parent_instance_key": None,
        "parent_master": None,
        "pin_name": "OUT",
        "full_name": "PIN/OUT",
        "net": "n1",
        "net_key": "n1",
        "is_io": True,
        "is_macro_pin": False,
        "classification_source": "def_section",
    }
    assert io_pin["electrical_context"]["direction"] == "OUTPUT"
    assert io_pin["electrical_context"]["use"] == "SIGNAL"
    assert io_pin["electrical_context"]["direction_source"] == "def_pin_direction"
    assert io_pin["geometry"]["geometry_status"] == "exact"
    assert io_pin["geometry"]["anchor_source"] == "io_pin_shape"
    assert io_pin["geometry"]["bbox"] == {"llx": 175.0, "lly": 45.0, "urx": 185.0, "ury": 55.0}
    assert io_pin["geometry"]["center"] == {"x": 180.0, "y": 50.0}
    assert io_pin["geometry"]["layers"] == ["MET2"]
    assert io_pin["patch_anchor"]["anchor_source"] == "exact_pin_geometry"
    assert io_pin["route_context"] is None
    assert io_pin["progressive_metadata"]["route_only_oracle"] is False
    assert inst_pin["parent_instance"]["instance_key"] == "U1"
    assert inst_pin["geometry"]["geometry_status"] == "fallback_to_instance_anchor"
    assert inst_pin["geometry"]["anchor_source"] == "parent_instance_center"
    assert inst_pin["geometry"]["bbox"] is None
    assert inst_pin["null_reason"]["geometry_bbox"] == "missing_lef_pin_shape"
    assert inst_pin["connectivity_context"]["net_degree"] == 2
    assert inst_pin["connectivity_context"]["same_net_pin_count"] == 2


def test_iccd_full_v1_pins_use_lef_geometry_electrical_context_and_route_attribution(
    tmp_path: Path,
):
    ws = _make_workspace(tmp_path)
    _write_json(
        ws / "home" / "parameters.json",
        {
            "PDK": "unit-test",
            "PDK Root": str(ws / "pdk"),
            "Design": "gcd",
            "Core": {"Utilitization": 0.5},
        },
    )
    _write_text(
        ws / "pdk" / "unit.lef",
        """
VERSION 5.8 ;
MACRO NAND2
  CLASS CORE ;
  SIZE 20 BY 20 ;
  PIN A
    DIRECTION INPUT ;
    USE SIGNAL ;
    PORT
      LAYER MET2 ;
        RECT 1 2 5 6 ;
    END
  END A
  PIN Y
    DIRECTION OUTPUT ;
    USE SIGNAL ;
    PORT
      LAYER MET2 ;
        RECT 10 10 14 14 ;
    END
  END Y
END NAND2
END LIBRARY
""".strip()
        + "\n",
    )
    _write_text(
        ws / "place_dreamplace" / "output" / "gcd_place.def",
        """
VERSION 5.8 ;
DIVIDERCHAR "/" ;
BUSBITCHARS "[]" ;
DESIGN gcd ;
UNITS DISTANCE MICRONS 1 ;
DIEAREA ( 0 0 ) ( 200 200 ) ;
COMPONENTS 2 ;
- U1 NAND2 + PLACED ( 10 20 ) N ;
- U2 NAND2 + PLACED ( 40 20 ) N ;
END COMPONENTS
PINS 1 ;
- OUT + NET n1 + DIRECTION OUTPUT + USE SIGNAL + LAYER MET2 ( -5 -5 ) ( 5 5 ) + PLACED ( 180 50 ) N ;
END PINS
NETS 2 ;
- n1 ( U1 A ) ( U2 A ) ( PIN OUT ) ;
- n2 ( U1 Y ) ( U2 Y ) ;
END NETS
END DESIGN
""".strip()
        + "\n",
    )
    _write_text(
        ws / "route_ecc" / "output" / "gcd_route.def",
        """
VERSION 5.8 ;
DIVIDERCHAR "/" ;
BUSBITCHARS "[]" ;
DESIGN gcd ;
UNITS DISTANCE MICRONS 1 ;
DIEAREA ( 0 0 ) ( 200 200 ) ;
COMPONENTS 2 ;
- U1 NAND2 + PLACED ( 10 20 ) N ;
- U2 NAND2 + PLACED ( 40 20 ) N ;
END COMPONENTS
PINS 1 ;
- OUT + NET n1 + DIRECTION OUTPUT + USE SIGNAL + LAYER MET2 ( -5 -5 ) ( 5 5 ) + PLACED ( 180 50 ) N ;
END PINS
NETS 2 ;
- n1 ( U1 A ) ( U2 A ) ( PIN OUT )
  + ROUTED MET2 ( 11 22 ) ( 90 * )
    NEW MET2 ( 42 22 ) ( 100 * )
  ;
- n2 ( U1 Y ) ( U2 Y )
  + ROUTED MET3 ( 22 32 ) ( * 120 )
  ;
END NETS
END DESIGN
""".strip()
        + "\n",
    )
    _write_sample_gcell_info(ws / "route_ecc")
    _write_text(
        ws
        / "route_ecc"
        / "data"
        / "rt"
        / "space_router"
        / "route_native_demand_capacity_final.jsonl",
        "\n".join(
            [
                json.dumps(
                    {
                        "row": 0,
                        "col": 0,
                        "gcell": {"x": 0, "y": 0},
                        "layer": "MET2",
                        "direction": "horizontal",
                        "demand": 6,
                        "capacity": 3,
                        "demand_capacity": 3,
                        "utilization": 2,
                        "source": "irt_space_router_native",
                    }
                ),
                json.dumps(
                    {
                        "row": 0,
                        "col": 1,
                        "gcell": {"x": 1, "y": 0},
                        "layer": "MET2",
                        "direction": "horizontal",
                        "demand": 2,
                        "capacity": 3,
                        "demand_capacity": -1,
                        "utilization": 0.67,
                        "source": "irt_space_router_native",
                    }
                ),
            ]
        )
        + "\n",
    )
    _write_json(
        ws / "drc_ecc" / "data" / "drc" / "violation_map.json",
        [
            {
                "type": "short",
                "layer": "MET2",
                "bbox": {"llx": 10, "lly": 20, "urx": 20, "ury": 30},
                "count": 2,
            }
        ],
    )

    FoundationExtractor(ws, profile="iccd_full_v1").extract(
        export_legacy_debug=True, stages=["place", "route", "drc"]
    )

    foundation_dir = ws / "foundation_data" / "ecc"
    place_rows = [
        json.loads(line)
        for line in (foundation_dir / "vectors" / "pins" / "place.jsonl").read_text().splitlines()
    ]
    route_rows = [
        json.loads(line)
        for line in (foundation_dir / "vectors" / "pins" / "route.jsonl").read_text().splitlines()
    ]
    u1_a = next(row for row in place_rows if row["pin_key"] == "U1:A")
    u1_y = next(row for row in place_rows if row["pin_key"] == "U1:Y")
    route_u1_a = next(row for row in route_rows if row["pin_key"] == "U1:A")

    assert u1_a["geometry"]["geometry_status"] == "exact"
    assert u1_a["geometry"]["anchor_source"] == "lef_pin_shape"
    assert u1_a["geometry"]["bbox"] == {"llx": 11.0, "lly": 22.0, "urx": 15.0, "ury": 26.0}
    assert u1_a["geometry"]["layers"] == ["MET2"]
    assert u1_a["electrical_context"]["direction"] == "INPUT"
    assert u1_a["electrical_context"]["direction_source"] == "lef_pin_direction"
    assert u1_a["connectivity_context"]["pin_role"] == "sink"
    assert u1_y["electrical_context"]["direction"] == "OUTPUT"
    assert u1_y["connectivity_context"]["pin_role"] == "driver"
    assert u1_a["patch_anchor"]["nearby_pin_count"] >= 2
    assert u1_a["patch_anchor"]["nearby_io_pin_count"] >= 0
    assert u1_a["source_refs"]["lef"].endswith("unit.lef")
    assert u1_a["source_refs"]["lef_macro"] == "NAND2"
    assert u1_a["source_refs"]["lef_pin"] == "A"
    assert "geometry_bbox" not in u1_a["null_reason"]

    assert route_u1_a["route_context"]["route_only_oracle"] is True
    assert route_u1_a["route_context"]["nearby_wire_count"] >= 1
    assert route_u1_a["route_context"]["nearby_drc_count"] == 2
    assert route_u1_a["route_context"]["local_final_overflow"] == 3.0
    assert route_u1_a["route_context"]["net_detour_ratio"] is not None
    assert route_u1_a["route_context"]["source"] == "route_ecc/output/gcd_route.def"


def test_iccd_full_v1_pin_progressive_and_route_leakage_guard(tmp_path: Path):
    ws = _make_workspace(tmp_path)
    _write_text(
        ws / "place_dreamplace" / "output" / "gcd_place.def",
        """
VERSION 5.8 ;
DIVIDERCHAR "/" ;
BUSBITCHARS "[]" ;
DESIGN gcd ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 200 200 ) ;
COMPONENTS 1 ;
- U1 DFFHQNX1H7L + PLACED ( 10 20 ) N ;
END COMPONENTS
NETS 1 ;
- clk ( U1 CK ) ;
END NETS
END DESIGN
""".strip()
        + "\n",
    )
    _write_text(
        ws / "CTS_ecc" / "output" / "gcd_CTS.def",
        """
VERSION 5.8 ;
DIVIDERCHAR "/" ;
BUSBITCHARS "[]" ;
DESIGN gcd ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 200 200 ) ;
COMPONENTS 2 ;
- U1 DFFHQNX1H7L + PLACED ( 12 22 ) N ;
- clk_leaf_0_0_buf BUFX1P4H7L + PLACED ( 80 80 ) N ;
END COMPONENTS
NETS 2 ;
- clk ( clk_leaf_0_0_buf A ) ;
- clk_leaf ( clk_leaf_0_0_buf Y ) ( U1 CK ) ;
END NETS
END DESIGN
""".strip()
        + "\n",
    )
    _write_json(
        ws / "CTS_ecc" / "output" / "gcd_CTS.json",
        {
            "design name": "gcd",
            "diearea": {"path": [[0, 0], [200, 0], [200, 200], [0, 200], [0, 0]]},
            "layerInfo": [{"id": 0, "layername": "cell"}],
            "data": [
                {
                    "type": "group",
                    "struct name": "Instance_U1",
                    "children": [
                        {
                            "type": "box",
                            "layer": 0,
                            "path": [[12, 22], [32, 22], [32, 42], [12, 42], [12, 22]],
                        }
                    ],
                },
                {
                    "type": "group",
                    "struct name": "clk_leaf_0_0_buf",
                    "children": [
                        {
                            "type": "box",
                            "layer": 0,
                            "path": [[80, 80], [90, 80], [90, 90], [80, 90], [80, 80]],
                        }
                    ],
                },
            ],
        },
    )

    _write_text(
        ws / "route_ecc" / "output" / "gcd_route.def",
        """
VERSION 5.8 ;
DIVIDERCHAR "/" ;
BUSBITCHARS "[]" ;
DESIGN gcd ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 200 200 ) ;
COMPONENTS 2 ;
- U1 DFFHQNX1H7L + PLACED ( 12 22 ) N ;
- clk_leaf_0_0_buf BUFX1P4H7L + PLACED ( 80 80 ) N ;
END COMPONENTS
NETS 2 ;
- clk ( clk_leaf_0_0_buf A )
  + ROUTED MET2 ( 80 80 ) ( 120 * )
  ;
- clk_leaf ( clk_leaf_0_0_buf Y ) ( U1 CK )
  + ROUTED MET3 ( 80 80 ) ( * 120 )
  ;
END NETS
END DESIGN
""".strip()
        + "\n",
    )

    FoundationExtractor(ws, profile="iccd_full_v1").extract(
        export_legacy_debug=True, stages=["place", "CTS", "route"]
    )

    foundation_dir = ws / "foundation_data" / "ecc"
    place_pin = json.loads(
        (foundation_dir / "vectors" / "pins" / "place.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    cts_rows = [
        json.loads(line)
        for line in (foundation_dir / "vectors" / "pins" / "CTS.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    route_rows = [
        json.loads(line)
        for line in (foundation_dir / "vectors" / "pins" / "route.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    new_cts_pin = next(row for row in cts_rows if row["pin_key"] == "clk_leaf_0_0_buf:A")
    moved_cts_pin = next(row for row in cts_rows if row["pin_key"] == "U1:CK")
    route_pin = next(row for row in route_rows if row["pin_key"] == "clk_leaf_0_0_buf:A")

    assert place_pin["route_context"] is None
    assert place_pin["progressive_metadata"]["route_only_oracle"] is False
    assert "local_final_overflow" not in json.dumps(place_pin)
    assert new_cts_pin["progressive_metadata"]["available_from"] == "CTS"
    assert new_cts_pin["progressive_metadata"]["introduced_by_cts"] is True
    assert new_cts_pin["progressive_metadata"]["exists_in_place"] is False
    assert moved_cts_pin["progressive_metadata"]["prev_net"] == "clk"
    assert moved_cts_pin["progressive_metadata"]["net_changed_from_prev_stage"] is True
    assert moved_cts_pin["progressive_metadata"]["moved_from_prev_stage"] is True
    assert route_pin["route_context"]["route_only_oracle"] is True
    assert route_pin["progressive_metadata"]["route_only_oracle"] is True
    assert route_pin["route_context"]["net_routed_length"] == 40.0


def test_iccd_full_v1_wire_primary_patch_is_in_intersections_on_grid_boundary(tmp_path: Path):
    ws = _make_workspace(tmp_path)
    _write_text(
        ws / "route_ecc" / "output" / "gcd_route.def",
        """
VERSION 5.8 ;
DIVIDERCHAR "/" ;
BUSBITCHARS "[]" ;
DESIGN gcd ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 200 200 ) ;
TRACKS X 50 DO 1 STEP 100 LAYER MET3 ;
GCELLGRID X 0 DO 3 STEP 100 ;
GCELLGRID Y 0 DO 3 STEP 100 ;
COMPONENTS 1 ;
- U1 NAND2 + PLACED ( 10 20 ) N ;
END COMPONENTS
PINS 1 ;
- OUT + NET n_boundary + DIRECTION OUTPUT + PLACED ( 180 50 ) N ;
END PINS
NETS 1 ;
- n_boundary ( U1 A ) ( PIN OUT )
  + ROUTED MET3 ( 120 0 ) ( * 200 )
  ;
END NETS
END DESIGN
""".strip()
        + "\n",
    )

    FoundationExtractor(ws, profile="iccd_full_v1").extract(
        export_legacy_debug=True, stages=["route"]
    )

    foundation_dir = ws / "foundation_data" / "ecc"
    wire = next(
        json.loads(line)
        for line in (foundation_dir / "vectors" / "wires" / "route.jsonl").read_text().splitlines()
        if line.strip()
    )
    primary_patch_id = wire["patch_anchor"]["primary_patch_id"]
    primary_intersections = [
        item for item in wire["patch_intersections"] if item["is_primary_patch"]
    ]
    assert any(item["patch_id"] == primary_patch_id for item in wire["patch_intersections"])
    assert len(primary_intersections) == 1
    assert primary_intersections[0]["patch_id"] == primary_patch_id


def test_iccd_full_v1_writes_nested_net_wire_graph_patch_and_tech_records(tmp_path: Path):
    ws = _make_workspace(tmp_path)

    FoundationExtractor(ws, profile="iccd_full_v1").extract(export_legacy_debug=True)

    foundation_dir = ws / "foundation_data" / "ecc"
    nets = [
        json.loads(line)
        for line in (foundation_dir / "vectors" / "nets" / "route.jsonl").read_text().splitlines()
    ]
    n1 = next(row for row in nets if row["net_key"] == "n1")
    assert list(n1) == [
        "id",
        "stage",
        "net_key",
        "name",
        "source",
        "identity",
        "connectivity_summary",
        "terminal_refs",
        "geometry_proxy",
        "patch_anchor",
        "timing_context",
        "route_analysis",
        "progressive_metadata",
        "source_refs",
        "null_reason",
    ]
    assert n1["identity"]["net_class"] == "signal"
    assert n1["connectivity_summary"]["terminal_count"] >= 2
    assert n1["connectivity_summary"]["pin_count"] == n1["connectivity_summary"]["terminal_count"]
    assert n1["terminal_refs"]
    terminal_ref = n1["terminal_refs"][0]
    assert {
        "pin_key",
        "pin_kind",
        "instance",
        "parent_instance_key",
        "parent_master",
        "pin_name",
        "full_name",
        "pin_role",
        "is_driver",
        "is_sink",
        "is_io",
        "is_macro_pin",
        "patch_id",
        "geometry_status",
        "anchor_source",
        "is_on_critical_path",
    } <= set(terminal_ref)
    assert n1["geometry_proxy"]["hpwl"] is not None
    assert {
        "anchor_source",
        "anchor_quality",
        "terminal_bbox",
        "terminal_center",
        "hpwl",
        "x_span",
        "y_span",
        "area",
        "aspect_ratio",
        "patch_ids",
        "patch_span_count",
        "cross_patch",
        "exact_terminal_count",
        "fallback_terminal_count",
        "missing_anchor_terminal_count",
    } <= set(n1["geometry_proxy"])
    assert n1["geometry_proxy"]["cross_patch"] == (n1["geometry_proxy"]["patch_span_count"] > 1)
    assert n1["geometry_proxy"]["anchor_quality"] in {
        "all_exact",
        "mixed_exact_and_fallback",
        "all_fallback",
        "missing",
    }
    assert {
        "primary_patch_id",
        "patch_ids",
        "patch_span_count",
        "anchor_source",
        "local_cell_density_mean",
        "local_pin_density_mean",
        "local_rudy_mean",
        "local_rudy_max",
        "local_egr_overflow_mean",
        "local_egr_overflow_max",
        "terminal_count_by_patch",
    } <= set(n1["patch_anchor"])
    assert {
        "available",
        "timing_path_count",
        "is_on_critical_path",
        "worst_slack_seen",
        "min_arrival",
        "max_arrival",
        "max_slew",
        "max_cap",
        "driver_pin_keys",
        "endpoint_pin_count",
        "path_refs",
        "source",
    } <= set(n1["timing_context"])
    assert n1["route_analysis"]["route_only_oracle"] is True
    assert {
        "route_only_oracle",
        "routed_wire_count",
        "routed_wire_length",
        "routed_bbox",
        "covered_layers",
        "via_count",
        "detour_ratio",
        "routed_patch_ids",
        "routed_patch_count",
        "overlapped_congested_patch_count",
        "final_overflow_sum",
        "final_overflow_max",
        "patch_attribution_refs",
        "source",
    } <= set(n1["route_analysis"])
    assert n1["route_analysis"]["routed_wire_length"] > 0
    assert n1["route_analysis"]["routed_wire_count"] > 0
    assert n1["route_analysis"]["routed_patch_count"] == len(
        n1["route_analysis"]["routed_patch_ids"]
    )
    assert (
        n1["route_analysis"]["detour_ratio"]
        == n1["route_analysis"]["routed_wire_length"] / n1["geometry_proxy"]["hpwl"]
    )
    assert n1["route_analysis"]["final_overflow_sum"] == 8.0
    assert n1["route_analysis"]["final_overflow_max"] == 5.0
    assert {
        "patch_id",
        "wire_length_in_patch",
        "via_count_in_patch",
        "final_overflow",
        "wire_segment_count",
        "covered_layers",
        "contribution_score",
    } <= set(n1["route_analysis"]["patch_attribution_refs"][0])
    assert n1["route_analysis"]["via_count"] >= 0
    assert {
        "available_from",
        "created_stage",
        "created_stage_source",
        "exists_in_prev_stage",
        "exists_in_place",
        "introduced_by_cts",
        "prev_net_key",
        "renamed_from_prev_stage",
        "terminal_count_changed_from_prev_stage",
        "hpwl_delta_from_prev_stage",
        "patch_span_delta_from_prev_stage",
        "route_only_oracle",
    } <= set(n1["progressive_metadata"])
    assert n1["progressive_metadata"]["exists_in_prev_stage"] is True
    assert n1["progressive_metadata"]["exists_in_place"] is True
    assert n1["source_refs"]["def"] == "route_ecc/output/gcd_route.def"
    assert n1["source_refs"]["def_section"] == "NETS"
    assert n1["source_refs"]["def_index"] == 0
    assert n1["source_refs"]["sta"] == "route_ecc/data/sta/gcd.rpt.json"
    assert n1["source_refs"]["route"] == "route_ecc/output/gcd_route.def"

    place_nets = [
        json.loads(line)
        for line in (foundation_dir / "vectors" / "nets" / "place.jsonl").read_text().splitlines()
    ]
    place_n1 = next(row for row in place_nets if row["net_key"] == "n1")
    assert place_n1["route_analysis"] is None
    assert (
        place_n1["null_reason"]["route_analysis"] == "route_only_not_available_for_preroute_stage"
    )
    assert place_n1["progressive_metadata"]["route_only_oracle"] is False
    assert "final_overflow" not in json.dumps(place_n1["patch_anchor"])

    wires = [
        json.loads(line)
        for line in (foundation_dir / "vectors" / "wires" / "route.jsonl").read_text().splitlines()
    ]
    wire = next(
        row
        for row in wires
        if row["identity"]["net_key"] == "n1" and row["identity"]["segment_kind"] == "wire_segment"
    )
    assert list(wire) == [
        "id",
        "stage",
        "wire_key",
        "source",
        "identity",
        "geometry",
        "layer_context",
        "track_context",
        "capacity_context",
        "patch_anchor",
        "patch_intersections",
        "net_context",
        "endpoint_context",
        "timing_context",
        "route_context",
        "via_context",
        "progressive_metadata",
        "source_refs",
        "null_reason",
    ]
    assert wire["wire_key"].startswith("route:NETS:n1:")
    assert wire["identity"]["wire_class"] == "signal"
    assert wire["geometry"]["segment_kind"] == "wire_segment"
    assert wire["geometry"]["bbox"] is not None
    assert wire["geometry"]["length"] == 200.0
    assert wire["geometry"]["width"] is None
    assert wire["patch_intersections"]
    assert sum(item["length"] for item in wire["patch_intersections"]) == wire["geometry"]["length"]
    primary_patch = next(
        patch
        for patch in json.loads((foundation_dir / "canonical_grid.json").read_text())["patches"]
        if patch["bbox"]["llx"] <= wire["geometry"]["center"]["x"] < patch["bbox"]["urx"]
        and patch["bbox"]["lly"] <= wire["geometry"]["center"]["y"] < patch["bbox"]["ury"]
    )
    assert wire["patch_anchor"]["primary_patch_id"] == primary_patch["patch_id"]
    assert any(
        item["patch_id"] == primary_patch["patch_id"] for item in wire["patch_intersections"]
    )
    assert sum(1 for item in wire["patch_intersections"] if item["is_primary_patch"]) == 1
    assert (
        next(item for item in wire["patch_intersections"] if item["is_primary_patch"])["patch_id"]
        == primary_patch["patch_id"]
    )
    assert wire["patch_anchor"]["anchor_source"] == "segment_midpoint"
    assert {"local_cell_density", "local_pin_density", "local_rudy", "local_egr_overflow"} <= set(
        wire["patch_anchor"]
    )
    assert {
        "layer",
        "layer_index",
        "routing_direction_preference",
        "pitch",
        "width_default",
        "is_preferred_direction",
        "source",
    } <= set(wire["layer_context"])
    assert wire["layer_context"]["routing_direction_preference"] == "horizontal"
    assert {
        "available",
        "track_axis",
        "is_on_track",
        "nearest_track_distance",
        "track_count",
        "track_step",
        "null_reason",
    } <= set(wire["track_context"])
    assert wire["track_context"]["available"] is True
    assert wire["track_context"]["is_on_track"] is True
    assert {
        "available",
        "patch_layer_demand",
        "patch_layer_capacity",
        "patch_layer_utilization",
        "layer_demand_capacity_ratio",
        "source",
    } <= set(wire["capacity_context"])
    assert wire["capacity_context"]["available"] is True
    assert wire["net_context"]["terminal_count"] >= 2
    assert wire["net_context"]["net_total_routed_length"] == 800.0
    assert wire["net_context"]["net_via_count"] == 1
    assert wire["route_context"]["route_only_oracle"] is True
    assert wire["route_context"]["local_final_overflow"] == 3.0
    assert wire["route_context"]["nearby_wire_count"] >= 1
    assert wire["route_context"]["nearby_via_count"] >= 0
    assert wire["route_context"]["source"] == "routed_def_reconstruction"
    assert wire["source_refs"]["def_section"] == "NETS"
    assert wire["source_refs"]["route"] == "routed_def_reconstruction"
    assert wire["null_reason"]["geometry_width"] == "def_route_missing_width"
    assert {
        "available_from_stage",
        "is_new_routed_geometry",
        "exists_same_geometry_in_prev_stage",
        "net_exists_in_prev_stage",
        "route_only_oracle",
        "tracking_scope",
    } <= set(wire["progressive_metadata"])
    assert wire["progressive_metadata"]["route_only_oracle"] is True
    assert wire["progressive_metadata"]["tracking_scope"] == "stage_local_wire_geometry"

    via_wire = next(row for row in wires if row["identity"]["segment_kind"] == "via")
    assert via_wire["via_context"]["via_name"] == "VIA23"
    assert via_wire["via_context"]["cut_layer"] == "VIA2"
    assert via_wire["via_context"]["lower_layer"] == "MET2"
    assert via_wire["via_context"]["upper_layer"] == "MET3"
    assert via_wire["via_context"]["layer_transition"] == "MET2->MET3"
    assert via_wire["via_context"]["via_source"] in {
        "def_routed_wires",
        "vectors_tech_vias",
        "heuristic_via_name_rule",
    }

    place_wires = [
        json.loads(line)
        for line in (foundation_dir / "vectors" / "wires" / "Floorplan.jsonl")
        .read_text()
        .splitlines()
    ]
    assert place_wires[0]["route_context"] is None
    assert place_wires[0]["null_reason"]["route_context"] == "not_route_stage"
    assert place_wires[0]["progressive_metadata"]["route_only_oracle"] is False
    assert "route_context" not in json.dumps(place_wires[0]["patch_anchor"])
    assert all(
        row["identity"]["wire_class"] in {"signal", "clock", "power_ground", "special"}
        for row in wires + place_wires
    )
    assert any(row["identity"]["segment_kind"] == "wire_segment" for row in wires)

    quality = json.loads((foundation_dir / "quality.json").read_text(encoding="utf-8"))
    assert quality["wires"]["route"]["record_count"] == len(wires)
    assert quality["wires"]["route"]["route_context_coverage"] == 1.0
    assert quality["wires"]["route"]["patch_intersection_coverage"] == 1.0
    assert quality["wires"]["route"]["route_context_source"] == {
        "routed_def_reconstruction": len(wires)
    }

    pre_route_graphs = (foundation_dir / "vectors" / "routing_graphs" / "place.jsonl").read_text(
        encoding="utf-8"
    )
    assert pre_route_graphs == ""
    route_graphs = [
        json.loads(line)
        for line in (foundation_dir / "vectors" / "routing_graphs" / "route.jsonl")
        .read_text()
        .splitlines()
    ]
    graph = next(row for row in route_graphs if row["net_key"] == "n1")
    assert list(graph) == [
        "id",
        "stage",
        "graph_key",
        "net_key",
        "name",
        "source",
        "identity",
        "graph_semantics",
        "vertices",
        "edges",
        "patch_footprint",
        "graph_metrics",
        "terminal_matching",
        "timing_context",
        "route_context",
        "progressive_metadata",
        "source_refs",
        "coverage",
        "null_reason",
    ]
    assert graph["identity"]["has_routed_geometry"] is True
    assert graph["graph_semantics"]["topology_direction"] == "undirected"
    assert graph["graph_metrics"]["wire_edge_count"] > 0
    assert graph["graph_metrics"]["via_edge_count"] == 1
    assert graph["graph_metrics"]["total_routed_length"] == 800.0
    assert graph["graph_metrics"]["used_layers"] == ["MET2", "MET3"]
    assert graph["graph_metrics"]["layer_count"] == 2
    assert graph["graph_metrics"]["max_vertex_degree"] >= 1
    assert graph["graph_metrics"]["terminal_vertex_count"] >= 1
    assert graph["patch_footprint"]["touched_patch_count"] >= 1
    assert graph["patch_footprint"]["touched_patch_ids"]
    assert (
        graph["patch_footprint"]["dominant_patch_id"]
        in graph["patch_footprint"]["touched_patch_ids"]
    )
    assert graph["patch_footprint"]["total_routed_length_by_patch"]
    assert graph["patch_footprint"]["layer_usage_by_patch"]
    assert graph["patch_footprint"]["touched_layer_ids"] == ["MET2", "MET3"]
    assert isinstance(graph["patch_footprint"]["cross_patch"], bool)
    assert graph["terminal_matching"]["strategy"] == "exact_shape_then_nearest_same_net"
    assert graph["terminal_matching"]["expected_terminal_count"] >= 2
    assert graph["terminal_matching"]["matched_terminal_count"] >= 1
    assert graph["terminal_matching"]["terminal_match_rate"] is not None
    assert graph["route_context"]["route_only_oracle"] is True
    assert graph["route_context"]["source"] == "route_ecc/output/gcd_route.def"
    assert graph["route_context"]["total_routed_length"] == 800.0
    assert graph["route_context"]["via_count"] == 1
    assert graph["route_context"]["wire_segment_count"] == 4
    assert graph["progressive_metadata"] == {
        "available_from": "route",
        "created_stage": "route",
        "exists_before_route": False,
        "not_available_before_route": True,
        "route_only_oracle": True,
        "pre_route_placeholder_policy": "empty_stage_file",
    }
    assert graph["coverage"]["has_routed_geometry"] is True
    assert graph["coverage"]["wire_ref_count"] == graph["graph_metrics"]["wire_edge_count"]
    assert graph["coverage"]["via_ref_count"] == graph["graph_metrics"]["via_edge_count"]
    assert (
        graph["coverage"]["terminal_match_rate"]
        == graph["terminal_matching"]["terminal_match_rate"]
    )
    assert graph["coverage"]["edge_patch_intersection_coverage"] == 1.0
    assert (
        graph["coverage"]["connected_component_count"]
        == graph["graph_metrics"]["connected_component_count"]
    )
    assert "patch_intersection_count" not in graph["coverage"]
    assert "patch_count" not in graph["patch_footprint"]

    via_edge = next(edge for edge in graph["edges"] if edge["edge_kind"] == "via_transition")
    assert via_edge["edge_key"] == f"{graph['graph_key']}:e{via_edge['edge_id']}"
    assert via_edge["source_vertex_id"] != via_edge["target_vertex_id"]
    assert via_edge["geometry"]["start"]["layer"] == "MET2"
    assert via_edge["geometry"]["end"]["layer"] == "MET3"
    assert via_edge["geometry"]["direction"] == "point"
    assert via_edge["via_ref"] == {
        "via_name": "VIA23",
        "coordinate": {"x": 60.0, "y": 60.0},
        "from_layer": "MET2",
        "to_layer": "MET3",
    }
    assert via_edge["patch_intersections"][0]["layer"] == "MET2/MET3"
    assert via_edge["patch_intersections"][0]["intersection_kind"] == "via_point"
    assert via_edge["source_refs"]["def"] == "route_ecc/output/gcd_route.def"
    assert via_edge["null_reason"].get("wire_ref") == "via_transition_has_no_wire_segment_ref"

    wire_edge = next(edge for edge in graph["edges"] if edge["edge_kind"] == "wire_segment")
    assert wire_edge["source_vertex_id"] != wire_edge["target_vertex_id"]
    assert wire_edge["wire_ref"]["wire_key"].startswith("route:NETS:n1:")
    assert wire_edge["via_ref"] is None
    assert wire_edge["patch_intersections"][0]["layer"] == wire_edge["geometry"]["layer"]
    assert wire_edge["patch_intersections"][0]["intersection_kind"] == "segment_overlap"

    assert all("terminal_match" in vertex for vertex in graph["vertices"])
    assert all("source_refs" in vertex for vertex in graph["vertices"])
    assert all("null_reason" in vertex for vertex in graph["vertices"])
    assert all(
        len(vertex["incident_edge_ids"]) == len(set(vertex["incident_edge_ids"]))
        for vertex in graph["vertices"]
    )
    assert any(vertex["vertex_kind"] == "terminal_anchor" for vertex in graph["vertices"])
    assert any(vertex["vertex_kind"] == "via_point" for vertex in graph["vertices"])

    patches = [
        json.loads(line)
        for line in (foundation_dir / "vectors" / "patches" / "route.jsonl")
        .read_text()
        .splitlines()
    ]
    patch = patches[0]
    assert list(patch)[:19] == [
        "id",
        "stage",
        "patch_key",
        "source",
        "identity",
        "geometry",
        "local_density",
        "local_connectivity",
        "pre_route_estimators",
        "neighbor_context",
        "entity_refs",
        "timing_context",
        "electrical_context",
        "route_oracle",
        "label_refs",
        "drc_context",
        "progressive_metadata",
        "source_refs",
        "null_reason",
    ]
    assert patch["patch_key"] == "patch:0"
    assert patch["identity"]["grid_patch_count"] == 4
    assert patch["local_density"]["available_for_training_input"] is False
    assert patch["local_connectivity"]["available_for_training_input"] is False
    assert patch["pre_route_estimators"]["available_for_training_input"] is False
    assert patch["neighbor_context"]["available_for_training_input"] is False
    assert patch["neighbor_context"]["window_3x3_patch_ids"]
    assert patch["entity_refs"]["wire_count"] >= 1
    assert patch["route_oracle"]["route_only_oracle"] is True
    assert (
        patch["label_refs"]["route_native_demand_capacity"]
        == "labels/route_native_demand_capacity.jsonl#patch_id=0"
    )

    layers = json.loads(
        (foundation_dir / "vectors" / "tech" / "layers.json").read_text(encoding="utf-8")
    )
    cells = json.loads(
        (foundation_dir / "vectors" / "tech" / "cells.json").read_text(encoding="utf-8")
    )
    vias = json.loads(
        (foundation_dir / "vectors" / "tech" / "vias.json").read_text(encoding="utf-8")
    )
    tech_summary = json.loads(
        (foundation_dir / "vectors" / "tech" / "tech_summary.json").read_text(encoding="utf-8")
    )
    assert layers[0]["identity"]["name"] == layers[0]["name"]
    assert "routing_properties" in layers[0]
    assert cells[0]["identity"]["name"] == cells[0]["name"]
    assert cells[0]["usage_summary"]["instance_count"] >= 1
    assert vias[0]["identity"]["name"] == vias[0]["name"]
    assert "layer_stack" in vias[0]
    assert tech_summary["schema_version"] == "iccd_full_v1.tech.v1"
    assert tech_summary["profile"] == "iccd_full_v1"
    assert tech_summary["source_coverage"] == {
        "def_tracks": True,
        "rt_log_layers": True,
        "def_components": True,
        "def_vias": True,
        "lef": False,
        "liberty": False,
    }
    assert tech_summary["counts"] == {
        "layer_count": len(layers),
        "routing_layer_count": 2,
        "cut_layer_count": 1,
        "cell_count": len(cells),
        "via_count": len(vias),
        "stage_count": 5,
    }
    assert tech_summary["milestones"] == {
        "m1": "available",
        "m2": "planned",
        "liberty": "reserved_not_parsed",
    }

    met2 = next(layer for layer in layers if layer["name"] == "MET2")
    assert met2["identity"]["is_routing_layer"] is True
    assert met2["identity"]["is_cut_layer"] is False
    assert met2["routing_properties"]["pitch"] == 100.0
    assert met2["routing_properties"]["source"] == "def_tracks+rt_log"
    assert met2["capacity_summary"]["estimated_track_count"] == 1
    assert met2["capacity_summary"]["estimated_capacity"] == 0.01
    assert met2["capacity_summary"]["capacity_formula"] == "estimated_track_count / pitch"
    assert met2["capacity_summary"]["stage_track_variants"]
    assert (
        met2["capacity_summary"]["patch_capacity_ref"]
        == "foundation_data/ecc/vectors/patches/route.jsonl:native_demand_capacity_by_layer"
    )
    assert met2["stage_metadata"]["missing_stages"] == ["place", "CTS", "drc"]
    assert met2["stage_metadata"]["stage_sources"]["route"] == [
        "def_routed_wires",
        "def_tracks",
        "def_vias",
        "rt_log",
    ]
    assert met2["source_refs"]["def"][0]["section"] == "TRACKS"
    assert met2["source_refs"]["rt_log"][0]["parser"] == "rt_log"

    via2 = next(layer for layer in layers if layer["name"] == "VIA2")
    assert via2["identity"]["layer_type"] == "cut"
    assert via2["identity"]["is_cut_layer"] is True

    nand2 = next(cell for cell in cells if cell["name"] == "NAND2")
    assert nand2["identity"]["is_macro"] is False
    assert nand2["identity"]["is_physical_only"] is False
    assert nand2["classification"]["is_buffer_like"] is False
    assert nand2["classification"]["source"] == "heuristic_name_rule"
    assert nand2["physical_properties"]["size_source"] in {"missing", "lef_macro_size"}
    assert nand2["pin_summary"]["summary_source"] in {"def_net_terminals", "lef_macro_pins"}
    assert nand2["usage_summary"]["first_seen_stage"] == "Floorplan"
    assert nand2["usage_summary"]["route_only_usage"] is False
    assert nand2["stage_metadata"]["missing_stages"] == ["CTS", "drc"]

    via23 = next(via for via in vias if via["name"] == "VIA23")
    assert via23["identity"]["via_type"] == "fixed"
    assert via23["layer_stack"] == {
        "layers": ["MET2", "VIA2", "MET3"],
        "bottom_layer": "MET2",
        "cut_layer": "VIA2",
        "top_layer": "MET3",
        "stack_source": "def_via_layers",
    }
    assert via23["geometry"]["geometry_status"] == "name_only"
    assert via23["routing_properties"]["bottom_direction"] == "horizontal"
    assert via23["routing_properties"]["top_direction"] == "vertical"
    assert via23["routing_properties"]["is_direction_change"] is True
    assert via23["usage_summary"]["total_usage_count"] == 1
    assert via23["usage_summary"]["usage_source"] == "def_routed_wires"
    assert via23["usage_summary"]["route_only_usage"] is True
    assert via23["stage_metadata"]["stage_sources"]["route"] == ["def_routed_wires", "def_vias"]
    assert via23["source_refs"]["liberty"] is None
    assert via23["null_reason"]["geometry_bottom_rect"] == "via_geometry_not_available_from_def"


def test_routing_graph_records_follow_vec_routing_graph_schema(tmp_path: Path):
    ws = _make_workspace(tmp_path)

    FoundationExtractor(ws, profile="iccd_full_v1").extract(
        export_legacy_debug=True, stages=["place", "route"]
    )

    foundation_dir = ws / "foundation_data" / "ecc"
    assert (foundation_dir / "vectors" / "routing_graphs" / "place.jsonl").read_text(
        encoding="utf-8"
    ) == ""
    route_graphs = [
        json.loads(line)
        for line in (foundation_dir / "vectors" / "routing_graphs" / "route.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    graph = next(row for row in route_graphs if row["net_key"] == "n1")

    required_patch_fields = {
        "primary_patch_id",
        "dominant_patch_id",
        "touched_patch_ids",
        "touched_patch_count",
        "total_routed_length_by_patch",
        "layer_usage_by_patch",
        "touched_layer_ids",
        "cross_patch",
    }
    assert required_patch_fields.issubset(graph["patch_footprint"])
    assert "patch_count" not in graph["patch_footprint"]
    assert "length_by_patch" not in graph["patch_footprint"]

    required_metric_fields = {
        "vertex_count",
        "edge_count",
        "wire_edge_count",
        "via_edge_count",
        "branch_vertex_count",
        "terminal_vertex_count",
        "connected_component_count",
        "total_routed_length",
        "layer_count",
        "used_layers",
        "max_vertex_degree",
        "has_cycle",
    }
    assert required_metric_fields.issubset(graph["graph_metrics"])
    assert graph["graph_metrics"]["total_routed_length"] == 800.0
    assert graph["graph_metrics"]["via_edge_count"] == 1

    assert graph["terminal_matching"]["strategy"] == "exact_shape_then_nearest_same_net"
    assert graph["terminal_matching"]["expected_terminal_count"] >= 2
    assert graph["terminal_matching"]["terminal_match_rate"] is not None
    assert graph["progressive_metadata"]["available_from"] == "route"
    assert graph["progressive_metadata"]["not_available_before_route"] is True
    assert graph["route_context"]["source"] == "route_ecc/output/gcd_route.def"
    assert graph["coverage"]["edge_patch_intersection_coverage"] == 1.0

    assert all(
        {"terminal_match", "source_refs", "null_reason"}.issubset(vertex)
        for vertex in graph["vertices"]
    )
    assert all(
        {
            "edge_key",
            "source_vertex_id",
            "target_vertex_id",
            "wire_ref",
            "via_ref",
            "source_refs",
            "null_reason",
        }.issubset(edge)
        for edge in graph["edges"]
    )
    assert all(
        {"layer", "intersection_kind"}.issubset(item)
        for edge in graph["edges"]
        for item in edge["patch_intersections"]
    )

    via_edge = next(edge for edge in graph["edges"] if edge["edge_kind"] == "via_transition")
    assert via_edge["source_vertex_id"] != via_edge["target_vertex_id"]
    assert via_edge["geometry"]["start"]["layer"] == "MET2"
    assert via_edge["geometry"]["end"]["layer"] == "MET3"
    assert via_edge["via_ref"]["from_layer"] == "MET2"
    assert via_edge["via_ref"]["to_layer"] == "MET3"
    assert all(
        len(vertex["incident_edge_ids"]) == len(set(vertex["incident_edge_ids"]))
        for vertex in graph["vertices"]
    )


def _append_large_route_nets(ws: Path, *, count: int = 1005) -> None:
    shutil_target = ws / "route_ecc" / "data" / "sta"
    if shutil_target.exists():
        import shutil

        shutil.rmtree(shutil_target)
    net_lines = []
    for idx in range(count):
        y = idx % 200
        net_lines.append(f"- n_large_{idx} ( U1 A ) ( PIN OUT )")
        net_lines.append(f"  + ROUTED MET2 ( 0 {y} ) ( 200 * )")
        net_lines.append("  ;")
    _write_text(
        ws / "route_ecc" / "output" / "gcd_route.def",
        "\n".join(
            [
                "VERSION 5.8 ;",
                'DIVIDERCHAR "/" ;',
                'BUSBITCHARS "[]" ;',
                "DESIGN gcd ;",
                "UNITS DISTANCE MICRONS 1000 ;",
                "DIEAREA ( 0 0 ) ( 200 200 ) ;",
                "TRACKS Y 50 DO 1 STEP 100 LAYER MET2 ;",
                "TRACKS X 50 DO 1 STEP 100 LAYER MET3 ;",
                "GCELLGRID X 0 DO 3 STEP 100 ;",
                "GCELLGRID Y 0 DO 3 STEP 100 ;",
                "VIAS 1 ;",
                "- VIA23 + LAYERS MET2 VIA2 MET3 ;",
                "END VIAS",
                "COMPONENTS 1 ;",
                "- U1 NAND2 + PLACED ( 10 20 ) N ;",
                "END COMPONENTS",
                "PINS 1 ;",
                "- OUT + NET n_large_0 + DIRECTION OUTPUT + PLACED ( 180 50 ) N ;",
                "END PINS",
                f"NETS {count} ;",
                *net_lines,
                "END NETS",
                "END DESIGN",
            ]
        )
        + "\n",
    )


def test_large_route_design_does_not_degrade_source_backed_tables(tmp_path: Path):
    import pyarrow.parquet as pq

    ws = _make_workspace(tmp_path)
    _append_large_route_nets(ws)

    result = FoundationExtractor(ws, profile="iccd_full_v1").extract(stages=["route"])
    foundation_dir = result.foundation_dir
    quality = json.loads((foundation_dir / "quality.json").read_text(encoding="utf-8"))
    manifest = json.loads((foundation_dir / "manifest.json").read_text(encoding="utf-8"))

    assert "route_wire_count_exceeds_in_memory_table_threshold" not in json.dumps(quality)
    assert not quality.get("large_design_mode", {}).get("degraded_tables")
    for table_name in [
        "wire_segments",
        "wire_patch_intersections",
        "patch_entity_refs",
        "routing_vertices",
        "routing_edges",
    ]:
        table = pq.read_table(foundation_dir / manifest["tables"][table_name]["path"])
        assert table.num_rows > 0, table_name


def test_large_design_quality_distinguishes_missing_source_from_perf_degrade(tmp_path: Path):
    import pyarrow.parquet as pq

    ws = _make_workspace(tmp_path)
    _append_large_route_nets(ws)

    result = FoundationExtractor(ws, profile="iccd_full_v1").extract(stages=["route"])
    foundation_dir = result.foundation_dir
    quality = json.loads((foundation_dir / "quality.json").read_text(encoding="utf-8"))
    manifest = json.loads((foundation_dir / "manifest.json").read_text(encoding="utf-8"))

    timing_paths = pq.read_table(foundation_dir / manifest["tables"]["timing_paths"]["path"])
    assert timing_paths.num_rows == 0
    assert quality["availability"]["timing_paths"]["route"] in {
        "missing",
        "missing_source",
        "missing_timing_source",
        "missing_timing_paths_source",
        "sta_report_missing_or_empty",
    }
    assert quality["null_reason"]["timing_paths"]["route"] in {
        "missing",
        "missing_source",
        "missing_timing_source",
        "missing_timing_paths_source",
        "sta_report_missing_or_empty",
    }
    assert "route_wire_count_exceeds_in_memory_table_threshold" not in json.dumps(quality)
    source_backed = [
        "instance_stage_state",
        "pin_stage_state",
        "wire_segments",
        "wire_patch_intersections",
        "patch_entity_refs",
        "routing_vertices",
        "routing_edges",
    ]
    for table_name in source_backed:
        table = pq.read_table(foundation_dir / manifest["tables"][table_name]["path"])
        assert table.num_rows > 0, table_name


def test_routing_graph_strict_blockers_are_enforced(tmp_path: Path):
    ws = _make_workspace(tmp_path)
    _write_text(
        ws / "route_ecc" / "output" / "gcd_route.def",
        """
VERSION 5.8 ;
DIVIDERCHAR "/" ;
BUSBITCHARS "[]" ;
DESIGN gcd ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 200 200 ) ;
TRACKS Y 50 DO 1 STEP 100 LAYER MET2 ;
TRACKS X 50 DO 1 STEP 100 LAYER MET3 ;
GCELLGRID X 0 DO 3 STEP 100 ;
GCELLGRID Y 0 DO 3 STEP 100 ;
COMPONENTS 1 ;
- U1 NAND2 + PLACED ( 10 20 ) N ;
END COMPONENTS
PINS 1 ;
- OUT + NET n_boundary + DIRECTION OUTPUT + PLACED ( 180 50 ) N ;
END PINS
NETS 3 ;
- n_skip ( U1 B ) ( U1 Y ) ;
- n_boundary ( U1 A ) ( PIN OUT )
  + ROUTED MET2 ( 120 10 ) ( * 70 )
  ;
- n_after ( U1 Y ) ( PIN OUT )
  + ROUTED MET3 ( 10 90 ) ( 70 * )
  ;
END NETS
END DESIGN
""".strip()
        + "\n",
    )

    FoundationExtractor(ws, profile="iccd_full_v1").extract(
        export_legacy_debug=True, stages=["route", "drc"]
    )

    foundation_dir = ws / "foundation_data" / "ecc"
    route_graphs = [
        json.loads(line)
        for line in (foundation_dir / "vectors" / "routing_graphs" / "route.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]

    boundary = next(row for row in route_graphs if row["net_key"] == "n_boundary")
    assert boundary["id"] == 0
    assert boundary["source_refs"]["def_net_index"] == 1
    edge = boundary["edges"][0]
    assert edge["geometry"]["length"] == 60.0
    assert sum(item["length"] for item in edge["patch_intersections"]) == edge["geometry"]["length"]
    assert (
        sum(
            float(value)
            for value in boundary["patch_footprint"]["total_routed_length_by_patch"].values()
        )
        == boundary["graph_metrics"]["total_routed_length"]
    )

    after = next(row for row in route_graphs if row["net_key"] == "n_after")
    assert after["id"] == 1
    assert after["source_refs"]["def_net_index"] == 2

    quality = json.loads((foundation_dir / "quality.json").read_text(encoding="utf-8"))
    assert quality["availability"]["routing_graphs"]["drc"] == "optional_post_route_snapshot"
    assert quality["null_reason"]["routing_graphs"]["drc"] == "optional_post_route_snapshot"
