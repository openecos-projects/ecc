"""A project's step selection: entry step, capability errors and warnings."""

import pytest

from chipcompiler.cli.project.config import load_project_config, validate_project_config
from chipcompiler.cli.project.flow_selection import (
    FlowSelectionChangedError,
    entry_step,
    selection_errors,
    selection_warnings,
    write_flow_selection,
)


def _config(tmp_path, flow_extra=""):
    (tmp_path / "ecc.toml").write_text(
        "[design]\n"
        'name = "gcd"\n'
        'top = "gcd"\n'
        'rtl = ["rtl/gcd.v"]\n'
        'clock_port = "clk"\n'
        "frequency_mhz = 100.0\n"
        "\n[flow]\n"
        'preset = "rtl2gds"\n' + flow_extra
    )
    return load_project_config(str(tmp_path / "ecc.toml"))


@pytest.mark.parametrize(
    ("flow_extra", "flow_config", "expected"),
    [
        ("", None, "synthesis"),
        ('skip_steps = ["synthesis"]\n', None, "pre_floorplan"),
        # The run's own policy wins over ecc.toml.
        ('skip_steps = ["synthesis"]\n', {"skip_steps": []}, "synthesis"),
        ("", {"start_step": "placement", "end_step": "routing"}, "placement"),
    ],
)
def test_entry_step_is_the_first_step_the_selection_keeps(
    tmp_path, flow_extra, flow_config, expected
):
    assert entry_step(_config(tmp_path, flow_extra), flow_config) == expected


def test_code_default_policy_is_not_rechecked(tmp_path):
    cfg = _config(tmp_path)

    assert (selection_errors(cfg, None), selection_warnings(cfg, None)) == ([], [])


def test_selection_missing_required_data_is_a_config_error(tmp_path):
    cfg = _config(tmp_path, 'skip_steps = ["legalization", "timing_optimization"]\n')

    expected = "flow.skip_steps: routing requires legal; enable timing_optimization or legalization"
    assert selection_errors(cfg, None) == [expected]
    assert expected in validate_project_config(cfg)


def test_skipped_range_start_is_a_config_error(tmp_path):
    cfg = _config(tmp_path)

    assert selection_errors(
        cfg, {"start_step": "cts", "end_step": "routing", "skip_steps": ["cts"]}
    ) == ["flow.skip_steps: 'cts' starts the flow range and cannot be skipped"]


def test_degraded_steps_are_warnings(tmp_path):
    cfg = _config(tmp_path, 'skip_steps = ["cts"]\n')

    assert selection_errors(cfg, None) == []
    warnings = selection_warnings(cfg, None)
    assert [warning["step"] for warning in warnings] == [
        "routing",
        "sta",
        "power_analysis",
        "harden",
    ]
    assert warnings[0] == {
        "kind": "warning",
        "warning": "flow_step_degraded",
        "step": "routing",
        "missing": ["clock_tree"],
        "fixes": ["cts"],
        "reason": "routing runs with degraded results without clock_tree; enable cts",
    }


def test_written_selection_keeps_the_rest_of_ecc_toml(tmp_path):
    config_path = tmp_path / "ecc.toml"
    config_path.write_text(
        "# project notes\n"
        "[design]\n"
        'name = "gcd"  # the top\n'
        "\n[flow]\n"
        "# preset: rtl2gds | syn_sta | synthesis_lec\n"
        'preset = "rtl2gds"\n'
        "# skipped steps\n"
        'skip_steps = ["diff_opt"]\n'
        "\n[params.cts]\n"
        "# fanout\n"
        "max_fanout = 32\n"
    )

    write_flow_selection(
        str(config_path),
        preset="rtl2gds",
        lec_engine="kepler_formal",
        skip_steps=["diff_opt", "cts"],
        insert_steps=[],
        max_parallel_steps=2,
    )

    # Declared keys change in place; the undeclared keys open [flow].
    assert config_path.read_text() == (
        "# project notes\n"
        "[design]\n"
        'name = "gcd"  # the top\n'
        "\n[flow]\n"
        "max_parallel_steps = 2\n"
        'lec_engine = "kepler_formal"\n'
        "# preset: rtl2gds | syn_sta | synthesis_lec\n"
        'preset = "rtl2gds"\n'
        "# skipped steps\n"
        'skip_steps = ["diff_opt", "cts"]\n'
        "\n[params.cts]\n"
        "# fanout\n"
        "max_fanout = 32\n"
    )


def test_written_selection_rejects_an_outdated_flow(tmp_path):
    expected = _config(tmp_path, "max_parallel_steps = 2\n")
    config_path = tmp_path / "ecc.toml"
    _config(tmp_path, "max_parallel_steps = 3\n")
    updated = config_path.read_bytes()

    with pytest.raises(FlowSelectionChangedError, match="Project flow changed"):
        write_flow_selection(
            str(config_path),
            preset="rtl2gds",
            lec_engine="kepler_formal",
            skip_steps=["diff_opt"],
            insert_steps=[],
            max_parallel_steps=2,
            expected=expected,
        )

    assert config_path.read_bytes() == updated


def test_written_selection_adds_a_missing_flow_section(tmp_path):
    config_path = tmp_path / "ecc.toml"
    config_path.write_text('[design]\nname = "gcd"\n')

    write_flow_selection(
        str(config_path),
        preset="rtl2gds",
        lec_engine="kepler_formal",
        skip_steps=[],
        insert_steps=[],
        max_parallel_steps=4,
    )

    assert config_path.read_text() == (
        '[design]\nname = "gcd"\n'
        "\n[flow]\n"
        "max_parallel_steps = 4\n"
        "skip_steps = []\n"
        'lec_engine = "kepler_formal"\n'
        'preset = "rtl2gds"\n'
    )


def test_a_declared_max_parallel_steps_changes_in_place(tmp_path):
    config_path = tmp_path / "ecc.toml"
    config_path.write_text(
        "[flow]\n"
        'preset = "rtl2gds"\n'
        'lec_engine = "kepler_formal"\n'
        "skip_steps = []\n"
        "# one at a time\n"
        "max_parallel_steps = 1\n"
    )

    write_flow_selection(
        str(config_path),
        preset="rtl2gds",
        lec_engine="kepler_formal",
        skip_steps=[],
        insert_steps=[],
        max_parallel_steps=3,
    )

    assert config_path.read_text() == (
        "[flow]\n"
        'preset = "rtl2gds"\n'
        'lec_engine = "kepler_formal"\n'
        "skip_steps = []\n"
        "# one at a time\n"
        "max_parallel_steps = 3\n"
    )
