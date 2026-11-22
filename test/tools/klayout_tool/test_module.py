import importlib
import subprocess
import sys
import types
from pathlib import Path

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
    lay.__dict__["LayoutView"] = FakeLayoutView
    klayout.__dict__["db"] = db
    klayout.__dict__["lay"] = lay
    monkeypatch.setitem(sys.modules, "klayout", klayout)
    monkeypatch.setitem(sys.modules, "klayout.db", db)
    monkeypatch.setitem(sys.modules, "klayout.lay", lay)
    sys.modules.pop("chipcompiler.tools.klayout_tool.module", None)
    sys.modules.pop("chipcompiler.tools.klayout_tool.image", None)

    klayout_module = importlib.import_module("chipcompiler.tools.klayout_tool.module")
    module = klayout_module.KlayoutModule(
        workspace=Workspace(directory=tmp_path), step=WorkspaceStep()
    )

    gds_file = tmp_path / "design.gds"
    img_file = tmp_path / "design.png"
    gds_file.write_text("gds", encoding="utf-8")
    module.save_snapshot_image(gds_file=gds_file, img_file=img_file, weight=800, height=600)

    assert calls["load_layout"] == (str(gds_file), "")
    assert calls["save_image"] == (str(img_file), 800, 600)


def test_load_tool_klayout_exposes_protocol_without_importing_klayout():
    repo_root = Path(__file__).resolve().parents[3]
    script = f"""
import inspect
import logging
import sys

sys.path.insert(0, {str(repo_root)!r})

class BlockKlayout:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "klayout" or fullname.startswith("klayout."):
            raise ModuleNotFoundError(f"blocked native import: {{fullname}}")
        return None

sys.meta_path.insert(0, BlockKlayout())

records = []
class Capture(logging.Handler):
    def emit(self, record):
        records.append(self.format(record))

logging.getLogger().addHandler(Capture())

from chipcompiler.tools.protocol import ToolModule, tool_module_members
from chipcompiler.tools.registry import load_tool

mod = load_tool("klayout", check_dependency=False)
assert mod is not None
assert isinstance(mod, ToolModule)

missing = object()
for name in [*tool_module_members(), *mod.__all__]:
    assert inspect.getattr_static(mod, name, missing) is not missing, name

assert mod.STEP_CONFIG_READS == {{}}
assert mod.run_step() is False
assert mod.save_snapshot_image("", "") is False
assert not any("missing interface" in msg for msg in records), records
assert "klayout" not in sys.modules
print("klayout-tool-lazy-ok")
"""
    completed = subprocess.run(
        [sys.executable, "-I", "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "klayout-tool-lazy-ok" in completed.stdout
