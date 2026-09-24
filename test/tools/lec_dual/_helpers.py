import json
from pathlib import Path
from types import SimpleNamespace

from chipcompiler.data import (
    PDK,
    ChecklistState,
    HomeData,
    LecDualStep,
    LecInput,
    LogPaths,
    OriginDesign,
    OutputPaths,
    Parameters,
    SubflowState,
    Workspace,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
GCD_RTL = REPO_ROOT / "test" / "fixtures" / "gcd" / "gcd.v"


def _workspace(tmp_path: Path) -> Workspace:
    lib = tmp_path / "stdcell.lib"
    lib.write_text("library(test) { }\n")
    return Workspace(
        directory=tmp_path / "ws",
        design=OriginDesign(
            name="gcd",
            top_module="gcd",
            origin_verilog=GCD_RTL,
        ),
        pdk=PDK(
            name="ics55",
            libs=[lib],
            tap_cell="FILLTAPH7R",
            fillers=["FILLER4H7R", "FILLER8H7R"],
        ),
        parameters=Parameters(data={"design": "gcd", "top_module": "gcd"}),
        home=HomeData(),
    )


def _write_netlists(tmp_path: Path) -> tuple[Path, Path]:
    golden = tmp_path / "gcd_Synthesis_golden.v"
    golden.write_text(GCD_RTL.read_text())
    gate = tmp_path / "gcd_Synthesis.v"
    gate.write_text(GCD_RTL.read_text())
    return golden, gate


def _aggregate_step(tmp_path: Path, golden: Path, gate: Path) -> LecDualStep:
    directory = tmp_path / "lec_dual"
    output_dir = directory / "output"
    log_dir = directory / "log"
    output_dir.mkdir(parents=True)
    log_dir.mkdir(parents=True)
    return LecDualStep(
        name="lec",
        tool="lec_dual",
        directory=directory,
        input=LecInput(gate_verilog=gate, golden_verilog=golden),
        output=OutputPaths(dir=output_dir, json=output_dir / "gcd_lec_result.json"),
        log=LogPaths(dir=log_dir, file=log_dir / "lec.log"),
        subflow=SubflowState(path=directory / "subflow.json", steps=[]),
        checklist=ChecklistState(path=directory / "checklist.json", checklist=[]),
    )


def _engine_step(tmp_path: Path, engine_value: str) -> SimpleNamespace:
    directory = tmp_path / f"lec_{engine_value}"
    output_dir = directory / "output"
    report_dir = directory / "report"
    output_dir.mkdir(parents=True)
    report_dir.mkdir(parents=True)
    return SimpleNamespace(
        name="lec",
        tool=engine_value,
        directory=directory,
        output=SimpleNamespace(dir=output_dir, json=output_dir / "gcd_lec_result.json"),
        report=SimpleNamespace(dir=report_dir, status=report_dir / "run_lec_status.rpt"),
    )


def write_engine_result(path: Path, *, proven: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"status": "proven" if proven else "incomplete"}) + "\n",
        encoding="utf-8",
    )


class FakeEngineModule:
    """Tool-module-shaped fake: build delegates to the real engine module,
    run is scripted by the test."""

    def __init__(self, real_module, run):
        self._real_module = real_module
        self._run = run

    def is_eda_exist(self):
        return True

    def build_step(self, **kwargs):
        return self._real_module.build_step(**kwargs)

    def build_step_space(self, step):
        return None

    def build_step_config(self, workspace, step):
        return None

    def run_step(self, workspace, step, ecc_module=None):
        return self._run(step)
