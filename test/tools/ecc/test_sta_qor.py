#!/usr/bin/env python

import json

from chipcompiler.tools.ecc.sta_qor import (
    StaPowerSummary,
    read_sta_power_summary,
    read_sta_power_summary_json,
    sta_power_summary_payload,
)

REAL_POWER_REPORT = """Design : gcd
Operating Conditions: ICS_N55_H7BR_ss_mos_RCworst_1.08_125
Analysis Effort : low
Wire Load Model : ZeroWireload
Global Operating Voltage = 1.08

Dynamic Power Units = 1mW
Leakage Power Units = 1nW

Cell Internal Power  =   51.2062 uW
Net Switching Power  =   11.5906 uW
Total Dynamic Power  =   62.7968 uW
Cell Leakage Power   =    1.7151 uW

                 Internal         Switching           Leakage            Total
Power Group      Power            Power               Power              Power   (   %    )  Attrs
--------------------------------------------------------------------------------------------------
register       3.6408e-02        2.5064e-03          364.6992        3.9279e-02  (  60.89%)
combinational  1.4798e-02        9.0842e-03         1350.4076        2.5233e-02  (  39.11%)
--------------------------------------------------------------------------------------------------
Total          5.1206e-02 mW     1.1591e-02 mW      1715.1068 nW     6.4512e-02 mW
"""


def test_read_sta_power_summary_parses_real_report(tmp_path):
    report_path = tmp_path / "power.rpt"
    report_path.write_text(REAL_POWER_REPORT, encoding="utf-8")

    assert read_sta_power_summary(report_path) == StaPowerSummary(
        path=report_path,
        internal_uw=51.2062,
        switching_uw=11.5906,
        dynamic_uw=62.7968,
        leakage_uw=1.7151,
    )


def test_read_sta_power_summary_normalizes_units(tmp_path):
    report_path = tmp_path / "power.rpt"
    report_path.write_text(
        "Cell Internal Power  =  1.5 mW\n"
        "Net Switching Power  =  200 nW\n"
        "Total Dynamic Power  =  2.5e-03 W\n"
        "Cell Leakage Power   =  3000 pW\n",
        encoding="utf-8",
    )

    assert read_sta_power_summary(report_path) == StaPowerSummary(
        path=report_path,
        internal_uw=1500.0,
        switching_uw=0.2,
        dynamic_uw=2500.0,
        leakage_uw=0.003,
    )


def test_read_sta_power_summary_returns_none_for_missing_file(tmp_path):
    assert read_sta_power_summary(tmp_path / "power.rpt") is None


def test_read_sta_power_summary_returns_none_for_empty_file(tmp_path):
    report_path = tmp_path / "power.rpt"
    report_path.write_text("", encoding="utf-8")

    assert read_sta_power_summary(report_path) is None


def test_read_sta_power_summary_returns_none_when_summary_line_missing(tmp_path):
    report_path = tmp_path / "power.rpt"
    report_path.write_text(
        "Cell Internal Power  =  51.2062 uW\n"
        "Net Switching Power  =  11.5906 uW\n"
        "Total Dynamic Power  =  62.7968 uW\n",
        encoding="utf-8",
    )

    assert read_sta_power_summary(report_path) is None


def test_read_sta_power_summary_returns_none_for_invalid_number(tmp_path):
    report_path = tmp_path / "power.rpt"
    report_path.write_text(
        "Cell Internal Power  =  unknown uW\n"
        "Net Switching Power  =  11.5906 uW\n"
        "Total Dynamic Power  =  62.7968 uW\n"
        "Cell Leakage Power   =  1.7151 uW\n",
        encoding="utf-8",
    )

    assert read_sta_power_summary(report_path) is None


def test_read_sta_power_summary_returns_none_for_duplicate_summary_line(tmp_path):
    report_path = tmp_path / "power.rpt"
    report_path.write_text(
        "Cell Internal Power  =  51.2062 uW\n"
        "Cell Internal Power  =  51.2062 uW\n"
        "Net Switching Power  =  11.5906 uW\n"
        "Total Dynamic Power  =  62.7968 uW\n"
        "Cell Leakage Power   =  1.7151 uW\n",
        encoding="utf-8",
    )

    assert read_sta_power_summary(report_path) is None


def test_read_sta_power_summary_returns_none_for_non_utf8_content(tmp_path):
    report_path = tmp_path / "power.rpt"
    report_path.write_bytes(b"Cell Internal Power  =  51.2062 uW\n\xff\xfe\r\x00")

    assert read_sta_power_summary(report_path) is None


def test_sta_power_summary_json_round_trip(tmp_path):
    summary_path = tmp_path / "power_summary.json"
    summary = StaPowerSummary(
        path=tmp_path / "power.rpt",
        internal_uw=51.2062,
        switching_uw=11.5906,
        dynamic_uw=62.7968,
        leakage_uw=1.7151,
    )
    summary_path.write_text(json.dumps(sta_power_summary_payload(summary)), encoding="utf-8")

    assert read_sta_power_summary_json(summary_path) == StaPowerSummary(
        path=summary_path,
        internal_uw=51.2062,
        switching_uw=11.5906,
        dynamic_uw=62.7968,
        leakage_uw=1.7151,
    )


def test_read_sta_power_summary_json_returns_none_for_wrong_schema_version(tmp_path):
    summary_path = tmp_path / "power_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "internal_uw": 51.2062,
                "switching_uw": 11.5906,
                "dynamic_uw": 62.7968,
                "leakage_uw": 1.7151,
            }
        ),
        encoding="utf-8",
    )

    assert read_sta_power_summary_json(summary_path) is None


def test_read_sta_power_summary_json_returns_none_when_field_missing(tmp_path):
    summary_path = tmp_path / "power_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "internal_uw": 51.2062,
                "switching_uw": 11.5906,
                "dynamic_uw": 62.7968,
            }
        ),
        encoding="utf-8",
    )

    assert read_sta_power_summary_json(summary_path) is None


def test_read_sta_power_summary_json_returns_none_for_malformed_json(tmp_path):
    summary_path = tmp_path / "power_summary.json"
    summary_path.write_text("{not json\n", encoding="utf-8")

    assert read_sta_power_summary_json(summary_path) is None
