"""Signoff CSV export and CI gate projection helpers.

``nix/scripts/export-signoff-csv*`` are thin entrypoints. Run-vs-run
dashboard diffs are intentionally not part of this package.
"""

from csv_gates.bundle import (
    CsvExportBundle,
    CsvTable,
    build_csv_bundle,
    render_csv,
    write_csv_bundle,
)
from csv_gates.compare import (
    METRIC_OPS,
    compare_values,
    evaluate_checklist_gate,
    evaluate_metric_gate,
)
from csv_gates.manifest import (
    MANIFEST_SCHEMA_VERSION,
    RunManifest,
    build_run_manifest,
    write_run_manifest,
)
from csv_gates.projection import projection_lines
from csv_gates.spec import (
    ChecklistItemSpec,
    CsvExportSpec,
    CsvSpecError,
    MetricSpec,
    load_csv_spec,
)

__all__ = [
    "METRIC_OPS",
    "MANIFEST_SCHEMA_VERSION",
    "ChecklistItemSpec",
    "CsvExportBundle",
    "CsvExportSpec",
    "CsvSpecError",
    "CsvTable",
    "MetricSpec",
    "RunManifest",
    "build_csv_bundle",
    "build_run_manifest",
    "compare_values",
    "evaluate_checklist_gate",
    "evaluate_metric_gate",
    "load_csv_spec",
    "projection_lines",
    "render_csv",
    "write_csv_bundle",
    "write_run_manifest",
]
