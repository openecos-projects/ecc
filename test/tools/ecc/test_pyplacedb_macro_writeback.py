import gzip
import json
from pathlib import Path
from textwrap import dedent

import numpy as np
import pytest


def _new_place_db(ecc_py):
    return ecc_py.pydb(ecc_py.get_dmInst(), 2, 2, False, False)  # noqa: FBT003


def _macro(name: str, cell_class: str, size: tuple[int, int], pin_name: str) -> str:
    width, height = size
    return dedent(
        f"""
        MACRO {name}
          CLASS {cell_class} ;
          ORIGIN 0 0 ;
          SIZE {width} BY {height} ;
          SYMMETRY X Y ;
          SITE core ;
          PIN {pin_name}
            DIRECTION INPUT ;
            PORT
              LAYER M1 ;
                RECT 0 0 1 1 ;
            END
          END {pin_name}
        END {name}
        """
    )


@pytest.fixture
def mixed_macro_place_db(tmp_path):
    ecc_py = pytest.importorskip("ecc_tools_bin.ecc_py")

    tech_lef = tmp_path / "tech.lef"
    tech_lef.write_text(
        dedent(
            """
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
            LAYER M2
              TYPE ROUTING ;
              DIRECTION VERTICAL ;
              PITCH 1 ;
              WIDTH 1 ;
              SPACING 1 ;
            END M2
            SITE core
              CLASS CORE ;
              SIZE 1 BY 1 ;
              SYMMETRY X Y ;
            END core
            END LIBRARY
            """
        ),
        encoding="utf-8",
    )

    cells_lef = tmp_path / "cells.lef"
    cells_lef.write_text(
        "VERSION 5.8 ;\n"
        'BUSBITCHARS "[]" ;\n'
        'DIVIDERCHAR "/" ;\n'
        + _macro("HARD_BLOCK", "BLOCK", (10, 10), "P")
        + _macro("LARGE_CORE", "CORE", (100, 10), "A")
        + _macro("CORE", "CORE", (1, 1), "A")
        + "END LIBRARY\n",
        encoding="utf-8",
    )

    rows = "".join(
        f"ROW ROW{row} core 0 {row * 1000} N DO 300 BY 1 STEP 1000 0 ;\n" for row in range(20)
    )
    design_def = tmp_path / "design.def"
    design_def.write_text(
        dedent(
            """
            VERSION 5.8 ;
            DIVIDERCHAR "/" ;
            BUSBITCHARS "[]" ;
            DESIGN macro_status_test ;
            UNITS DISTANCE MICRONS 1000 ;
            DIEAREA ( 0 0 ) ( 300000 20000 ) ;
            """
        )
        + rows
        + dedent(
            """
            COMPONENTS 7 ;
            - macro_none HARD_BLOCK ;
            - macro_unplaced HARD_BLOCK + UNPLACED ;
            - macro_placed HARD_BLOCK + PLACED ( 20000 0 ) N ;
            - macro_fixed HARD_BLOCK + FIXED ( 40000 0 ) N ;
            - macro_cover HARD_BLOCK + COVER ( 60000 0 ) N ;
            - large_core LARGE_CORE + PLACED ( 80000 0 ) N ;
            - core_unplaced CORE + UNPLACED ;
            END COMPONENTS
            PINS 1 ;
            - input + NET signal + DIRECTION INPUT + USE SIGNAL
              + LAYER M1 ( 0 0 ) ( 1 1 ) + FIXED ( 0 0 ) N ;
            END PINS
            NETS 1 ;
            - signal ( PIN input ) ( macro_none P ) ( macro_unplaced P ) ( macro_placed P )
              ( macro_fixed P ) ( macro_cover P ) ( large_core A ) ( core_unplaced A ) ;
            END NETS
            BLOCKAGES 1 ;
            - PLACEMENT RECT ( 250000 10000 ) ( 260000 20000 ) ;
            END BLOCKAGES
            END DESIGN
            """
        ),
        encoding="utf-8",
    )

    ecc_py.reset_data()
    assert ecc_py.tech_lef_init(str(tech_lef))
    assert ecc_py.lef_init([str(cells_lef)])
    assert ecc_py.def_init(str(design_def))
    try:
        yield ecc_py, _new_place_db(ecc_py), tmp_path
    finally:
        ecc_py.reset_data()


