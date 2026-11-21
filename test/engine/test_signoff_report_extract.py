import pytest

from chipcompiler.engine.signoff.report_extract import _convert_unit_to_mw, parse_power_rpt

REPORT = """Cell Internal Power  =   51.2062 uW
Net Switching Power  =   11.5906 uW
Total Dynamic Power  =   62.7968 uW
Cell Leakage Power   =    1.7151 uW
Total          5.1206e-02 mW     1.1591e-02 mW      1715.1068 nW     6.4512e-02 mW
"""


def test_parse_power_report_units_and_exponents():
    parsed = parse_power_rpt(REPORT)

    assert parsed.internal_power_mw == pytest.approx(0.0512062)
    assert parsed.switching_power_mw == pytest.approx(0.0115906)
    assert parsed.dynamic_power_mw == pytest.approx(0.0627968)
    assert parsed.leakage_power_mw == pytest.approx(0.0017151)
    assert parsed.total_power_mw == pytest.approx(0.064512)


@pytest.mark.parametrize(
    "line",
    [
        "Cell Internal Power = - mW",
        "Total Dynamic Power = . mW",
        "Net Switching Power = e mW",
        "Cell Leakage Power = +. nW",
    ],
)
def test_malformed_number_is_ignored_not_an_exception(line):
    parsed = parse_power_rpt(line)

    assert parsed.internal_power_mw is None
    assert parsed.switching_power_mw is None
    assert parsed.leakage_power_mw is None


@pytest.mark.parametrize(
    "value,unit,expected",
    [
        (2.0, "mW", 2.0),
        (2.0, "MW", 2.0e9),
        (2.0, "W", 2000.0),
        (2.0, "kW", 2.0e6),
        (2.0, "uW", 2.0e-3),
        (2.0, "nW", 2.0e-6),
        (2.0, "pW", 2.0e-9),
    ],
)
def test_unit_conversion_keeps_milli_and_mega_distinct(value, unit, expected):
    assert _convert_unit_to_mw(value, unit) == pytest.approx(expected)


def test_parse_power_report_micro_units_and_sci_voltage():
    text = "Global Operating Voltage = 1.1e+00\nTotal   51.2 µW   11.6 µW   1.7 µW   64.5 µW\n"
    parsed = parse_power_rpt(text)
    assert parsed.voltage_v == pytest.approx(1.1)
    assert parsed.total_power_mw == pytest.approx(0.0645)
