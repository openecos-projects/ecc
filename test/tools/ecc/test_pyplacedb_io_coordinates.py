from textwrap import dedent

import pytest


def test_missing_io_coordinates_follow_pad_pins(tmp_path):
    ecc_py = pytest.importorskip("ecc_tools_bin.ecc_py")
    tech_lef = tmp_path / "tech.lef"
    tech_lef.write_text(
        dedent("""
        VERSION 5.8 ;
        BUSBITCHARS "[]" ;
        DIVIDERCHAR "/" ;
        UNITS
          DATABASE MICRONS 1000 ;
        END UNITS
        MANUFACTURINGGRID 0.001 ;
        LAYER M1
          TYPE ROUTING ;
          DIRECTION HORIZONTAL ;
          PITCH 1 ;
          WIDTH 1 ;
          SPACING 1 ;
        END M1
        SITE core
          CLASS CORE ;
          SIZE 1 BY 1 ;
          SYMMETRY X Y ;
        END core
        END LIBRARY
    """)
    )
    cells_lef = tmp_path / "cells.lef"
    cells_lef.write_text(
        dedent("""
        VERSION 5.8 ;
        MACRO IO_PAD
          CLASS PAD ;
          ORIGIN 0 0 ;
          SIZE 10 BY 20 ;
          SYMMETRY X Y R90 ;
          PIN PAD
            DIRECTION INOUT ;
            PORT
              LAYER M1 ;
                RECT 2 3 4 5 ;
            END
          END PAD
          PIN C
            DIRECTION INPUT ;
            PORT
              LAYER M1 ;
                RECT 6 7 8 9 ;
            END
          END C
        END IO_PAD
        MACRO CORE
          CLASS CORE ;
          ORIGIN 0 0 ;
          SIZE 1 BY 1 ;
          SITE core ;
          PIN A
            DIRECTION INPUT ;
            PORT
              LAYER M1 ;
                RECT 0 0 1 1 ;
            END
          END A
        END CORE
        END LIBRARY
    """)
    )
    design_def = tmp_path / "design.def"
    design_def.write_text(
        dedent("""
        VERSION 5.8 ;
        DIVIDERCHAR "/" ;
        BUSBITCHARS "[]" ;
        DESIGN io_coordinates ;
        UNITS DISTANCE MICRONS 1000 ;
        DIEAREA ( 0 0 ) ( 200000 100000 ) ;
        ROW ROW0 core 0 0 N DO 200 BY 1 STEP 1000 0 ;
        COMPONENTS 7 ;
        - pad_n IO_PAD + PLACED ( 10000 20000 ) N ;
        - pad_s IO_PAD + PLACED ( 30000 20000 ) S ;
        - pad_e IO_PAD + PLACED ( 50000 20000 ) E ;
        - pad_w IO_PAD + PLACED ( 70000 20000 ) W ;
        - pad_layer IO_PAD + PLACED ( 90000 20000 ) N ;
        - pad_port IO_PAD + PLACED ( 110000 20000 ) N ;
        - logic CORE + PLACED ( 130000 0 ) N ;
        END COMPONENTS
        PINS 8 ;
        - io_n + NET n + DIRECTION INPUT + USE SIGNAL ;
        - io_s + NET s + DIRECTION INPUT + USE SIGNAL ;
        - io_e + NET e + DIRECTION INPUT + USE SIGNAL ;
        - io_w + NET w + DIRECTION INPUT + USE SIGNAL ;
        - io_layer + NET layer + DIRECTION INPUT + USE SIGNAL
          + LAYER M1 ( 0 0 ) ( 1 1 ) + FIXED ( 150000 30000 ) N ;
        - io_port + NET port + DIRECTION INPUT + USE SIGNAL
          + PORT + LAYER M1 ( 0 0 ) ( 1 1 ) + FIXED ( 160000 30000 ) N ;
        - io_only + NET direct + DIRECTION INPUT + USE SIGNAL
          + LAYER M1 ( 0 0 ) ( 1 1 ) + FIXED ( 170000 30000 ) N ;
        - io_core_side + NET core_side + DIRECTION INPUT + USE SIGNAL ;
        END PINS
        NETS 8 ;
        - n ( PIN io_n ) ( pad_n PAD ) ;
        - s ( PIN io_s ) ( pad_s PAD ) ;
        - e ( PIN io_e ) ( pad_e PAD ) ;
        - w ( PIN io_w ) ( pad_w PAD ) ;
        - layer ( PIN io_layer ) ( pad_layer PAD ) ;
        - port ( PIN io_port ) ( pad_port PAD ) ;
        - direct ( PIN io_only ) ( logic A ) ;
        - core_side ( PIN io_core_side ) ( pad_n C ) ;
        END NETS
        END DESIGN
    """)
    )
    ecc_py.reset_data()
    try:
        assert ecc_py.tech_lef_init(str(tech_lef))
        assert ecc_py.lef_init([str(cells_lef)])
        assert ecc_py.def_init(str(design_def))
        before_def = tmp_path / "before.def"
        assert ecc_py.def_save(str(before_def))
        db = ecc_py.pydb(ecc_py.get_dmInst(), 2, 2, False, False)  # noqa: FBT003
        nodes = dict(zip(db.node_names, zip(db.node_x, db.node_y, strict=True), strict=True))
        assert {name: xy for name, xy in nodes.items() if name.startswith("io_")} == {
            "io_n": (13000, 24000),
            "io_s": (37000, 36000),
            "io_e": (54000, 27000),
            "io_w": (86000, 23000),
            "io_layer": (150000, 30000),
            "io_port": (160000, 30000),
            "io_only": (170000, 30000),
            "io_core_side": (-1, -1),
        }
        after_def = tmp_path / "after.def"
        assert ecc_py.def_save(str(after_def))
        assert after_def.read_text() == before_def.read_text()
    finally:
        ecc_py.reset_data()
