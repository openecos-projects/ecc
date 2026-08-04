#!/usr/bin/env python

import shutil
from pathlib import Path

import pytest

from chipcompiler.tools.ecc.module import ECCToolsModule


class FakeStaEcc:
    def __init__(self):
        self.calls = []
        self.structured_timing_filenames = (
            "qor_summary.json",
            "timing_paths.json",
        )
        self.emit_sdf = True

    def lib_init(self, **kwargs):
        self.calls.append(("lib_init", kwargs))
        return True

    def sdc_init(self, sdc_path):
        self.calls.append(("sdc_init", sdc_path))
        return True

    def spef_init(self, spef_path):
        self.calls.append(("spef_init", spef_path))
        return True

    def init_sta(self, **kwargs):
        self.calls.append(("init_sta", kwargs))
        # iSTA wipes the temp directory on init, like DataManager::input does.
        shutil.rmtree(kwargs["config_dict"]["-temp_directory_path"], ignore_errors=True)
        return True

    def run_sta(self):
        self.calls.append(("run_sta", (), {}))
        config_dict = None
        for call in reversed(self.calls):
            if len(call) == 2 and call[0] == "init_sta":
                config_dict = call[1]["config_dict"]
                break
        assert config_dict is not None
        report_dir = Path(config_dict["-temp_directory_path"]) / "timing_reporter"
        report_dir.mkdir(parents=True, exist_ok=True)
        if config_dict.get("-output_timing_reports") == "1":
            (report_dir / "qor_summary.rpt").write_text("report\n", encoding="utf-8")
            (report_dir / "timing_max.rpt").write_text("report\n", encoding="utf-8")
        if config_dict.get("-output_timing_features") == "1":
            for filename in self.structured_timing_filenames:
                (report_dir / filename).write_text("{}\n", encoding="utf-8")
        if self.emit_sdf:
            sdf_dir = Path(config_dict["-temp_directory_path"]) / "sdf_writer"
            sdf_dir.mkdir(parents=True, exist_ok=True)
            (sdf_dir / "gcd.sdf").write_text("(DELAYFILE\n)\n", encoding="utf-8")
        return True

    def destroy_sta(self):
        self.calls.append(("destroy_sta", (), {}))
        return True


def make_module() -> ECCToolsModule:
    module = ECCToolsModule.__new__(ECCToolsModule)
    module.ecc = FakeStaEcc()
    return module


def test_run_timing_splits_text_reports_and_structured_artifacts(tmp_path):
    module = make_module()
    report_dir = tmp_path / "report" / "MAX_125" / "RCworst"
    feature_dir = tmp_path / "feature" / "MAX_125" / "RCworst"

    module.run_timing(
        work_dir=tmp_path / "data" / "sta",
        report_dir=report_dir,
        feature_dir=feature_dir,
        output_modes=("structured", "report"),
        max_paths_per_analysis=7,
        corner="MAX_125/RCworst",
    )

    assert (report_dir / "qor_summary.rpt").is_file()
    assert (report_dir / "timing_max.rpt").is_file()
    assert (feature_dir / "qor_summary.json").is_file()
    assert (feature_dir / "timing_paths.json").is_file()
    init_config = next(
        call[1] for call in module.ecc.calls if len(call) == 2 and call[0] == "init_sta"
    )
    assert init_config["config_dict"] == {
        "-temp_directory_path": str(tmp_path / "data" / "sta"),
        "-output_timing_reports": "1",
        "-output_timing_features": "1",
        "-timing_path_limit": "7",
        "-timing_corner": "MAX_125/RCworst",
    }


def test_run_timing_accepts_qor_summary_without_timing_paths(tmp_path):
    module = make_module()
    module.ecc.structured_timing_filenames = ("qor_summary.json",)
    feature_dir = tmp_path / "feature" / "MAX_125" / "RCworst"

    module.run_timing(
        work_dir=tmp_path / "data" / "sta",
        feature_dir=feature_dir,
        output_modes=("structured",),
        corner="MAX_125/RCworst",
    )

    assert (feature_dir / "qor_summary.json").is_file()
    assert not (feature_dir / "timing_paths.json").exists()


def test_run_timing_rejects_invalid_output_modes(tmp_path):
    module = make_module()

    with pytest.raises(ValueError, match="Unsupported STA output modes"):
        module.run_timing(
            work_dir=tmp_path / "data" / "sta",
            feature_dir=tmp_path / "feature",
            output_modes=("structured", "raw"),
        )

    assert module.ecc.calls == []


