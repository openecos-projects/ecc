import json
from types import SimpleNamespace

import pytest

from chipcompiler.analysis.qor import build_qor_analysis
from chipcompiler.analysis.qor.schema import validate_report
from chipcompiler.cli import main as cli_main
from chipcompiler.data.step import step_directory_for_tool


@pytest.fixture
def matrix_project(tmp_path, manifest_stubs):
    project = tmp_path / "project"
    project.mkdir()
    entries = []

    def add(
        workspace_id, score, *, steps=None, status="success", external=False, profile="balanced"
    ):
        root = (tmp_path if external else project) / workspace_id
        (root / "home").mkdir(parents=True)
        steps = (
            steps
            if steps is not None
            else [
                {"name": "place", "tool": "dreamplace", "state": "Success"},
                {"name": "drc", "tool": "ecc", "state": "Success"},
            ]
        )
        flow = {"steps": steps}
        (root / "home" / "flow.json").write_text(json.dumps(flow))
        workspace = SimpleNamespace(
            directory=root,
            flow=SimpleNamespace(data=flow),
            parameters=SimpleNamespace(data={"design": "gcd"}),
            design=SimpleNamespace(name="gcd"),
        )
        report = build_qor_analysis(workspace).to_dict()
        report["scalar_summary"].update(
            score=score,
            status="NOT_RATED" if score is None else "FAIL" if score == 0 else "GREEN",
            profile=profile,
        )
        assert validate_report(report) == []
        (root / "home" / "qor_report.json").write_text(json.dumps(report))
        entry = manifest_stubs.entry(project, workspace_id, status)
        entry["workspace_path"] = str(root)
        entries.append(entry)
        manifest_stubs.write(project, entries)
        return root, report

    manifest_stubs.write(project, [])
    return project, add


def _run(project, capsys, *options):
    assert cli_main.run(["report", "project", "--project", str(project), "--json", *options]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    return json.loads(captured.out)[0]


def _metric_file(root, step, counts, *, tool="ecc"):
    path = root / step_directory_for_tool(step, tool) / "analysis" / "qor_metrics.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 3,
        "step": step,
        "tool": tool,
        "status": "success",
        "metrics": [
            {"id": metric, "value": value, "unit": "count"} for metric, value in counts.items()
        ],
    }
    path.write_text(json.dumps(payload))
    return path, payload


def _files(root):
    return {
        path.relative_to(root): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }


def test_descending_stable_sort_distinguishes_zero_and_unrated(matrix_project, capsys):
    project, add = matrix_project
    add("unrated", None)
    add("low", 60)
    add("tie_a", 90)
    add("tie_b", 90)
    add("zero", 0)

    report = _run(project, capsys)

    assert [
        (row["workspace_id"], row["qor"]["score"], row["rank"]) for row in report["workspaces"]
    ] == [
        ("tie_a", 90, 1),
        ("tie_b", 90, 2),
        ("low", 60, 3),
        ("zero", 0, 4),
        ("unrated", None, None),
    ]
    assert report["status"] == "partial"


def test_checker_execution_success_is_not_clean(matrix_project, capsys):
    project, add = matrix_project
    root, _report = add("trial", 0)
    path, _payload = _metric_file(root, "drc", {"drc_count": 8})

    row = _run(project, capsys)["workspaces"][0]

    assert row["flow_status"] == "success"
    assert row["steps"][1]["checker"] == {
        "availability": "available",
        "verdict": "violated",
        "has_violations": True,
        "violation_count": 8,
        "counts": {"drc_count": 8},
        "source": str(path),
    }


@pytest.mark.parametrize("step,metric", [("drc", "drc_count"), ("lvs", "lvs_count")])
def test_zero_checker_count_is_clean(matrix_project, capsys, step, metric):
    project, add = matrix_project
    root, _report = add("trial", 90, steps=[{"name": step, "tool": "ecc", "state": "Success"}])
    _metric_file(root, step, {metric: 0})

    report = _run(project, capsys)
    checker = report["workspaces"][0]["steps"][0]["checker"]

    assert (checker["verdict"], checker["has_violations"], checker["violation_count"]) == (
        "clean",
        False,
        0,
    )
    assert report["status"] == "available"


@pytest.mark.parametrize("state", ["Unstart", "Ongoing", "Pending", "Incomplete", "Invalid"])
def test_unfinished_checker_does_not_reuse_old_zero(matrix_project, capsys, state):
    project, add = matrix_project
    root, _report = add("trial", None, steps=[{"name": "drc", "tool": "ecc", "state": state}])
    _metric_file(root, "drc", {"drc_count": 0})

    checker = _run(project, capsys)["workspaces"][0]["steps"][0]["checker"]

    assert checker == {
        "availability": "not_verified",
        "verdict": "unknown",
        "has_violations": None,
        "violation_count": None,
        "counts": {},
        "source": None,
    }


