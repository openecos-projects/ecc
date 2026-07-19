import json

from chipcompiler.data import PDK, OriginDesign, StepEnum, Workspace, WorkspaceStep
from chipcompiler.tools.ecc import runner as ecc_runner
from chipcompiler.tools.ecc.checklist import EccRcxChecklist
from chipcompiler.tools.ecc.builder import build_step, build_step_space


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


class FakeSubFlow:
    def __init__(self, *args, **kwargs):
        self.updates = []

    def update_step(self, **kwargs):
        self.updates.append(kwargs)


class FakeCtsModule:
    def __init__(self, timing_quality):
        self.calls = []
        self.timing_quality = timing_quality

    def run_cts(self, **kwargs):
        self.calls.append(("run_cts", kwargs))

    def update_step_paths(self, **kwargs):
        self.calls.append(("update_step_paths", kwargs))

    def report_cts(self, **kwargs):
        self.calls.append(("report_cts", kwargs))

    def feature_cts_map(self, **kwargs):
        self.calls.append(("feature_cts_map", kwargs))

    def feature_cts_timing(self):
        self.calls.append(("feature_cts_timing", {}))
        return self.timing_quality


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


def test_run_cts_merges_structured_timing_into_step_feature(tmp_path, monkeypatch):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
        config={StepEnum.CTS.value: tmp_path / "config" / "cts.json"},
    )
    step = build_step(
        workspace=workspace,
        step_name=StepEnum.CTS.value,
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
    )
    build_step_space(step)
    step.feature["step"].write_text(json.dumps({"CTS": {"buffer_num": 3}}))
    timing_quality = {
        "schema_version": 1,
        "analysis_stage": "cts_fast_sta_post_optimization",
        "availability": "available",
        "clock_count": 1,
        "clocks": [{
            "clock": "clk",
            "sink_count": 10,
            "target_skew_ns": 0.08,
            "initial_skew_ns": 0.05,
            "optimized_skew_ns": 0.04,
            "min_insertion_latency_ns": 0.12,
            "max_insertion_latency_ns": 0.28,
            "mean_insertion_latency_ns": 0.2,
            "target_met": True,
        }],
        "worst_optimized_skew_ns": 0.04,
        "worst_max_insertion_latency_ns": 0.28,
        "target_unmet_count": 0,
    }
    module = FakeCtsModule(timing_quality)
    monkeypatch.setattr(ecc_runner, "EccSubFlow", FakeSubFlow)
    monkeypatch.setattr(ecc_runner, "save_data", lambda **kwargs: True)
    monkeypatch.setattr(ecc_runner, "run_analysis", lambda **kwargs: None)

    assert ecc_runner.run_cts(workspace, step, module) is True

    feature = json.loads(step.feature["step"].read_text(encoding="utf-8"))
    assert feature["CTS"] == {
        "buffer_num": 3,
        "timing_quality": timing_quality,
    }
    assert [call[0] for call in module.calls] == [
        "update_step_paths",
        "run_cts",
        "report_cts",
        "feature_cts_map",
        "feature_cts_timing",
    ]


def test_run_sta_without_spef_reads_netlist_and_writes_to_step_report_and_feature(
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
        output={"verilog": netlist},
        data={"dir": tmp_path / "Synthesis_yosys" / "data"},
        feature={"dir": tmp_path / "Synthesis_yosys" / "feature"},
        report={"dir": tmp_path / "Synthesis_yosys" / "report"},
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
                "report_dir": step.report["dir"] / "post_synthesis",
                "feature_dir": step.feature["dir"] / "post_synthesis",
                "lib_paths": [liberty],
                "sdc_path": sdc,
                "corner": "post_synthesis",
            },
        ),
    ]
    assert (step.data["dir"] / "sta").is_dir()
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
        output={"verilog": netlist},
        data={"dir": tmp_path / "Synthesis_yosys" / "data"},
        report={"dir": tmp_path / "Synthesis_yosys" / "report"},
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


def test_run_sta_uses_matched_report_and_feature_corner_directories(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    max_lib = tmp_path / "pdk" / "max.lib"
    min_lib = tmp_path / "pdk" / "min.lib"
    sdc = tmp_path / "pdk" / "gcd.sdc"
    spef_root = tmp_path / "RCX_ecc" / "output"
    for path in (
        max_lib,
        min_lib,
        sdc,
        spef_root / "gcd_RCworst_125C.spef",
        spef_root / "gcd_Cbest_m40C.spef",
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    sta_config = config_dir / "sta.json"
    sta_config.write_text(
        json.dumps({
            "liberty": [
                {"corner": "MAX", "temperature": 125, "path": [str(max_lib)]},
                {"corner": "MIN", "temperature": -40, "path": [str(min_lib)]},
            ],
            "signoff": [{"MAX": ["RCworst"], "MIN": ["Cbest"]}],
        }),
        encoding="utf-8",
    )
    rcx_config = config_dir / "rcx.json"
    rcx_config.write_text(json.dumps({"output": str(spef_root)}), encoding="utf-8")
    logger = FakeLogger()
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
        pdk=PDK(libs=[max_lib, min_lib], sdc=sdc),
        config={StepEnum.STA.value: sta_config, StepEnum.RCX.value: rcx_config},
        logger=logger,
    )
    step = WorkspaceStep(
        name=StepEnum.STA.value,
        data={StepEnum.STA.value: tmp_path / "sta_ecc" / "data" / "sta"},
        report={"dir": tmp_path / "sta_ecc" / "report"},
        feature={"dir": tmp_path / "sta_ecc" / "feature"},
    )
    module = FakeSynthesisStaModule()
    monkeypatch.setattr(ecc_runner, "EccSubFlow", FakeSubFlow)
    monkeypatch.setattr(ecc_runner, "get_eda_instance", lambda **kwargs: module)
    monkeypatch.setattr(ecc_runner, "save_data", lambda **kwargs: True)
    monkeypatch.setattr(ecc_runner, "run_analysis", lambda **kwargs: None)

    assert ecc_runner.run_sta(workspace, step) is True

    calls = [payload for name, payload in module.calls if name == "run_timing"]
    assert calls == [
        {
            "config": sta_config,
            "work_dir": step.data[StepEnum.STA.value],
            "report_dir": step.report["dir"] / "MAX_125" / "RCworst",
            "feature_dir": step.feature["dir"] / "MAX_125" / "RCworst",
            "lib_paths": [str(max_lib)],
            "sdc_path": sdc,
            "spef_path": str(spef_root / "gcd_RCworst_125C.spef"),
            "output_modes": ("report", "structured"),
            "corner": "MAX_125/RCworst",
        },
        {
            "config": sta_config,
            "work_dir": step.data[StepEnum.STA.value],
            "report_dir": step.report["dir"] / "MIN_m40" / "Cbest",
            "feature_dir": step.feature["dir"] / "MIN_m40" / "Cbest",
            "lib_paths": [str(min_lib)],
            "sdc_path": sdc,
            "spef_path": str(spef_root / "gcd_Cbest_m40C.spef"),
            "output_modes": ("report", "structured"),
            "corner": "MIN_m40/Cbest",
        },
    ]


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
