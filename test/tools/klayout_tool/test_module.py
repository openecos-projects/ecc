import importlib
import sys
import types

from chipcompiler.data import Workspace, WorkspaceStep


def test_save_snapshot_image_passes_path_text_to_klayout(monkeypatch, tmp_path):
    calls = {}

    class FakeLayoutView:
        def set_config(self, *_args):
            pass

        def load_layout(self, *args):
            calls["load_layout"] = args

        def max_hier(self):
            pass

        def timer(self):
            pass

        def save_image(self, *args):
            calls["save_image"] = args

    klayout = types.ModuleType("klayout")
    db = types.ModuleType("klayout.db")
    lay = types.ModuleType("klayout.lay")
    lay.LayoutView = FakeLayoutView
    klayout.db = db
    klayout.lay = lay
    monkeypatch.setitem(sys.modules, "klayout", klayout)
    monkeypatch.setitem(sys.modules, "klayout.db", db)
    monkeypatch.setitem(sys.modules, "klayout.lay", lay)
    sys.modules.pop("chipcompiler.tools.klayout_tool.module", None)
    sys.modules.pop("chipcompiler.tools.klayout_tool.image", None)

    klayout_module = importlib.import_module("chipcompiler.tools.klayout_tool.module")
    module = klayout_module.KlayoutModule(workspace=Workspace(), step=WorkspaceStep())

    gds_file = tmp_path / "design.gds"
    img_file = tmp_path / "design.png"
    gds_file.write_text("GDS", encoding="utf-8")
    module.save_snapshot_image(gds_file=gds_file, img_file=img_file, weight=800, height=600)

    assert calls["load_layout"] == (str(gds_file), 0)
    assert calls["save_image"] == (str(img_file), 800, 600)