@pytest.mark.parametrize("value", [-1, 1.5, True, "0", None, float("nan"), float("inf")])
def test_invalid_checker_counts_do_not_become_clean(matrix_project, capsys, value):
    project, add = matrix_project
    root, _report = add("trial", 80)
    _metric_file(root, "drc", {"drc_count": value})

    checker = _run(project, capsys)["workspaces"][0]["steps"][1]["checker"]

    assert checker["availability"] == "invalid"
    assert checker["has_violations"] is None
    assert checker["violation_count"] is None


@pytest.mark.parametrize(
    "kind", ["missing", "corrupt", "unit", "duplicate", "tool", "step", "status"]
)
def test_checker_metadata_and_missing_evidence_are_not_zero(matrix_project, capsys, kind):
    project, add = matrix_project
    root, _report = add("trial", 80)
    path, payload = _metric_file(root, "drc", {"drc_count": 0})
    if kind == "missing":
        path.unlink()
    elif kind == "corrupt":
        path.write_text("{")
    else:
        if kind == "unit":
            payload["metrics"][0]["unit"] = "ns"
        elif kind == "duplicate":
            payload["metrics"].append(payload["metrics"][0])
        else:
            payload[kind] = "other"
        path.write_text(json.dumps(payload))

    checker = _run(project, capsys)["workspaces"][0]["steps"][1]["checker"]

    assert checker["has_violations"] is None
    assert checker["violation_count"] is None
    assert checker["verdict"] == "unknown"


@pytest.mark.parametrize(
    "counts,verdict",
    [
        ({"sta_setup_violation_count": 2, "sta_hold_violation_count": 3}, "violated"),
        ({"sta_setup_violation_count": 0, "sta_hold_violation_count": 0}, "clean"),
        ({"sta_setup_violation_count": 0}, "unknown"),
        ({"sta_hold_violation_count": 1}, "violated"),
    ],
)
def test_sta_keeps_setup_and_hold_counts_separate(matrix_project, capsys, counts, verdict):
    project, add = matrix_project
    root, _report = add("trial", 80, steps=[{"name": "sta", "tool": "ecc", "state": "Success"}])
    _metric_file(root, "sta", counts)

    checker = _run(project, capsys)["workspaces"][0]["steps"][0]["checker"]

    assert checker["counts"] == counts
    assert checker["verdict"] == verdict
    assert checker["violation_count"] is None


@pytest.mark.parametrize("step", ["RCX", "powerAnalysis"])
def test_other_checkers_do_not_invent_violation_counts(matrix_project, capsys, step):
    project, add = matrix_project
    add("trial", 80, steps=[{"name": step, "tool": "ecc", "state": "Success"}])

    checker = _run(project, capsys)["workspaces"][0]["steps"][0]["checker"]

    assert checker["availability"] == "not_applicable"
    assert checker["has_violations"] is None
    assert checker["violation_count"] is None


def test_lec_saved_verdict_does_not_invent_counts_or_verify_files(matrix_project, tmp_path, capsys):
    project, add = matrix_project
    root, _report = add(
        "trial", 80, steps=[{"name": "postRouteLec", "tool": "kepler_formal", "state": "Success"}]
    )
    result = (
        root
        / step_directory_for_tool("postRouteLec", "kepler_formal")
        / "output"
        / "gcd_postRouteLec_result.json"
    )
    result.parent.mkdir(parents=True)
    result.write_text(json.dumps({"status": "proven", "gate_verilog": str(tmp_path / "missing.v")}))

    checker = _run(project, capsys)["workspaces"][0]["steps"][0]["checker"]

    assert checker["verdict"] == "proven_saved"
    assert checker["has_violations"] is None
    assert checker["violation_count"] is None


def test_explicit_category_controls_checker_projection(matrix_project, capsys):
    project, add = matrix_project
    root, _report = add(
        "trial",
        80,
        steps=[
            {"name": "drc", "tool": "ecc", "state": "Success", "category": "PNR"},
            {"name": "custom", "tool": "ecc", "state": "Success", "category": "CHECKER"},
        ],
    )
    _metric_file(root, "drc", {"drc_count": 8})

    steps = _run(project, capsys)["workspaces"][0]["steps"]

    assert steps[0]["checker"] is None
    assert steps[1]["checker"]["availability"] == "not_applicable"


