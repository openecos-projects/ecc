from types import SimpleNamespace

import numpy as np
from dreamplace.macroPlaceDB import MacroPlaceDB
from dreamplace.Placer import PlacementEngine


def _macro_params(**overrides):
    values = {
        "macro_only": 1,
        "bndry_padding_x": 0,
        "bndry_padding_y": 0,
        "macro_halo_x": 0,
        "macro_halo_y": 0,
        "macro_pin_halo_x": -1,
        "macro_pin_halo_y": -1,
        "cell_padding_x": 0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_macro_only_uses_native_masks_instead_of_geometry_heuristics():
    place_db = MacroPlaceDB(ecc_module=None)
    place_db.num_physical_nodes = 8
    place_db.num_terminals = 4
    place_db.num_terminal_NIs = 0
    place_db.movable_slice = slice(0, 4)
    place_db.fixed_slice = slice(4, 8)
    place_db.node_size_x = np.array([10, 8, 500, 1, 10, 10, 10, 1000], dtype=np.float32)
    place_db.node_size_y = np.array([10, 8, 10, 1, 10, 10, 10, 1000], dtype=np.float32)
    place_db.node_x = np.zeros(8, dtype=np.float32)
    place_db.node_y = np.zeros(8, dtype=np.float32)
    place_db.node_is_hard_macro = np.array(
        [True, True, False, False, True, True, True, False], dtype=np.bool_
    )
    place_db.macro_writeback_candidate = np.array(
        [True, True, False, False, False, False, False, False], dtype=np.bool_
    )
    place_db.node2pin_map = np.empty(8, dtype=object)
    for node_id in range(8):
        place_db.node2pin_map[node_id] = np.array([node_id], dtype=np.int32)
    place_db.pin2node_map = np.arange(8, dtype=np.int32)
    place_db.pin_offset_x = np.zeros(8, dtype=np.float32)
    place_db.pin_offset_y = np.zeros(8, dtype=np.float32)
    place_db.site_width = 1.0
    place_db.row_height = 1.0
    place_db.total_space_area = 10_000_000.0

    place_db.update_macros(_macro_params())

    np.testing.assert_array_equal(place_db.movable_macro_mask, [True, True, False, False])
    np.testing.assert_array_equal(place_db.movable_macro_idx, [0, 1])
    np.testing.assert_array_equal(place_db.fixed_macro_mask, [True, True, True, False])
    np.testing.assert_array_equal(place_db.fixed_macro_idx, [4, 5, 6])


def test_macro_only_apply_selectively_writes_unscaled_physical_coordinates():
    class FakeNativePlaceDB:
        def __init__(self):
            self.calls = []

        def write_macro_placement_back(self, node_x, node_y):
            self.calls.append((node_x.copy(), node_y.copy()))
            return 2

    class FakeEccModule:
        def __init__(self):
            self.dense_calls = []

        def write_placement_back(self, ecc_db, node_x, node_y):
            self.dense_calls.append((ecc_db, node_x.copy(), node_y.copy()))

    ecc_module = FakeEccModule()
    native_db = FakeNativePlaceDB()
    place_db = MacroPlaceDB(ecc_module=ecc_module)
    place_db.pydb = native_db
    place_db.ecc_db = object()
    place_db.num_physical_nodes = 3
    place_db.num_terminals = 0
    place_db.num_terminal_NIs = 0
    place_db.node_x = np.zeros(3, dtype=np.float32)
    place_db.node_y = np.zeros(3, dtype=np.float32)
    params = SimpleNamespace(macro_only=1, scale_factor=2.0, shift_factor=[10.0, 20.0])

    place_db.apply(
        params,
        np.array([2.0, 4.0, 6.0], dtype=np.float32),
        np.array([8.0, 10.0, 12.0], dtype=np.float32),
    )

    assert len(native_db.calls) == 1
    np.testing.assert_array_equal(native_db.calls[0][0], [11.0, 12.0, 13.0])
    np.testing.assert_array_equal(native_db.calls[0][1], [24.0, 25.0, 26.0])
    assert ecc_module.dense_calls == []


def test_normal_apply_keeps_dense_writeback():
    class FakeNativePlaceDB:
        def write_macro_placement_back(self, node_x, node_y):
            raise AssertionError("normal placement must not use selective writeback")

    class FakeEccModule:
        def __init__(self):
            self.dense_calls = []

        def write_placement_back(self, ecc_db, node_x, node_y):
            self.dense_calls.append((ecc_db, node_x.copy(), node_y.copy()))

    ecc_module = FakeEccModule()
    place_db = MacroPlaceDB(ecc_module=ecc_module)
    place_db.pydb = FakeNativePlaceDB()
    place_db.ecc_db = object()
    place_db.num_physical_nodes = 2
    place_db.num_terminals = 0
    place_db.num_terminal_NIs = 0
    place_db.node_x = np.zeros(2, dtype=np.float32)
    place_db.node_y = np.zeros(2, dtype=np.float32)
    params = SimpleNamespace(macro_only=0, scale_factor=2.0, shift_factor=[10.0, 20.0])

    place_db.apply(
        params,
        np.array([2.0, 4.0], dtype=np.float32),
        np.array([8.0, 10.0], dtype=np.float32),
    )

    assert len(ecc_module.dense_calls) == 1
    assert ecc_module.dense_calls[0][0] is place_db.ecc_db
    np.testing.assert_array_equal(ecc_module.dense_calls[0][1], [11.0, 12.0])
    np.testing.assert_array_equal(ecc_module.dense_calls[0][2], [24.0, 25.0])


def test_macro_only_empty_candidate_set_skips_placement():
    engine = PlacementEngine.__new__(PlacementEngine)
    engine.params = SimpleNamespace(macro_only=1)
    engine.placedb = SimpleNamespace(
        pydb=SimpleNamespace(
            macro_writeback_candidate=np.array([False, False, False], dtype=np.bool_)
        )
    )
    engine.setup_placedb = lambda: (_ for _ in ()).throw(
        AssertionError("empty macro placement must not initialize the placement database")
    )
    engine.place = lambda: (_ for _ in ()).throw(
        AssertionError("empty macro placement must not run optimization")
    )

    result = engine.run()

    assert result == {
        "executed": False,
        "candidate_count": 0,
        "reason": "no_unplaced_hard_macros",
    }
