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


def qor_summary(
    *,
    setup_wns=2.5,
    setup_tns=0.0,
    setup_nvp=0,
    frequency_mhz=100,
    hold_wns=1.25,
    hold_tns=0.0,
    hold_nvp=0,
):
    return {
        "path_groups": [],
        "summary": {
            "setup": {
                "wns": setup_wns,
                "tns": setup_tns,
                "nvp": setup_nvp,
                "frequency_mhz": frequency_mhz,
            },
            "hold": {
                "wns": hold_wns,
                "tns": hold_tns,
                "nvp": hold_nvp,
            },
        },
        "design_statistics": {},
    }


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _sta_checker(
    tmp_path: Path,
    *,
    report_names=STA_REPORT_NAMES,
    summary=None,
    frequency_target=100,
    text_report="legacy signoff report\n",
) -> EccStaChecklist:
    output_dir = tmp_path / "sta_ecc" / "output"
    report_dir = output_dir / "MAX_125" / "RCworst"
    for report_name in report_names:
        _write(report_dir / report_name, text_report)

    if summary is not None:
        _write(report_dir / "qor_summary.json", json.dumps(summary))

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
        parameters=SimpleNamespace(data={"Frequency max [MHz]": frequency_target}),
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


def test_sta_checklist_validates_current_json_summary(tmp_path):
    checker = _sta_checker(tmp_path, summary=qor_summary())

    assert checker.check() is True
    assert _item_state(checker, "check STA signoff matrix") == "Passed"
    assert _item_state(checker, "check STA QoR summary data") == "Passed"
    assert _item_state(checker, "check setup timing") == "Passed"
    assert _item_state(checker, "check hold timing") == "Passed"
    assert _item_state(checker, "check frequency requirement") == "Passed"
    assert _item_state(checker, "check timing exceptions") == "Warning"
    assert _item_state(checker, "check STA DRV violations") == "Warning"


def test_sta_checklist_fails_matrix_when_a_path_report_is_missing(tmp_path):
    checker = _sta_checker(
        tmp_path,
        report_names=STA_REPORT_NAMES[:-1],
        summary=qor_summary(),
    )

    assert checker.check() is False
    assert _item_state(checker, "check STA signoff matrix") == "Failed"


def test_sta_checklist_requires_current_qor_summary_json(tmp_path):
    checker = _sta_checker(tmp_path)

    assert checker.check() is False
    assert _item_state(checker, "check STA signoff matrix") == "Failed"
    assert _item_state(checker, "check STA QoR summary data") == "Failed"


def test_sta_checklist_uses_json_nvp_not_text_report_columns(tmp_path):
    checker = _sta_checker(
        tmp_path,
        summary=qor_summary(setup_nvp=1),
        text_report="text report format changed\n",
    )

    assert checker.check() is False
    assert _item_state(checker, "check setup timing") == "Failed"
    assert _item_state(checker, "check hold timing") == "Passed"
    assert _item_state(checker, "check frequency requirement") == "Passed"


def test_sta_checklist_rejects_incomplete_qor_summary_json(tmp_path):
    checker = _sta_checker(
        tmp_path,
        summary={"path_groups": [], "summary": {"setup": None, "hold": None}},
    )

    assert checker.check() is False
    assert _item_state(checker, "check STA QoR summary data") == "Failed"


def test_sta_checklist_warns_when_frequency_target_is_not_configured(tmp_path):
    checker = _sta_checker(
        tmp_path,
        summary=qor_summary(),
        frequency_target=0,
    )

    assert checker.check() is True
    assert _item_state(checker, "check frequency requirement") == "Warning"