def test_pyplacedb_freezes_only_none_and_unplaced_hard_macros_as_candidates(
    mixed_macro_place_db,
):
    _, place_db, _ = mixed_macro_place_db
    names = list(place_db.node_names)
    hard_macros = dict(zip(names, place_db.node_is_hard_macro, strict=True))
    candidates = dict(zip(names, place_db.macro_writeback_candidate, strict=True))

    assert {name for name, is_macro in hard_macros.items() if is_macro} == {
        "macro_none",
        "macro_unplaced",
        "macro_placed",
        "macro_fixed",
        "macro_cover",
    }
    assert {name for name, is_candidate in candidates.items() if is_candidate} == {
        "macro_none",
        "macro_unplaced",
    }
    assert hard_macros["input"] is False
    assert candidates["input"] is False
    blockage_names = [name for name in names if name.startswith("blockage")]
    assert len(blockage_names) == 1
    assert hard_macros[blockage_names[0]] is False
    assert candidates[blockage_names[0]] is False


def test_macro_writeback_commits_only_frozen_candidates(mixed_macro_place_db):
    ecc_py, place_db, tmp_path = mixed_macro_place_db
    names = list(place_db.node_names)
    candidate_ids = np.flatnonzero(place_db.macro_writeback_candidate)
    num_movable_nodes = place_db.num_nodes - place_db.num_terminals - place_db.num_terminal_NIs
    before = {
        name: (place_db.node_x[node_id], place_db.node_y[node_id], place_db.node_orient[node_id])
        for node_id, name in enumerate(names)
    }

    node_x = np.asarray(place_db.node_x, dtype=np.float32)[:num_movable_nodes].copy()
    node_y = np.asarray(place_db.node_y, dtype=np.float32)[:num_movable_nodes].copy()
    node_x[:] = np.arange(num_movable_nodes, dtype=np.float32) * 1000 + 100000
    node_y[:] = 1000
    expected_candidate_locations = {
        names[node_id]: (int(node_x[node_id]), int(node_y[node_id])) for node_id in candidate_ids
    }

    assert place_db.write_macro_placement_back(node_x, node_y) == len(candidate_ids)

    updated_db = _new_place_db(ecc_py)
    updated_names = list(updated_db.node_names)
    after = {
        name: (
            updated_db.node_x[node_id],
            updated_db.node_y[node_id],
            updated_db.node_orient[node_id],
        )
        for node_id, name in enumerate(updated_names)
    }
    for name, location in expected_candidate_locations.items():
        assert after[name][:2] == location
        assert after[name][2] == before[name][2]
    assert {
        name: state for name, state in after.items() if name not in expected_candidate_locations
    } == {name: state for name, state in before.items() if name not in expected_candidate_locations}
    assert updated_db.num_terminals == place_db.num_terminals + len(candidate_ids)

    output_def = tmp_path / "macro_writeback.def"
    assert ecc_py.def_save(str(output_def))
    output_text = output_def.read_text(encoding="utf-8")
    for name, (x, y) in expected_candidate_locations.items():
        component_start = output_text.index(f"- {name} ")
        component_end = output_text.index(";", component_start)
        component = output_text[component_start:component_end]
        assert f"+ PLACED ( {x} {y} )" in component


def test_macro_writeback_validates_every_candidate_before_mutating(mixed_macro_place_db):
    ecc_py, place_db, _ = mixed_macro_place_db
    names = list(place_db.node_names)
    macro_none_id = names.index("macro_none")
    before = (
        place_db.node_x[macro_none_id],
        place_db.node_y[macro_none_id],
        place_db.node_orient[macro_none_id],
    )
    num_movable_nodes = place_db.num_nodes - place_db.num_terminals - place_db.num_terminal_NIs
    node_x = np.asarray(place_db.node_x, dtype=np.float32)[:num_movable_nodes].copy()
    node_y = np.asarray(place_db.node_y, dtype=np.float32)[:num_movable_nodes].copy()
    node_x[macro_none_id] = 125000
    node_y[macro_none_id] = 1000

    assert ecc_py.delete_inst("macro_unplaced")
    with pytest.raises(RuntimeError, match="no longer exists"):
        place_db.write_macro_placement_back(node_x, node_y)

    updated_db = _new_place_db(ecc_py)
    updated_names = list(updated_db.node_names)
    updated_id = updated_names.index("macro_none")
    assert (
        updated_db.node_x[updated_id],
        updated_db.node_y[updated_id],
        updated_db.node_orient[updated_id],
    ) == before
    assert updated_db.macro_writeback_candidate[updated_id]


