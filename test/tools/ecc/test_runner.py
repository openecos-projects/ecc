import json

from chipcompiler.data import PDK, OriginDesign, Workspace, WorkspaceStep
from chipcompiler.tools.ecc import runner as ecc_runner
from chipcompiler.tools.ecc.checklist import EccRcxChecklist


class FakeEccModule:
    instances = []

    def __init__(self):
        self.calls = []
        FakeEccModule.instances.append(self)

    def init_config(self, **kwargs):
        self.calls.append(("init_config", kwargs))

    def is_db_data_exists(self, path):
        self.calls.append(("is_db_data_exists", path))
        return False

    def init_techlef(self, path):
        self.calls.append(("init_techlef", path))

    def init_lefs(self, paths):
        self.calls.append(("init_lefs", paths))

    def read_def(self, path):
        self.calls.append(("read_def", path))


def test_create_db_engine_accepts_path_inputs_for_first_ecc_step(tmp_path, monkeypatch):
    design_def = tmp_path / "origin" / "gcd.def"
    design_def.parent.mkdir()
    design_def.write_text("VERSION 5.8 ;\nDESIGN gcd ;\nEND DESIGN\n")

    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
        pdk=PDK(tech=tmp_path / "tech.lef", lefs=[tmp_path / "std.lef"]),
        config={
            "flow": tmp_path / "config" / "flow_config.json",
            "db": tmp_path / "config" / "db_default_config.json",
        },
    )
    step = WorkspaceStep(
        name="Floorplan",
        input={
            "def": design_def,
            "verilog": tmp_path / "origin" / "gcd.v",
            "db": None,
        },
        data={"dir": tmp_path / "floorplan_ecc" / "data"},
        feature={"dir": tmp_path / "floorplan_ecc" / "feature"},
    )
    FakeEccModule.instances = []
    monkeypatch.setattr(ecc_runner, "is_eda_exist", lambda: True)
    monkeypatch.setattr(ecc_runner, "ECCToolsModule", FakeEccModule)

    module = ecc_runner.create_db_engine(workspace, step)

    assert module is FakeEccModule.instances[-1]
    assert ("read_def", str(design_def)) in module.calls


def test_sta_signoff_items_use_top_module_for_rcx_spef(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    sta_config = config_dir / "sta.json"
    rcx_config = config_dir / "rcx.json"
    sta_config.write_text(json.dumps({
        "liberty": [{"corner": "MAX", "temperature": 125, "path": ["max.lib"]}],
        "signoff": [{"MAX": ["Cworst"]}],
    }))
    rcx_config.write_text(json.dumps({"output": str(tmp_path / "RCX_ecc" / "output")}))
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="project_gcd_ws_0002", top_module="gcd"),
        config={"sta": sta_config, "RCX": rcx_config},
    )

    items = ecc_runner.collect_sta_signoff_items(workspace)

    assert items[0]["spef_file"] == str(
        tmp_path / "RCX_ecc" / "output" / "gcd_Cworst_125C.spef"
    )


def test_rcx_checklist_strips_top_module_from_spef_corner(tmp_path):
    checklist = EccRcxChecklist.__new__(EccRcxChecklist)
    checklist.workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="project_gcd_ws_0002", top_module="gcd"),
    )

    assert checklist.spef_corner_name("/rcx/gcd_Cworst_125C.spef") == "Cworst"


def test_rcx_checklist_uses_top_module_for_spef_design_token(tmp_path):
    spef = tmp_path / "gcd_Cworst_125C.spef"
    spef.write_text('*SPEF "IEEE 1481-1998"\n*DESIGN "gcd"\n*NAME_MAP\n')
    checklist = EccRcxChecklist.__new__(EccRcxChecklist)
    checklist.workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="project_gcd_ws_0002", top_module="gcd"),
    )

    assert checklist.check_spef_file(str(spef)) is True
