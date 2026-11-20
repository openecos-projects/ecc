import pytest

db = pytest.importorskip("klayout.db")

from chipcompiler.data import (  # noqa: E402
    EccData,
    EccOutput,
    EccStep,
    OriginDesign,
    StepEnum,
    Workspace,
)
from chipcompiler.data.pdk import PDK  # noqa: E402
from chipcompiler.tools.ecc import runner as ecc_runner  # noqa: E402
from chipcompiler.tools.ecc.gds_merge import (  # noqa: E402
    derive_gds_from_lefs,
    merge_pdk_cell_layouts,
    merge_pdk_gds,
    pdk_gds_files,
)

ACTIVE = (2, 1)
METAL1 = (81, 1)
BOUNDARY = (351, 12)


def _write_library(path, cell_names):
    layout = db.Layout()
    layout.dbu = 0.001
    active = layout.layer(*ACTIVE)
    for name in cell_names:
        layout.create_cell(name).shapes(active).insert(db.Box(0, 0, 100, 100))
    layout.write(str(path))


def _write_abstract_design(path, masters):
    layout = db.Layout()
    layout.dbu = 0.001
    boundary = layout.layer(*BOUNDARY)
    metal1 = layout.layer(*METAL1)
    top = layout.create_cell("top")
    top.shapes(metal1).insert(db.Box(0, 0, 1000, 1000))
    for name in masters:
        master = layout.create_cell(f"Master_{name}")
        master.shapes(boundary).insert(db.Box(0, 0, 100, 100))
        top.insert(db.CellInstArray(master.cell_index(), db.Trans(0, 0)))
    layout.write(str(path))


def _layers(path):
    layout = db.Layout()
    layout.read(str(path))
    return {(layout.get_info(i).layer, layout.get_info(i).datatype) for i in layout.layer_indexes()}


def test_merge_fills_masters_from_pdk_gds(tmp_path):
    lib = tmp_path / "lib.gds"
    design = tmp_path / "design.gds"
    _write_library(lib, ["INVX1", "NAND2X1"])
    _write_abstract_design(design, ["INVX1", "NAND2X1", "MACRO"])
    assert ACTIVE not in _layers(design)

    result = merge_pdk_gds(design, [lib])

    assert sorted(result.merged) == ["INVX1", "NAND2X1"]
    assert result.missing == ["MACRO"]
    layers = _layers(design)
    assert ACTIVE in layers and BOUNDARY in layers and METAL1 in layers
    layout = db.Layout()
    layout.read(str(design))
    assert layout.top_cell().name == "top"
    assert layout.top_cell().dbbox() == db.DBox(0, 0, 1, 1)
    assert not (tmp_path / "design.gds.merge.tmp").exists()


def test_merge_without_masters_or_matches_is_a_no_op(tmp_path):
    design = tmp_path / "design.gds"
    _write_abstract_design(design, [])
    before = design.read_bytes()
    assert merge_pdk_gds(design, []).merged == []
    assert design.read_bytes() == before

    lib = tmp_path / "lib.gds"
    _write_library(lib, ["OTHER"])
    _write_abstract_design(design, ["UNMATCHED"])
    stat_before = design.stat()
    result = merge_pdk_gds(design, [lib])
    assert result.merged == []
    assert result.missing == ["UNMATCHED"]
    assert design.stat().st_mtime_ns == stat_before.st_mtime_ns


def test_pdk_gds_files_prefers_configured_and_derives_from_lefs(tmp_path):
    lib_dir = tmp_path / "cells"
    (lib_dir / "lef").mkdir(parents=True)
    (lib_dir / "gds").mkdir()
    lef = lib_dir / "lef" / "cells_ecos_ant.lef"
    lef.touch()
    gds = lib_dir / "gds" / "cells.gds"
    gds.touch()
    assert derive_gds_from_lefs([lef]) == [gds]
    assert pdk_gds_files(PDK(gds=[], lefs=[lef])) == [gds]
    other = tmp_path / "other.gds"
    other.touch()
    assert pdk_gds_files(PDK(gds=[other], lefs=[lef])) == [other]
    assert pdk_gds_files(PDK(gds=[tmp_path / "missing.gds"], lefs=[lef])) == []


def test_merge_pdk_cell_layouts_and_run_filler_fail_closed(tmp_path, monkeypatch):
    gds = tmp_path / "out.gds"
    lib = tmp_path / "lib.gds"
    _write_abstract_design(gds, ["INVX1"])
    _write_library(lib, ["INVX1"])
    workspace = Workspace(
        directory=tmp_path,
        pdk=PDK(name="ics55", gds=[lib], mapping_file=tmp_path / "layer.map"),
        design=OriginDesign(name="gcd", top_module="gcd"),
        config={StepEnum.FILLER.value: tmp_path / "filler.json"},
    )
    step = EccStep(
        name=StepEnum.FILLER.value,
        data=EccData(steps={StepEnum.FILLER.value: tmp_path / "data"}),
        output=EccOutput(gds=gds),
    )

    def boom(*_args, **_kwargs):
        raise RuntimeError("corrupt gds")

    monkeypatch.setattr("chipcompiler.tools.ecc.gds_merge.merge_pdk_gds", boom)
    assert merge_pdk_cell_layouts(workspace, step) is False

    class FakeFiller:
        def init_mj(self, **_kwargs):
            return True

        def run_filler(self, **_kwargs):
            return True

        def destroy_mj(self):
            return True

        def gds_save(self, **_kwargs):
            return True

    class FakeSubFlow:
        def __init__(self, **_kwargs):
            pass

        def update_step(self, **_kwargs):
            pass

    monkeypatch.setattr(ecc_runner, "EccSubFlow", FakeSubFlow)
    monkeypatch.setattr(ecc_runner, "get_eda_instance", lambda **_kwargs: FakeFiller())
    assert ecc_runner.run_filler(workspace, step) is False
