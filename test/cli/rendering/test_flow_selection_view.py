"""The step table shows parallel stages and step-to-step dependencies."""

import io

import pytest
from rich.console import Console

from chipcompiler.cli.project.flow_status_view import (
    StatusView,
    status_view,
    view_from_records,
    view_records,
)
from chipcompiler.cli.rendering.flow_selection_view import (
    flow_edit_summary,
    flow_selection_view,
    render_flow_status_text,
)
from chipcompiler.data import DEFAULT_SKIP_STEPS
from chipcompiler.data.flow_plan import inserted_chain, plan_flow, preset_chain

_LEGEND = "┐…┘ same number = can run in parallel, up to 4 at once"


def _view(skip=DEFAULT_SKIP_STEPS, max_parallel_steps=4, insert=(), **bounds) -> StatusView:
    plan = plan_flow(
        preset_chain("rtl2gds"), skip_steps=skip, inserted=inserted_chain(insert), **bounds
    )
    return status_view(plan, flow="rtl2gds", max_parallel_steps=max_parallel_steps)


def _render(view: StatusView, width: int = 140) -> list[str]:
    out = io.StringIO()
    Console(file=out, width=width, force_terminal=False, highlight=False).print(
        flow_selection_view(view)
    )
    return out.getvalue().splitlines()


def _row(lines: list[str], step: str) -> str:
    return next(line for line in lines if step in line.split())


def test_the_post_filler_stage_is_bracketed_and_lettered():
    lines = _render(_view())

    assert [_row(lines, step).split()[1:3] for step in ("lvs", "drc", "RCX")] == [
        ["13a", "┐"],
        ["13b", "│"],
        ["13e", "┘"],
    ]
    assert _row(lines, "sta").split()[1:3] == ["14a", "┐"]
    assert _row(lines, "powerAnalysis").split()[1:3] == ["14b", "┘"]
    assert _LEGEND in lines


def test_a_step_alone_in_its_stage_has_a_bare_number_and_no_bracket():
    assert _row(_render(_view()), "route").split()[:4] == ["[✔]", "11", "route", "ecc"]


def test_the_table_lists_producers_and_the_check_tag():
    lines = _render(_view())

    assert "Timing optimization, CTS" in _row(lines, "route")
    assert _row(lines, "sta").split()[4:] == ["ecc", "RCX,", "CTS", "check"]
    assert "(rtl)" in _row(lines, "Synthesis")


def test_the_label_and_bracket_share_one_column_aligned_to_the_widest_label():
    lines = _render(_view())

    assert [_row(lines, step)[5:10].rstrip() for step in ("filler", "lvs", "drc", "RCX")] == [
        "12",
        "13a ┐",
        "13b │",
        "13e ┘",
    ]


def test_a_disabled_step_has_an_empty_number_and_the_stages_renumber():
    lines = _render(_view(skip=[*DEFAULT_SKIP_STEPS, "CTS"]))

    assert _row(lines, "CTS").split()[:4] == ["[", "]", "CTS", "ecc"]
    assert _row(lines, "legalization").split()[1] == "8"
    assert _row(lines, "Harden").split()[1] == "15"


def test_a_disabled_step_inside_a_parallel_stage_keeps_the_bracket_continuous():
    lines = _render(_view(skip=[*DEFAULT_SKIP_STEPS, "drc"]))

    assert [_row(lines, step).split()[:3] for step in ("lvs", "drc", "antennaCheck")] == [
        ["[✔]", "13a", "┐"],
        ["[", "]", "│"],
        ["[✔]", "13b", "│"],
    ]
    assert _LEGEND in lines


def test_a_disabled_step_before_a_parallel_stage_is_outside_the_bracket():
    lines = _render(_view(skip=[*DEFAULT_SKIP_STEPS, "lvs"]))

    assert [_row(lines, step).split()[:3] for step in ("lvs", "drc", "RCX")] == [
        ["[", "]", "lvs"],
        ["[✔]", "13a", "┐"],
        ["[✔]", "13d", "┘"],
    ]


def test_no_legend_without_a_parallel_stage():
    lines = _render(_view(start="Synthesis", end="preFloorplan"))

    assert _LEGEND not in lines
    assert not any(char in line for line in lines for char in "┐│┘")


@pytest.mark.parametrize(
    ("max_parallel_steps", "legend"),
    [
        (4, "┐…┘ same number = can run in parallel, up to 4 at once"),
        (2, "┐…┘ same number = can run in parallel, up to 2 at once"),
        (1, "┐…┘ same number = independent steps; run one at a time (max_parallel_steps = 1)"),
    ],
)
def test_the_legend_states_how_many_steps_of_a_stage_run_at_once(max_parallel_steps, legend):
    lines = _render(_view(max_parallel_steps=max_parallel_steps))

    assert [line for line in lines if "┐…┘" in line] == [legend]
    # The stage labels and brackets show whatever the value.
    assert _row(lines, "lvs").split()[1:3] == ["13a", "┐"]


def test_no_legend_for_one_at_a_time_without_a_parallel_stage():
    lines = _render(_view(max_parallel_steps=1, start="Synthesis", end="preFloorplan"))

    assert not any("┐…┘" in line for line in lines)


@pytest.mark.parametrize("max_parallel_steps", [1, 4])
def test_records_round_trip_through_the_view(max_parallel_steps):
    view = _view(max_parallel_steps=max_parallel_steps)

    assert view_from_records(view_records(view)) == view