def test_run_timing_publishes_sdf_alongside_text_reports(tmp_path):
    module = make_module()
    report_dir = tmp_path / "report" / "MAX_125" / "RCworst"

    module.run_timing(
        work_dir=tmp_path / "data" / "sta",
        report_dir=report_dir,
        output_modes=("report",),
        corner="MAX_125/RCworst",
    )

    assert sorted(path.name for path in report_dir.iterdir()) == [
        "gcd.sdf",
        "qor_summary.rpt",
        "timing_max.rpt",
    ]


def test_run_timing_raises_when_sdf_missing(tmp_path):
    module = make_module()
    module.ecc.emit_sdf = False
    report_dir = tmp_path / "report" / "MAX_125" / "RCworst"

    with pytest.raises(FileNotFoundError, match="SDF"):
        module.run_timing(
            work_dir=tmp_path / "data" / "sta",
            report_dir=report_dir,
            output_modes=("report",),
            corner="MAX_125/RCworst",
        )

    assert not report_dir.exists()


def test_run_timing_structured_only_does_not_require_sdf(tmp_path):
    module = make_module()
    module.ecc.emit_sdf = False
    feature_dir = tmp_path / "feature" / "MAX_125" / "RCworst"

    module.run_timing(
        work_dir=tmp_path / "data" / "sta",
        feature_dir=feature_dir,
        output_modes=("structured",),
        corner="MAX_125/RCworst",
    )

    assert (feature_dir / "qor_summary.json").is_file()


def test_run_timing_removes_stale_sdf_when_rerun_fails(tmp_path):
    module = make_module()
    report_dir = tmp_path / "report" / "MAX_125" / "RCworst"

    module.run_timing(
        work_dir=tmp_path / "data" / "sta",
        report_dir=report_dir,
        output_modes=("report",),
        corner="MAX_125/RCworst",
    )
    assert (report_dir / "gcd.sdf").is_file()

    module.ecc.emit_sdf = False
    with pytest.raises(FileNotFoundError, match="SDF"):
        module.run_timing(
            work_dir=tmp_path / "data" / "sta",
            report_dir=report_dir,
            output_modes=("report",),
            corner="MAX_125/RCworst",
        )

    assert not (report_dir / "gcd.sdf").exists()


def test_run_timing_publishes_nothing_when_structured_artifact_missing(tmp_path):
    module = make_module()
    module.ecc.structured_timing_filenames = ("timing_paths.json",)
    report_dir = tmp_path / "report" / "MAX_125" / "RCworst"
    feature_dir = tmp_path / "feature" / "MAX_125" / "RCworst"

    with pytest.raises(FileNotFoundError, match="structured"):
        module.run_timing(
            work_dir=tmp_path / "data" / "sta",
            report_dir=report_dir,
            feature_dir=feature_dir,
            output_modes=("report", "structured"),
            corner="MAX_125/RCworst",
        )

    assert not report_dir.exists()
    assert not feature_dir.exists()


def test_run_timing_stringifies_path_arguments(tmp_path):
    module = make_module()

    module.run_timing(
        config=Path("/ws/config/sta.json"),
        work_dir=tmp_path / "sta_work",
        report_dir=tmp_path / "sta_report",
        feature_dir=tmp_path / "sta_feature",
        lib_paths=[Path("/pdk/lib.lib")],
        sdc_path=Path("/ws/design.sdc"),
        spef_path=Path("/ws/design.spef"),
        corner="MAX_125/RCworst",
    )

    assert module.ecc.calls == [
        ("lib_init", {"lib_paths": ["/pdk/lib.lib"]}),
        ("sdc_init", "/ws/design.sdc"),
        ("spef_init", "/ws/design.spef"),
        (
            "init_sta",
            {
                "config": "/ws/config/sta.json",
                "config_dict": {
                    "-temp_directory_path": str(tmp_path / "sta_work"),
                    "-output_timing_reports": "1",
                    "-output_timing_features": "1",
                    "-timing_path_limit": "20",
                    "-timing_corner": "MAX_125/RCworst",
                },
            },
        ),
        ("run_sta", (), {}),
        ("destroy_sta", (), {}),
    ]