def test_macro_writeback_rejects_float32_value_above_int32_max(mixed_macro_place_db):
    ecc_py, place_db, _ = mixed_macro_place_db
    names = list(place_db.node_names)
    macro_none_id = names.index("macro_none")
    before = (place_db.node_x[macro_none_id], place_db.node_y[macro_none_id])
    num_movable_nodes = place_db.num_nodes - place_db.num_terminals - place_db.num_terminal_NIs
    node_x = np.asarray(place_db.node_x, dtype=np.float32)[:num_movable_nodes].copy()
    node_y = np.asarray(place_db.node_y, dtype=np.float32)[:num_movable_nodes].copy()
    node_x[macro_none_id] = np.float32(np.iinfo(np.int32).max)

    assert node_x[macro_none_id] == np.float32(2**31)
    with pytest.raises(ValueError, match="int32-compatible"):
        place_db.write_macro_placement_back(node_x, node_y)

    updated_db = _new_place_db(ecc_py)
    updated_names = list(updated_db.node_names)
    updated_id = updated_names.index("macro_none")
    assert (updated_db.node_x[updated_id], updated_db.node_y[updated_id]) == before


def test_macro_writeback_rejects_replacement_with_same_instance_name(mixed_macro_place_db):
    ecc_py, place_db, _ = mixed_macro_place_db
    names = list(place_db.node_names)
    macro_unplaced_id = names.index("macro_unplaced")
    num_movable_nodes = place_db.num_nodes - place_db.num_terminals - place_db.num_terminal_NIs
    node_x = np.asarray(place_db.node_x, dtype=np.float32)[:num_movable_nodes].copy()
    node_y = np.asarray(place_db.node_y, dtype=np.float32)[:num_movable_nodes].copy()
    node_x[macro_unplaced_id] = 125000
    node_y[macro_unplaced_id] = 1000

    assert ecc_py.delete_inst("macro_unplaced")
    assert ecc_py.create_inst("macro_unplaced", "HARD_BLOCK", 222000, 2000, "N")
    with pytest.raises(RuntimeError, match="same instance"):
        place_db.write_macro_placement_back(node_x, node_y)

    updated_db = _new_place_db(ecc_py)
    updated_names = list(updated_db.node_names)
    replacement_id = updated_names.index("macro_unplaced")
    assert (updated_db.node_x[replacement_id], updated_db.node_y[replacement_id]) == (222000, 2000)