def test_a_max_parallel_steps_record_is_an_integer():
    records = view_records(_view())

    for value in (True, "4", None):
        with pytest.raises(ValueError, match="max_parallel_steps must be an integer"):
            view_from_records([{**records[0], "max_parallel_steps": value}, *records[1:]])
    with pytest.raises(ValueError, match="lacks 'max_parallel_steps'"):
        view_from_records(
            [{k: v for k, v in records[0].items() if k != "max_parallel_steps"}, *records[1:]]
        )


@pytest.mark.parametrize(
    ("written", "heading"),
    [(True, "✔ wrote [flow] to ecc.toml"), (False, "Write [flow] to ecc.toml?")],
)
def test_the_edit_summary_shows_max_parallel_steps(written, heading):
    out = io.StringIO()
    summary = {
        "record": "flow_edit",
        "status": "written",
        "path": "ecc.toml",
        "preset": "rtl2gds",
        "lec_engine": "kepler_formal",
        "skip_steps": ["diff_opt", "CTS"],
        "insert_steps": [],
        "max_parallel_steps": 2,
        "enabled": [],
        "disabled": ["CTS"],
        "inserted": [],
        "removed": [],
    }

    Console(file=out, width=100, force_terminal=False, highlight=False).print(
        flow_edit_summary([summary], written=written)
    )

    assert out.getvalue().splitlines() == [
        heading,
        "  preset = rtl2gds · lec_engine = kepler_formal",
        "  skip_steps = diff_opt, CTS",
        "  max_parallel_steps = 2",
        "  disabled: CTS",
    ]


def _rows(lines: list[str]) -> list[list[str]]:
    """The words of each step row, with the lines its wrapped cells continue on."""
    rows: list[list[str]] = []
    for line in lines:
        if line.startswith("["):
            rows.append([])
        if rows and line.startswith(("[", " ")):
            rows[-1].extend(word for word in line.split() if word not in "┐│┘")
    return [sorted(row) for row in rows]


def _expected_rows(view: StatusView) -> list[list[str]]:
    rows: list[list[str]] = []
    for step in view.steps:
        tags = [
            tag
            for tag, shown in (
                ("check", step.check),
                ("optional", step.optional),
                ("target", step.target),
            )
            if shown
        ]
        unprovided = [f"({capability})" for capability, producer in step.needs if producer is None]
        cells = [
            "[✔]" if step.enabled else "[ ]",
            step.label,
            step.step,
            step.tool,
            ", ".join([*step.after, *unprovided]),
            ", ".join(step.provides),
            " · ".join(tags),
        ]
        rows.append(sorted(" ".join(cells).split()))
    return rows


@pytest.mark.parametrize(
    "view",
    [
        pytest.param(_view(), id="default"),
        pytest.param(_view(start="Synthesis", end="postRouteLec"), id="synthesis-to-postRouteLec"),
    ],
)
def test_a_narrow_terminal_wraps_every_cell_without_cutting_a_word(view):
    lines = _render(view, width=110)

    assert not any("…" in line for line in lines if line != _LEGEND)
    assert len([line for line in lines if line.startswith(("[", " "))]) > len(view.steps) + 1
    assert _rows(lines) == _expected_rows(view)


def test_a_stage_record_is_an_integer_or_null():
    records = view_records(_view())
    step = next(record for record in records if record["record"] == "flow_step")

    for stage in (True, "1"):
        with pytest.raises(ValueError, match="stage must be an integer"):
            view_from_records([*records[:1], {**step, "stage": stage}])


def test_piped_output_is_as_wide_as_the_table_needs():
    out = io.StringIO()

    render_flow_status_text(view_records(_view()), file=out, color=False)

    lines = out.getvalue().splitlines()
    assert not any("…" in line for line in lines if line != _LEGEND)
    assert "Timing optimization, CTS" in _row(lines, "route")
    assert "check · optional" in _row(lines, "postRouteLec")


class _ColorlessTty(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_a_colorless_terminal_wraps_instead_of_taking_the_piped_branch(monkeypatch):
    """A real terminal without color (NO_COLOR, TERM=dumb) wraps within its width."""
    monkeypatch.setenv("COLUMNS", "110")
    records = view_records(_view())
    piped = io.StringIO()
    terminal = _ColorlessTty()

    render_flow_status_text(records, file=piped, color=False)
    render_flow_status_text(records, file=terminal, color=False)

    assert max(len(line) for line in piped.getvalue().splitlines()) > 110
    assert max(len(line) for line in terminal.getvalue().splitlines()) <= 110


def test_an_inserted_lec_row_follows_its_step_and_is_tagged_inserted():
    lines = _render(_view(insert=("lec@CTS",)))

    assert _row(lines, "lec@CTS").split() == [
        "[✔]",
        "9",
        "lec@CTS",
        "kepler_formal",
        "CTS,",
        "Synthesis",
        "inserted",
    ]
    assert lines.index(_row(lines, "lec@CTS")) == lines.index(_row(lines, "CTS")) + 1


def test_a_range_ending_at_an_inserted_steps_step_keeps_the_target_on_that_step():
    view = _view(skip=(), insert=("lec@route",), start="CTS", end="route")

    assert [(step.step, step.target) for step in view.steps[-2:]] == [
        ("route", True),
        ("lec@route", False),
    ]
