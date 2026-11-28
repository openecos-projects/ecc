from math import isfinite
from pathlib import Path

from chipcompiler.analysis.qor.metrics_contract import (
    QOR_METRICS_SCHEMA_VERSION,
    index_metric_records,
)
from chipcompiler.utility import json_read


class QorMetrics:
    """Read the current V3 scalar metric contract for checklist checks."""

    def __init__(self, path: str | Path | None):
        self.path = Path(path) if path else None
        self.error: str | None = None
        self.records: dict[str, dict] = {}
        self.conflicts: set[str] = set()
        self._load()

    def _load(self) -> None:
        if self.path is None or not self.path.is_file():
            self.error = "qor_metrics.json is missing"
            return

        data = json_read(self.path)
        if not isinstance(data, dict) or data.get("schema_version") != QOR_METRICS_SCHEMA_VERSION:
            self.error = "qor_metrics.json does not use schema_version 3"
            return

        metrics = data.get("metrics")
        if not isinstance(metrics, list):
            self.error = "qor_metrics.json is missing its metrics array"
            return

        indexed = index_metric_records(metrics)
        if indexed.error is not None:
            self.error = indexed.error
            return
        self.records = indexed.records
        self.conflicts = set(indexed.conflicts)

    def number(self, metric_id: str) -> tuple[float | None, str | None]:
        if self.error is not None:
            return None, self.error

        if metric_id in self.conflicts:
            return None, f"qor_metrics.json contains conflicting duplicate metric id {metric_id}"

        record = self.records.get(metric_id)
        if record is None:
            return None, f"{metric_id} is missing from qor_metrics.json"

        value = record.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None, f"{metric_id} has no numeric value in qor_metrics.json"

        number = float(value)
        if not isfinite(number):
            return None, f"{metric_id} has a non-finite value in qor_metrics.json"
        return number, None