def test_different_flows_align_by_step_and_tool(matrix_project, capsys):
    project, add = matrix_project
    add("first", 80, steps=[{"name": "custom", "tool": "one", "state": "Success"}])
    add("second", 90, steps=[{"name": "custom", "tool": "two", "state": "Success"}])

    report = _run(project, capsys)

    assert report["columns"] == [
        {"step": "custom", "token": "custom", "tool": "one"},
        {"step": "custom", "token": "custom", "tool": "two"},
    ]
    assert [row["workspace_id"] for row in report["workspaces"]] == ["second", "first"]


@pytest.mark.parametrize(
    "kind",
    [
        "missing",
        "corrupt",
        "non_utf8",
        "schema",
        "score",
        "nonfinite",
        "nested",
        "identity",
        "stale",
    ],
)
def test_bad_qor_is_retained_without_score(matrix_project, capsys, kind):
    project, add = matrix_project
    root, payload = add("trial", 80)
    path = root / "home" / "qor_report.json"
    if kind == "missing":
        path.unlink()
    elif kind == "corrupt":
        path.write_text("{")
    elif kind == "non_utf8":
        path.write_bytes(b"\xff")
    else:
        if kind == "schema":
            payload["schema_version"] = 999
        elif kind == "score":
            payload["scalar_summary"]["score"] = 10**1000
        elif kind == "nonfinite":
            payload["scalar_summary"]["score"] = float("nan")
        elif kind == "nested":
            payload["scalar_summary"]["status"] = []
        elif kind == "identity":
            payload["workspace"] = "/different/workspace"
        else:
            payload["flow_steps"]["place"] = "Unstart"
        path.write_text(json.dumps(payload))

    report = _run(project, capsys)

    assert len(report["workspaces"]) == 1
    assert report["workspaces"][0]["qor"]["score"] is None
    assert report["workspaces"][0]["rank"] is None
    assert report["status"] == "partial"


@pytest.mark.parametrize("payload", [None, "{", "[]", '{"steps":{}}', '{"steps":[{}]}', b"\xff"])
def test_missing_or_corrupt_flow_does_not_hide_workspace(matrix_project, capsys, payload):
    project, add = matrix_project
    root, _report = add("trial", 80)
    path = root / "home" / "flow.json"
    if payload is None:
        path.unlink()
    elif isinstance(payload, bytes):
        path.write_bytes(payload)
    else:
        path.write_text(payload)

    row = _run(project, capsys)["workspaces"][0]

    assert row["workspace_id"] == "trial"
    assert row["flow_status"] in {"missing", "invalid"}
    assert row["steps"] == []
    assert row["qor"]["score"] is None


def test_archived_and_external_workspaces_are_included(matrix_project, capsys):
    project, add = matrix_project
    add("archived", 90, status="archived")
    add("external", 80, external=True)

    rows = _run(project, capsys)["workspaces"]

    assert [(row["workspace_id"], row["manifest_status"]) for row in rows] == [
        ("archived", "archived"),
        ("external", "success"),
    ]


def test_incomparable_profiles_emit_warning(matrix_project, capsys):
    project, add = matrix_project
    add("balanced", 80)
    add("timing", 90, profile="timing_critical")

    report = _run(project, capsys)

    assert any("different profiles" in warning for warning in report["warnings"])


def test_empty_project_is_successful(matrix_project, capsys):
    project, _add = matrix_project

    report = _run(project, capsys)

    assert report["status"] == "available"
    assert report["columns"] == []
    assert report["workspaces"] == []


@pytest.mark.parametrize("options", [[], ["--plain"], ["--json"]])
def test_all_output_modes_are_read_only(
    matrix_project, tmp_path, monkeypatch, capsys, options, plain_records
):
    project, add = matrix_project
    root, _report = add("trial", 90)
    _metric_file(root, "drc", {"drc_count": 0})
    before = _files(tmp_path)

    def unexpected(*args, **kwargs):
        pytest.fail("project report must only read saved data")

    monkeypatch.setattr("chipcompiler.data.load_workspace", unexpected)
    monkeypatch.setattr("chipcompiler.analysis.qor.refresh_workspace_qor_report", unexpected)
    monkeypatch.setattr("chipcompiler.engine.flow.EngineFlow.run_steps", unexpected)
    assert cli_main.run(["report", "project", "--project", str(project), *options]) == 0

    captured = capsys.readouterr()
    assert captured.err == ""
    assert _files(tmp_path) == before
    if "--json" in options:
        assert json.loads(captured.out)[0]["report"] == "project"
    elif "--plain" in options:
        records = plain_records(captured.out)
        assert [record["record"] for record in records] == [
            "project_report",
            "step_column",
            "step_column",
            "workspace",
            "workspace_step",
            "workspace_step",
            "checker_count",
        ]
        assert records[-1]["count"] == "0"
    else:
        assert "Workspace" in captured.out
        assert "90.00" in captured.out
        assert "clean (0)" in captured.out