def test_macro_placement_runner_writes_complete_selective_snapshot(
    mixed_macro_place_db, monkeypatch
):
    from chipcompiler.data import OriginDesign, StepEnum, Workspace
    from chipcompiler.tools.ecc.module import ECCToolsModule
    from chipcompiler.tools.ecc_dreamplace import builder, runner

    _, _, tmp_path = mixed_macro_place_db
    source_config = (
        Path(__file__).resolve().parents[3]
        / "chipcompiler/tools/ecc_dreamplace/configs/dreamplace_ecc.json"
    )
    config = json.loads(source_config.read_text(encoding="utf-8"))
    config.update(
        {
            "macro_halo_x": 1000,
            "macro_halo_y": 1000,
            "macro_pin_halo_x": -1,
            "macro_pin_halo_y": -1,
            "cell_padding_x": 0,
            "enable_fillers": 0,
            "auto_adjust_bins": 0,
            "num_bins_x": 4,
            "num_bins_y": 4,
            "num_threads": 1,
            "global_place_stages": [
                {
                    **config["global_place_stages"][0],
                    "iteration": 5,
                }
            ],
            "stop_overflow": 1.0,
        }
    )
    config_path = tmp_path / "dreamplace.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    workspace = Workspace(
        directory=tmp_path / "workspace",
        design=OriginDesign(name="macro_status_test", top_module="macro_status_test"),
        config={"dreamplace": config_path},
    )
    step = builder.build_step(
        workspace=workspace,
        step_name=StepEnum.MACRO_PLACEMENT.value,
        input_def=tmp_path / "design.def",
        input_verilog=None,
    )
    builder.build_step_space(step)
    monkeypatch.setattr(runner, "run_analysis", lambda **_kwargs: None)

    assert runner.run_macro_placement(
        workspace=workspace,
        step=step,
        ecc_module=ECCToolsModule(),
    )

    for path in (step.output.def_, step.output.verilog, step.output.gds):
        assert path is not None
        assert path.is_file()
        assert path.stat().st_size > 0
    assert step.output.db is not None
    assert step.output.db.is_dir()
    assert step.output.geometry_manifest is not None
    assert step.output.geometry_manifest.is_file()
    with gzip.open(step.output.def_, "rt", encoding="utf-8") as output:
        output_def = output.read()
    for name in ("macro_none", "macro_unplaced"):
        component_start = output_def.index(f"- {name} ")
        component_end = output_def.index(";", component_start)
        assert "+ PLACED" in output_def[component_start:component_end]
    core_start = output_def.index("- core_unplaced ")
    core_end = output_def.index(";", core_start)
    assert "+ UNPLACED" in output_def[core_start:core_end]


