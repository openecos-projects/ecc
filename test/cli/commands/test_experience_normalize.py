import json

import pytest
from typer.testing import CliRunner

from chipcompiler.cli.app import app
from ecc_experience.knowledge.store import ExperienceStore
from test.experience.test_summary import _case


@pytest.mark.parametrize("condition,exit_code", [("pass", 0), ("empty", 7), ("invalid", 6)])
def test_normalize_works_outside_projects_and_preserves_report_on_failure(
    tmp_path, monkeypatch, condition, exit_code
):
    monkeypatch.chdir(tmp_path)
    first = ExperienceStore(tmp_path / "first")
    first.root.mkdir()
    second = ExperienceStore(tmp_path / "second")
    second.root.mkdir()
    if condition != "empty":
        case = _case(tmp_path, "cli")
        first.put(case, {})
        second.put(case, {})
        if condition == "invalid":
            (first.case_directory(case.case_id) / "case.json").write_text("invalid")

    result = CliRunner().invoke(
        app,
        [
            "experience",
            "normalize",
            "--store",
            str(first.root),
            "--store",
            str(second.root),
            "--output",
            "normalized",
            "--json",
        ],
    )

    assert result.exit_code == exit_code, result.output
    records = json.loads(result.stdout)
    assert len(records) == 1
    assert (records[0]["experience"], records[0]["exit_code"]) == ("normalize", exit_code)
    assert records[0]["counts"]["stores"] == 2
    assert (tmp_path / "normalized/normalized-manifest.json").is_file()


@pytest.mark.parametrize(
    "output,exit_code,error",
    [
        ("exists", 21, "experience_normalize_conflict"),
        ("store/nested", 2, "experience_normalize_invalid"),
    ],
)
def test_normalize_reports_path_errors_without_overwriting(
    tmp_path, monkeypatch, output, exit_code, error
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "store").mkdir()
    (tmp_path / "exists").write_text("preserve")

    result = CliRunner().invoke(
        app,
        [
            "experience",
            "normalize",
            "--store",
            "store",
            "--output",
            output,
            "--json",
        ],
    )

    assert result.exit_code == exit_code, result.output
    assert json.loads(result.stdout)[0]["error"] == error
    assert (tmp_path / "exists").read_text() == "preserve"


def test_normalize_requires_a_store_and_output():
    result = CliRunner().invoke(app, ["experience", "normalize"])
    assert result.exit_code == 2
