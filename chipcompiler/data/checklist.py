#!/usr/bin/env python
from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from chipcompiler.utility import json_read, json_write

CHECKLIST_SCHEMA_VERSION = 2
CHECKLIST_REVISION = "qor-v3-current-output"


class CheckState(Enum):
    """Checklist state."""

    Unstart = "Unstart"
    Passed = "Passed"
    Failed = "Failed"
    Warning = "Warning"


class Checklist:
    """Persist the current checklist contract for one workspace or one step."""

    header = ["step", "type", "item", "state", "info"]

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.data = self._load_current_data()

    def _default_data(self) -> dict:
        return {
            "schema_version": CHECKLIST_SCHEMA_VERSION,
            "checker_revision": CHECKLIST_REVISION,
            "generated_at": self._timestamp(),
            "path": str(self.path),
            "checklist": [],
        }

    def _load_current_data(self) -> dict:
        data = json_read(self.path) if self.path.exists() else {}
        if not isinstance(data, dict) or data.get("schema_version") != CHECKLIST_SCHEMA_VERSION:
            data = self._default_data()
            json_write(self.path, data)
            return data

        items = data.get("checklist")
        if not isinstance(items, list):
            data = self._default_data()
            json_write(self.path, data)
            return data

        data["path"] = str(self.path)
        data["checker_revision"] = CHECKLIST_REVISION
        for item in items:
            if isinstance(item, dict):
                item.setdefault("info", "")
        return data

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")

    def save(self) -> None:
        self.data["schema_version"] = CHECKLIST_SCHEMA_VERSION
        self.data["checker_revision"] = CHECKLIST_REVISION
        self.data["generated_at"] = self._timestamp()
        self.data["path"] = str(self.path)
        json_write(self.path, self.data)

    @staticmethod
    def state_value(state: str | CheckState) -> str:
        return state.value if isinstance(state, CheckState) else state

    def check_info(self, state: str | CheckState, item: str, info: str = "") -> str:
        state_value = self.state_value(state)
        if info or state_value not in (CheckState.Failed.value, CheckState.Warning.value):
            return info
        return f"{state_value}: {item} check needs attention"

    def state_statistics(self) -> dict:
        statistics = {state.value: 0 for state in CheckState}
        checklist = self.data.get("checklist", [])
        for check_item in checklist:
            if not isinstance(check_item, dict):
                continue
            state = check_item.get("state", "")
            if state in statistics:
                statistics[state] += 1
        return {"total": len(checklist), **statistics}

    def replace_step(self, step: str, items: list[dict] | None = None) -> None:
        current_items = [
            item
            for item in self.data.get("checklist", [])
            if isinstance(item, dict) and item.get("step") != step
        ]
        for item in items or []:
            item_data = dict(item)
            item_data.pop("step", None)
            current_items.append(self._normalized_item(step=step, **item_data))
        self.data["checklist"] = current_items
        self.save()

    def _normalized_item(
        self,
        step: str,
        type: str,
        item: str,
        state: str | CheckState,
        info: str = "",
        evidence: dict | None = None,
    ) -> dict:
        result = {
            "step": step,
            "type": type,
            "item": item,
            "state": self.state_value(state),
            "info": self.check_info(state=state, item=item, info=info),
        }
        if evidence:
            result["evidence"] = evidence
        return result

    def add(
        self,
        step: str,
        type: str,
        item: str,
        state: str | CheckState,
        info: str = "",
        evidence: dict | None = None,
    ) -> None:
        for check_item in self.data.get("checklist", []):
            if (
                isinstance(check_item, dict)
                and check_item.get("step") == step
                and check_item.get("type") == type
                and check_item.get("item") == item
            ):
                return
        self.data["checklist"].append(
            self._normalized_item(step, type, item, state, info, evidence)
        )
        self.save()

    def update(
        self,
        step: str,
        type: str,
        item: str,
        state: str | CheckState,
        info: str = "",
        evidence: dict | None = None,
    ) -> None:
        for index, check_item in enumerate(self.data.get("checklist", [])):
            if (
                isinstance(check_item, dict)
                and check_item.get("step") == step
                and check_item.get("type") == type
                and check_item.get("item") == item
            ):
                self.data["checklist"][index] = self._normalized_item(
                    step, type, item, state, info, evidence
                )
                self.save()
                return
        self.add(step=step, type=type, item=item, state=state, info=info, evidence=evidence)
