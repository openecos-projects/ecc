import json
from pathlib import Path
from types import SimpleNamespace

from chipcompiler.data import StepEnum
from chipcompiler.tools.ecc.checklist import EccStaChecklist


STA_REPORT_NAMES = (
    "qor_summary.rpt",
    "timing_max_in2out.rpt",
    "timing_max_in2reg.rpt",
    "timing_max_reg2out.rpt",
    "timing_max_reg2reg.rpt",
    "timing_min_in2out.rpt",
    "timing_min_in2reg.rpt",
    "timing_min_reg2out.rpt",
    "timing_min_reg2reg.rpt",
)

QOR_SUMMARY = """\
Path Group                  WNS        TNS     NVP      FREQ      WNS(H)     TNS(H)  NVP(H)
-------------------------------------------------------------------------------------------
clk                       2.500      0.000       0    100MHz       1.250      0.000       0
-------------------------------------------------------------------------------------------
Summary                   2.500      0.000       0    100MHz       1.250      0.000       0
"""


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _sta_checker(tmp_path: Path, report_names=STA_REPORT_NAMES) -> EccStaChecklist:
    output_dir = tmp_path / "sta_ecc" / "output"
    report_dir = output_dir / "MAX_125" / "RCworst"
    for report_name in report_names:
        text = QOR_SUMMARY if report_name == "qor_summary.rpt" else "timing paths\n"
        _write(report_dir / report_name, text)

    sta_config = tmp_path / "config" / "sta.json"
    _write(
        sta_config,
        json.dumps(
            {
                "liberty": [{"corner": "MAX", "temperature": 125}],
                "signoff": [{"MAX": ["RCworst"]}],
            }
        ),
    )
    checklist_path = tmp_path / "sta_ecc" / "checklist.json"
    workspace = SimpleNamespace(
        config={StepEnum.STA.value: str(sta_config)},
        design=SimpleNamespace(name="gcd", top_module="gcd"),
        home=SimpleNamespace(update_checklist=lambda **kwargs: None),
        parameters=SimpleNamespace(data={"Frequency max [MHz]": 100}),
    )
    workspace_step = SimpleNamespace(
        checklist={"path": str(checklist_path)},
        name=StepEnum.STA.value,
        output={"dir": str(output_dir)},
    )
    return EccStaChecklist(workspace, workspace_step)


def _item_state(checker: EccStaChecklist, item: str) -> str:
    data = json.loads(Path(checker.workspace_step.checklist["path"]).read_text())
    return next(row["state"] for row in data["checklist"] if row["item"] == item)


def test_sta_checklist_validates_current_text_reports(tmp_path):
    checker = _sta_checker(tmp_path)

    assert checker.check() is True
    assert _item_state(checker, "check STA signoff matrix") == "Passed"
    assert _item_state(checker, "check setup timing") == "Passed"
    assert _item_state(checker, "check hold timing") == "Passed"
    assert _item_state(checker, "check frequency requirement") == "Passed"


def test_sta_checklist_fails_matrix_when_a_path_report_is_missing(tmp_path):
    checker = _sta_checker(tmp_path, STA_REPORT_NAMES[:-1])

    assert checker.check() is False
    assert _item_state(checker, "check STA signoff matrix") == "Failed"