@pytest.mark.parametrize(
    "relative", ["home/flow.json", "home/qor_report.json", "drc_ecc/analysis/qor_metrics.json"]
)
def test_symlinked_evidence_outside_workspace_is_not_read(
    matrix_project, tmp_path, capsys, relative
):
    project, add = matrix_project
    root, _report = add("trial", 80)
    _metric_file(root, "drc", {"drc_count": 0})
    path = root / relative
    outside = tmp_path / "outside.json"
    path.rename(outside)
    path.symlink_to(outside)

    row = _run(project, capsys)["workspaces"][0]

    if relative.endswith("flow.json"):
        assert row["flow_status"] == "invalid"
    elif relative.endswith("qor_report.json"):
        assert row["qor"]["availability"] == "invalid"
    else:
        assert row["steps"][1]["checker"]["availability"] == "invalid"


def test_project_root_defaults_to_current_directory(matrix_project, monkeypatch, capsys):
    project, add = matrix_project
    add("trial", 80)
    monkeypatch.chdir(project)

    assert cli_main.run(["report", "project", "--json"]) == 0

    assert json.loads(capsys.readouterr().out)[0]["project"] == str(project)


@pytest.mark.parametrize("kind", ["missing", "corrupt"])
def test_bad_manifest_is_project_error(matrix_project, capsys, kind):
    project, _add = matrix_project
    path = project / "project.json"
    if kind == "missing":
        path.unlink()
    else:
        path.write_text("{")

    assert cli_main.run(["report", "project", "--project", str(project), "--json"]) == 1

    assert json.loads(capsys.readouterr().out)[0]["error"] == "manifest_invalid"


def test_mutually_exclusive_output_options(matrix_project, capsys):
    project, _add = matrix_project

    assert cli_main.run(["report", "project", "--project", str(project), "--plain", "--json"]) == 2

    assert "--plain" in capsys.readouterr().err


@pytest.mark.parametrize("artifact", ["flow", "qor", "checker"])
def test_oversized_artifacts_are_reported_without_guessing(
    matrix_project, monkeypatch, capsys, artifact
):
    project, add = matrix_project
    root, _report = add("trial", 80)
    _metric_file(root, "drc", {"drc_count": 0})
    if artifact == "checker":
        monkeypatch.setattr(
            "chipcompiler.cli.inspection.project_checkers.CHECKLIST_READ_MAX_BYTES", 16
        )
    else:
        monkeypatch.setattr(
            "chipcompiler.cli.inspection.project_matrix.ENGINEERING_SNAPSHOT_MAX_BYTES",
            16 if artifact == "flow" else 512,
        )

    row = _run(project, capsys)["workspaces"][0]

    if artifact == "checker":
        assert row["steps"][1]["checker"]["availability"] == "oversized"
        assert row["steps"][1]["checker"]["violation_count"] is None
    else:
        assert row["qor"]["score"] is None
        availability = row["flow_status"] if artifact == "flow" else row["qor"]["availability"]
        assert availability == "oversized"


def test_deeply_nested_qor_is_a_partial_row_not_a_traceback(matrix_project, capsys):
    project, add = matrix_project
    root, _report = add("trial", 80)
    (root / "home" / "qor_report.json").write_text(
        '{"nested":' + "[" * 2000 + "0" + "]" * 2000 + "}"
    )

    row = _run(project, capsys)["workspaces"][0]

    assert row["qor"]["availability"] == "invalid"


def test_invalid_metric_selector_cannot_report_clean(matrix_project, capsys):
    project, add = matrix_project
    root, _report = add("trial", 80)
    path, payload = _metric_file(root, "drc", {"drc_count": 0})
    payload["integrity"] = {"status": "incomplete", "invalid_metric_source_ids": ["drc_count"]}
    path.write_text(json.dumps(payload))

    checker = _run(project, capsys)["workspaces"][0]["steps"][1]["checker"]

    assert checker["availability"] == "invalid"
    assert checker["has_violations"] is None


def test_running_workspace_marks_score_as_provisional(matrix_project, capsys):
    project, add = matrix_project
    add("trial", 80, steps=[{"name": "place", "tool": "dreamplace", "state": "Ongoing"}])

    row = _run(project, capsys)["workspaces"][0]

    assert row["flow_status"] == "ongoing"
    assert row["qor"]["provisional"] is True
