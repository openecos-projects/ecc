from __future__ import annotations

from math import isfinite
from pathlib import Path

from chipcompiler.utility import json_read


class QorMetrics:
    """Read the current V3 scalar metric contract for checklist checks."""

    def __init__(self, path: str | Path | None):
        self.path = Path(path) if path else None
        self.error: str | None = None
        self.records: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if self.path is None or not self.path.is_file():
            self.error = "qor_metrics.json is missing"
            return

        data = json_read(self.path)
        if not isinstance(data, dict) or data.get("schema_version") != 3:
            self.error = "qor_metrics.json does not use schema_version 3"
            return

        metrics = data.get("metrics")
        if not isinstance(metrics, list):
            self.error = "qor_metrics.json is missing its metrics array"
            return

        for record in metrics:
            metric_id = record.get("id") if isinstance(record, dict) else None
            if not isinstance(metric_id, str) or not metric_id:
                self.error = "qor_metrics.json contains a metric without a valid id"
                return
            if metric_id in self.records:
                self.error = f"qor_metrics.json contains duplicate metric id {metric_id}"
                return
            self.records[metric_id] = record

    def number(self, metric_id: str) -> tuple[float | None, str | None]:
        if self.error is not None:
            return None, self.error

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
