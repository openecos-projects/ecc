import gzip
import json

import pytest

from chipcompiler.tools.replay_events import export_phase
from chipcompiler.tools.replay_harden import lef_views, liberty_views


def test_abstract_uses_compressed_def_units_and_ecc_absolute_rectangles(tmp_path):
    design = tmp_path / "design.def.gz"
    design.write_bytes(
        gzip.compress(b"UNITS DISTANCE MICRONS 2000 ;\nDIEAREA ( 1000 4000 ) ( 21000 44000 ) ;")
    )
    lef = tmp_path / "design.lef"
    lef.write_text("""MACRO design
ORIGIN 0.0 0.0 ;
SIZE 10 BY 20 ;
PIN A
PORT
LAYER M2 ;
RECT 0.5 2 0.6 2.1 ;
END
END A
OBS
LAYER M1 ;
RECT 1 3 2 4 ;
END
END design
""")
    views = lef_views(lef, design)
    assert [view["items"][0]["bboxes"] for view in views] == [
        [[1000, 4000, 21000, 44000]],
        [[1000, 4000, 1200, 4200]],
        [[2000, 6000, 4000, 8000]],
    ]


def test_liberty_nested_tables_preserve_port_and_arc_context(tmp_path):
    lib = tmp_path / "design.lib"
    lib.write_text("""library(test) { time_unit : "1ns"; nom_voltage : 1.2;
cell(design) { pin(A) { direction : input; capacitance : 0.02; }
pin(Z) { direction : output; timing() { related_pin : "A";
timing_sense : positive_unate; timing_type : combinational;
cell_rise(table) { index_1("1, 2"); values("0.1, 0.2"); } } } } }""")
    view = liberty_views(lib)[0]
    assert view["items"] == [
        {
            "label": "A",
            "pins": ["A"],
            "details": {"arcs": [], "direction": "input", "capacitance": "0.02"},
        },
        {
            "label": "Z",
            "pins": ["Z"],
            "details": {
                "arcs": [
                    {
                        "related_pin": "A",
                        "timing_sense": "positive_unate",
                        "timing_type": "combinational",
                    }
                ],
                "direction": "output",
            },
        },
    ]
    assert view["summary"] == {"time_unit": "1ns", "nom_voltage": "1.2", "ports": 2, "arcs": 1}


def test_export_events_are_opt_in_and_do_not_swallow_export_errors(tmp_path, monkeypatch):
    monkeypatch.delenv("ECC_REPLAY_CAPTURE_DIR", raising=False)
    with export_phase("lef", str(tmp_path / "absent")):
        pass
    assert list(tmp_path.iterdir()) == []
    monkeypatch.setenv("ECC_REPLAY_CAPTURE_DIR", str(tmp_path))
    monkeypatch.setenv("ECC_REPLAY_START_NS", "0")
    with (
        pytest.raises(RuntimeError, match="export failure"),
        export_phase("lef", str(tmp_path / "absent")),
    ):
        raise RuntimeError("export failure")
    events = sorted(
        (json.loads(path.read_text()) for path in tmp_path.glob("*.json")),
        key=lambda e: e["sequence"],
    )
    assert [event["phase"] for event in events] == ["lef_export_started", "lef_export_failed"]
    assert all(event["scope"] == "patch" and event["objects"] == {} for event in events)
