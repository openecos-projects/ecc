import json

from chipcompiler.data import (
    PDK,
    OriginDesign,
    OutputPaths,
    StepData,
    StepEnum,
    StepFeature,
    StepInput,
    StepReport,
    Workspace,
    WorkspaceStep,
)
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


class FakeSynthesisStaModule:
    def __init__(self):
        self.calls = []

    def init_config(self, **kwargs):
        self.calls.append(("init_config", kwargs))

    def init_techlef(self, path):
        self.calls.append(("init_techlef", path))

    def init_lefs(self, paths):
        self.calls.append(("init_lefs", paths))

    def read_verilog(self, **kwargs):
        self.calls.append(("read_verilog", kwargs))

    def run_timing(self, **kwargs):
        self.calls.append(("run_timing", kwargs))


class FakeLogger:
    def __init__(self):
        self.infos = []
        self.warnings = []

    def info(self, message, *args):
        self.infos.append((message, args))

    def warning(self, message, *args):
        self.warnings.append((message, args))


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
        input=StepInput(
            def_=design_def,
            verilog=tmp_path / "origin" / "gcd.v",
            db=None,
        ),
        data=StepData(dir=tmp_path / "floorplan_ecc" / "data"),
        feature=StepFeature(dir=tmp_path / "floorplan_ecc" / "feature"),
    )
    FakeEccModule.instances = []
    monkeypatch.setattr(ecc_runner, "is_eda_exist", lambda: True)
    monkeypatch.setattr(ecc_runner, "ECCToolsModule", FakeEccModule)

    module = ecc_runner.create_db_engine(workspace, step)

    assert module is FakeEccModule.instances[-1]
    assert ("read_def", str(design_def)) in module.calls


def test_run_sta_without_spef_reads_netlist_and_writes_to_step_report(
        tmp_path, monkeypatch):
    netlist = tmp_path / "output" / "gcd.v"
    techlef = tmp_path / "pdk" / "tech.lef"
    lef = tmp_path / "pdk" / "std.lef"
    liberty = tmp_path / "pdk" / "std.lib"
    sdc = tmp_path / "gcd.sdc"
    for path in (netlist, techlef, lef, liberty, sdc):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")

    logger = FakeLogger()
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
        pdk=PDK(tech=techlef, lefs=[lef], libs=[liberty], sdc=sdc),
        config={
            "flow": tmp_path / "config" / "flow.json",
            "db": tmp_path / "config" / "db.json",
            StepEnum.STA.value: tmp_path / "config" / "sta.json",
        },
        logger=logger,
    )
    step = WorkspaceStep(
        output=OutputPaths(verilog=netlist),
        data=StepData(dir=tmp_path / "Synthesis_yosys" / "data"),
        feature=StepFeature(dir=tmp_path / "Synthesis_yosys" / "feature"),
        report=StepReport(dir=tmp_path / "Synthesis_yosys" / "report"),
    )
    module = FakeSynthesisStaModule()
    monkeypatch.setattr(ecc_runner, "ECCToolsModule", lambda: module)

    assert ecc_runner.run_sta_without_spef(workspace, step) is True

    assert module.calls == [
        (
            "init_config",
            {
                "flow_config": workspace.config["flow"],
                "db_config": workspace.config["db"],
                "output_dir": step.data["dir"],
                "feature_dir": step.feature["dir"],
            },
        ),
        ("init_techlef", techlef),
        ("init_lefs", [lef]),
        ("read_verilog", {"verilog": netlist, "top_module": "gcd"}),
        (
            "run_timing",
            {
                "config": workspace.config[StepEnum.STA.value],
                "work_dir": step.data["dir"] / "sta",
                "output_dir": step.report["dir"],
                "lib_paths": [liberty],
                "sdc_path": sdc,
            },
        ),
    ]
    assert (step.data["dir"] / "sta").is_dir()
    assert step.report["dir"].is_dir()
    assert logger.warnings == []


def test_run_sta_without_spef_warns_when_sdc_is_missing(tmp_path):
    netlist = tmp_path / "output" / "gcd.v"
    liberty = tmp_path / "pdk" / "std.lib"
    for path in (netlist, liberty):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")

    logger = FakeLogger()
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
        pdk=PDK(libs=[liberty], sdc=tmp_path / "missing.sdc"),
        logger=logger,
    )
    step = WorkspaceStep(
        output=OutputPaths(verilog=netlist),
        data=StepData(dir=tmp_path / "Synthesis_yosys" / "data"),
        report=StepReport(dir=tmp_path / "Synthesis_yosys" / "report"),
    )

    assert ecc_runner.run_sta_without_spef(workspace, step) is False
    assert logger.warnings[0][0] == "Post-synthesis STA failed; synthesis result is kept: %s"


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
