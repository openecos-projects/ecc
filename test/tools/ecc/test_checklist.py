import json
from pathlib import Path
from types import SimpleNamespace

from chipcompiler.data import StepEnum
from chipcompiler.tools.ecc.checklist import EccStaChecklist
from chipcompiler.tools.ecc.sta_qor import sta_qor_summary_paths

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


def timing_paths(*, slack_ns=-0.025):
    return {
        "schema_version": 1,
        "corner": "MAX_125/RCworst",
        "path_limit": 20,
        "paths": [
            {
                "path_id": "timing_path_a",
                "analysis_type": "setup",
                "path_group": "core",
                "start_point": "u_launch:CK",
                "end_point": "u_capture:D",
                "launch_clock": "clk",
                "capture_clock": "clk",
                "check_type": "setup",
                "slack_ns": slack_ns,
                "arrival_ns": 1.025,
                "required_ns": 1.0,
                "cppr_ns": 0.0,
                "stages": [
                    {
                        "kind": "cell_arc",
                        "pin": "u_buf:Y",
                        "instance": "u_buf",
                        "cell": "BUFX3",
                        "incremental_delay_ns": 0.12,
                        "arrival_ns": 1.025,
                        "transition": "rise",
                    },
                ],
            },
        ],
    }


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _sta_checker(
    tmp_path: Path,
    *,
    report_names=STA_REPORT_NAMES,
    summary=None,
    paths=None,
    frequency_target=100,
    text_report="legacy signoff report\n",
) -> EccStaChecklist:
    report_root = tmp_path / "sta_ecc" / "report"
    feature_root = tmp_path / "sta_ecc" / "feature"
    report_dir = report_root / "MAX_125" / "RCworst"
    feature_dir = feature_root / "MAX_125" / "RCworst"
    for report_name in report_names:
        _write(report_dir / report_name, text_report)

    if summary is not None:
        _write(feature_dir / "qor_summary.json", json.dumps(summary))
    if paths is not None:
        _write(feature_dir / "timing_paths.json", json.dumps(paths))

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
        report={"dir": str(report_root)},
        feature={"dir": str(feature_root)},
    )
    return EccStaChecklist(workspace, workspace_step)


def _item_state(checker: EccStaChecklist, item: str) -> str:
    data = json.loads(Path(checker.workspace_step.checklist["path"]).read_text())
    return next(row["state"] for row in data["checklist"] if row["item"] == item)


def test_sta_checklist_validates_current_json_summary(tmp_path):
    checker = _sta_checker(tmp_path, summary=qor_summary(), paths=timing_paths())

    assert checker.check() is True
    assert _item_state(checker, "check STA signoff matrix") == "Passed"
    assert _item_state(checker, "check STA QoR summary data") == "Passed"
    assert _item_state(checker, "check STA timing path data") == "Passed"
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
        paths=timing_paths(),
    )

    assert checker.check() is False
    assert _item_state(checker, "check STA signoff matrix") == "Failed"


def test_sta_checklist_requires_current_qor_summary_json(tmp_path):
    checker = _sta_checker(tmp_path, paths=timing_paths())

    assert checker.check() is False
    assert _item_state(checker, "check STA signoff matrix") == "Passed"
    assert _item_state(checker, "check STA QoR summary data") == "Failed"


def test_sta_checklist_uses_json_nvp_not_text_report_columns(tmp_path):
    checker = _sta_checker(
        tmp_path,
        summary=qor_summary(setup_nvp=1),
        paths=timing_paths(),
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
        paths=timing_paths(),
    )

    assert checker.check() is False
    assert _item_state(checker, "check STA QoR summary data") == "Failed"


def test_sta_checklist_warns_when_frequency_target_is_not_configured(tmp_path):
    checker = _sta_checker(
        tmp_path,
        summary=qor_summary(),
        paths=timing_paths(),
        frequency_target=0,
    )

    assert checker.check() is True
    assert _item_state(checker, "check frequency requirement") == "Warning"


def test_sta_checklist_rejects_malformed_timing_paths_json(tmp_path):
    checker = _sta_checker(
        tmp_path,
        summary=qor_summary(),
        paths={"schema_version": 1, "corner": "MAX_125/RCworst", "path_limit": 20, "paths": [{}]},
    )

    assert checker.check() is False
    assert _item_state(checker, "check STA timing path data") == "Failed"


def test_sta_summary_paths_do_not_fallback_to_obsolete_output(tmp_path):
    workspace = SimpleNamespace(config={StepEnum.STA.value: ""})
    feature_root = tmp_path / "feature"
    output_path = tmp_path / "output" / "MAX_125" / "RCworst" / "qor_summary.json"
    _write(output_path, json.dumps(qor_summary()))

    assert sta_qor_summary_paths(workspace, feature_root) == []

    feature_path = feature_root / "MAX_125" / "RCworst" / "qor_summary.json"
    _write(feature_path, json.dumps(qor_summary()))

    assert sta_qor_summary_paths(workspace, feature_root) == [
        ("MAX_125/RCworst", feature_path),
    ]