def test_macro_placement_engine_smoke_commits_candidates_as_fixed(mixed_macro_place_db):
    from dreamplace.Params import Params
    from dreamplace.Placer import PlacementEngine

    from chipcompiler.tools.ecc.module import ECCToolsModule

    ecc_py, place_db, tmp_path = mixed_macro_place_db
    input_nodes = {
        name: {
            "x": place_db.node_x[node_id],
            "y": place_db.node_y[node_id],
            "size_x": place_db.node_size_x[node_id],
            "size_y": place_db.node_size_y[node_id],
        }
        for node_id, name in enumerate(place_db.node_names)
        if place_db.macro_writeback_candidate[node_id]
    }
    config_path = (
        Path(__file__).resolve().parents[3]
        / "chipcompiler/tools/ecc_dreamplace/configs/dreamplace_ecc.json"
    )
    params = Params()
    params.fromJson(json.loads(config_path.read_text(encoding="utf-8")))
    params.macro_only = 1
    params.global_place_flag = 1
    params.macro_place_flag = 1
    params.legalize_flag = 1
    params.two_stage_flag = 0
    params.routability_opt_flag = 0
    params.get_congestion_map = 0
    params.egr_padding_flag = 0
    params.macro_halo_x = 1000
    params.macro_halo_y = 1000
    params.macro_pin_halo_x = -1
    params.macro_pin_halo_y = -1
    params.cell_padding_x = 0
    params.enable_fillers = 0
    params.auto_adjust_bins = 0
    params.num_bins_x = 4
    params.num_bins_y = 4
    params.num_threads = 1
    params.plot_flag = 0
    params.result_dir = str(tmp_path)
    params.base_design_name = "macro_status_test"
    params.global_place_stages[0]["iteration"] = 5
    params.stop_overflow = 1.0

    engine = PlacementEngine(params)
    engine.setup_rawdb(ecc_module=ECCToolsModule())
    halo_setup = {}
    setup_placedb = engine.setup_placedb

    def capture_halo_setup():
        setup_placedb()
        candidate_ids = np.flatnonzero(engine.placedb.macro_writeback_candidate)
        halo_setup.update(
            candidate_ids=candidate_ids,
            halo_x=engine.params.macro_halo_x,
            halo_y=engine.params.macro_halo_y,
            node_x=engine.placedb.node_x[candidate_ids].copy(),
            node_y=engine.placedb.node_y[candidate_ids].copy(),
            node_size_x=engine.placedb.node_size_x[candidate_ids].copy(),
            node_size_y=engine.placedb.node_size_y[candidate_ids].copy(),
        )

    engine.setup_placedb = capture_halo_setup
    result = engine.run()

    assert result.get("executed") is not False, (
        result,
        list(engine.placedb.pydb.macro_writeback_candidate),
        list(engine.placedb.pydb.node_names),
    )
    assert result["hpwl"] != float("inf")
    assert halo_setup["halo_x"] > 0
    assert halo_setup["halo_y"] > 0
    scale_factor = engine.params.scale_factor
    shift_x, shift_y = engine.params.shift_factor
    candidate_names = [
        engine.placedb.node_names[node_id].decode() for node_id in halo_setup["candidate_ids"]
    ]
    for offset, name in enumerate(candidate_names):
        input_node = input_nodes[name]
        assert halo_setup["node_x"][offset] == pytest.approx(
            (input_node["x"] - shift_x) * scale_factor - halo_setup["halo_x"]
        )
        assert halo_setup["node_y"][offset] == pytest.approx(
            (input_node["y"] - shift_y) * scale_factor - halo_setup["halo_y"]
        )
        assert halo_setup["node_size_x"][offset] == pytest.approx(
            input_node["size_x"] * scale_factor + 2 * halo_setup["halo_x"]
        )
        assert halo_setup["node_size_y"][offset] == pytest.approx(
            input_node["size_y"] * scale_factor + 2 * halo_setup["halo_y"]
        )

    assert engine.params.macro_halo_x == 0
    assert engine.params.macro_halo_y == 0
    np.testing.assert_allclose(
        engine.placer.data_collections.node_size_x[halo_setup["candidate_ids"]].cpu(),
        [input_nodes[name]["size_x"] * scale_factor for name in candidate_names],
    )
    np.testing.assert_allclose(
        engine.placer.data_collections.node_size_y[halo_setup["candidate_ids"]].cpu(),
        [input_nodes[name]["size_y"] * scale_factor for name in candidate_names],
    )
    updated_db = _new_place_db(ecc_py)
    updated_locations = {
        name: (updated_db.node_x[node_id], updated_db.node_y[node_id])
        for node_id, name in enumerate(updated_db.node_names)
    }
    for node_id, name in zip(halo_setup["candidate_ids"], candidate_names, strict=True):
        assert updated_locations[name] == pytest.approx(
            (
                engine.placedb.node_x[node_id] / scale_factor + shift_x,
                engine.placedb.node_y[node_id] / scale_factor + shift_y,
            ),
            abs=1,
        )
    updated_candidates = dict(
        zip(updated_db.node_names, updated_db.macro_writeback_candidate, strict=True)
    )
    assert updated_candidates["macro_none"] is False
    assert updated_candidates["macro_unplaced"] is False
    assert updated_db.num_terminals == place_db.num_terminals + 2

    committed_locations = {name: updated_locations[name] for name in candidate_names}
    normal_params = Params()
    normal_params.fromJson(json.loads(config_path.read_text(encoding="utf-8")))
    normal_params.macro_only = 0
    normal_params.routability_opt_flag = 0
    normal_params.get_congestion_map = 0
    normal_params.egr_padding_flag = 0
    normal_params.macro_halo_x = 0
    normal_params.macro_halo_y = 0
    normal_params.cell_padding_x = 0
    normal_params.enable_fillers = 0
    normal_params.auto_adjust_bins = 0
    normal_params.num_bins_x = 4
    normal_params.num_bins_y = 4
    normal_params.num_threads = 1
    normal_params.result_dir = str(tmp_path / "normal-placement")
    normal_params.base_design_name = "macro_status_test"
    normal_params.global_place_stages[0]["iteration"] = 5
    normal_params.stop_overflow = 1.0

    normal_engine = PlacementEngine(normal_params)
    normal_engine.setup_rawdb(ecc_module=ECCToolsModule())
    normal_result = normal_engine.run()

    assert normal_result["hpwl"] != float("inf")
    fixed_names = {
        name.decode()
        for name in normal_engine.placedb.node_names[normal_engine.placedb.fixed_slice]
    }
    assert set(candidate_names) <= fixed_names
    after_normal_db = _new_place_db(ecc_py)
    after_normal_locations = {
        name: (after_normal_db.node_x[node_id], after_normal_db.node_y[node_id])
        for node_id, name in enumerate(after_normal_db.node_names)
    }
    assert {name: after_normal_locations[name] for name in candidate_names} == committed_locations
