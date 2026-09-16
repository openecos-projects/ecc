import csv
import io

import pytest
import yaml
from support.csv_export import (
    TABLE_FILES,
    build_csv_bundle,
    render_csv,
    write_csv_bundle,
)
from support.csv_spec import (
    CsvSpecError,
    default_profile_path,
    load_csv_spec,
    parse_csv_spec,
)
from test_qor_report import _make_workspace


class TestCsvExport:
    def test_bundle_tables_match_contract(self, tmp_path):
        bundle = build_csv_bundle(_make_workspace(tmp_path))
        assert bundle.design == "gcd"
        assert bundle.checklist_available is True
        assert {table.filename for table in bundle.tables} == set(TABLE_FILES)

        by_name = {table.filename: table for table in bundle.tables}
        assert by_name["qor_summary.csv"].rows[0]["design"] == "gcd"
        assert by_name["qor_summary.csv"].rows[0]["overall_score"] == bundle.overall_score
        assert any(row["metric_name"] == "sta_setup_wns" for row in by_name["qor_metrics.csv"].rows)
        assert "quality.drc.clean" in {row["id"] for row in by_name["checklist.csv"].rows}
        flow_names = [row["name"] for row in by_name["flow_steps.csv"].rows]
        assert "sta" in flow_names
        assert "Harden" in flow_names

    def test_write_creates_all_files(self, tmp_path):
        bundle = build_csv_bundle(_make_workspace(tmp_path / "ws"))
        destination = tmp_path / "out"
        written = write_csv_bundle(bundle, str(destination))

        assert [entry["file"] for entry in written] == list(TABLE_FILES)
        for name in TABLE_FILES:
            path = destination / name
            assert path.is_file()
            with path.open(newline="") as handle:
                rows = list(csv.DictReader(handle))
            table = next(t for t in bundle.tables if t.filename == name)
            assert len(rows) == len(table.rows)

    def test_render_csv_bool_and_none(self):
        from support.csv_export import CsvTable

        text = render_csv(
            CsvTable(
                filename="t.csv",
                fieldnames=("a", "b", "c"),
                rows=({"a": True, "b": False, "c": None},),
            )
        )
        reader = csv.DictReader(io.StringIO(text))
        assert list(reader) == [{"a": "true", "b": "false", "c": ""}]

    def test_empty_checklist_still_writes_header(self, tmp_path):
        bundle = build_csv_bundle(_make_workspace(tmp_path, with_checklist=False))
        assert bundle.checklist_available is False
        checklist = next(t for t in bundle.tables if t.filename == "checklist.csv")
        assert checklist.rows == ()
        assert render_csv(checklist).startswith("id,step,category,")


class TestCsvSpec:
    def test_parse_rejects_unknown_table(self):
        with pytest.raises(CsvSpecError, match="unknown table"):
            parse_csv_spec({"version": 1, "tables": ["nope"]})

    def test_spec_injects_reference_and_missing_rows(self, tmp_path):
        spec_path = tmp_path / "profile.yml"
        spec_path.write_text(
            yaml.dump(
                {
                    "version": 1,
                    "tables": ["qor_metrics", "checklist", "flow_steps"],
                    "metrics": [
                        {"id": "sta_setup_wns", "reference": 0.0},
                        {"id": "missing_metric", "reference": 1},
                    ],
                    "checklist": [
                        {"id": "quality.drc.clean"},
                        {"id": "missing.item"},
                    ],
                    "flow_steps": ["sta", "GhostStep"],
                }
            ),
            encoding="utf-8",
        )
        spec = load_csv_spec(str(spec_path))
        bundle = build_csv_bundle(_make_workspace(tmp_path / "ws"), spec=spec)
        assert [t.filename for t in bundle.tables] == [
            "qor_metrics.csv",
            "checklist.csv",
            "flow_steps.csv",
        ]
        assert bundle.spec_path == str(spec_path.resolve())

        metrics = {row["metric_name"]: row for row in bundle.tables[0].rows}
        assert metrics["sta_setup_wns"]["present"] is True
        assert metrics["sta_setup_wns"]["reference"] == 0.0
        assert metrics["missing_metric"]["present"] is False
        assert metrics["missing_metric"]["reference"] == 1

        checklist = {row["id"]: row for row in bundle.tables[1].rows}
        assert checklist["quality.drc.clean"]["present"] is True
        assert checklist["missing.item"]["present"] is False

        flow = {row["name"]: row for row in bundle.tables[2].rows}
        assert flow["sta"]["present"] is True
        assert flow["GhostStep"]["present"] is False

        out = tmp_path / "csv"
        written = write_csv_bundle(bundle, str(out))
        assert (out / "export_spec.yml").is_file()
        assert any(entry["file"] == "export_spec.yml" for entry in written)

    def test_default_signoff_profile_loads(self):
        spec = load_csv_spec(str(default_profile_path()))
        assert spec.version == 1
        assert spec.metrics is not None
        assert any(item.id == "drc_count" for item in spec.metrics)


class TestCsvProjection:
    def test_projection_lists_spec_ids(self, tmp_path):
        from support.csv_projection import projection_lines, write_projection

        spec = load_csv_spec(str(default_profile_path()))
        bundle = build_csv_bundle(_make_workspace(tmp_path / "ws"), spec=spec)
        csv_dir = tmp_path / "csv"
        write_csv_bundle(bundle, str(csv_dir))
        lines = projection_lines(csv_dir, bundle.design)
        text = "\n".join(lines)
        assert "design: gcd" in text
        assert "metric drc_count " in text
        assert "checklist quality.drc.clean " in text
        path = write_projection(csv_dir, bundle.design, tmp_path / "metrics.check.txt")
        assert path.read_text(encoding="utf-8") == text + "\n"
