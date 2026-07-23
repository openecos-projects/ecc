#!/usr/bin/env python
from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from chipcompiler.utility import json_read, json_write

CHECKLIST_SCHEMA_VERSION = 3
CHECKLIST_REVISION = "signoff-v1"


class CheckState(Enum):
    """States retained for tool code that constructs checklist records."""

    Unstart = "Unstart"
    Passed = "Passed"
    Failed = "Failed"
    Warning = "Warning"


_STATE_MAP = {
    CheckState.Unstart.value: "unavailable",
    CheckState.Passed.value: "pass",
    CheckState.Failed.value: "failed",
    CheckState.Warning.value: "warning",
    "pass": "pass",
    "failed": "failed",
    "warning": "warning",
    "unavailable": "unavailable",
}


class Checklist:
    """Persist the workspace signoff checklist contract.

    A checklist is replaced as a complete current-output snapshot.  The small
    add/update API remains for tool entry points, but always writes the V3
    contract instead of preserving the removed V2 table model.
    """

    header = ["step", "category", "title", "owner", "policy", "state", "summary"]

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.data = self._load_current_data()

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")

    def _default_data(self) -> dict:
        return {
            "schema_version": CHECKLIST_SCHEMA_VERSION,
            "kind": "signoff_checklist",
            "checker_revision": CHECKLIST_REVISION,
            "generated_at": self._timestamp(),
            "status": "ready",
            "summary": {
                "passed": 0,
                "blocked": 0,
                "attention": 0,
                "unavailable": 0,
            },
            "checklist": [],
        }

    def _load_current_data(self) -> dict:
        data = json_read(self.path) if self.path.exists() else {}
        if (
            not isinstance(data, dict)
            or data.get("schema_version") != CHECKLIST_SCHEMA_VERSION
            or data.get("kind") != "signoff_checklist"
            or not isinstance(data.get("checklist"), list)
        ):
            data = self._default_data()
            json_write(self.path, data)
            return data
        self._refresh_summary(data)
        return data

    @staticmethod
    def state_value(state: str | CheckState) -> str:
        raw = state.value if isinstance(state, CheckState) else str(state)
        return _STATE_MAP.get(raw, "unavailable")

    @staticmethod
    def _identifier(value: str) -> str:
        token = re.sub(r"[^a-z0-9]+", ".", value.lower()).strip(".")
        return token or "item"

    @classmethod
    def _normalize_item(cls, item: dict) -> dict:
        state = cls.state_value(item.get("state", "unavailable"))
        policy = item.get("policy") if item.get("policy") in {"block", "warn"} else "warn"
        normalized = {
            "id": str(
                item.get("id")
                or cls._identifier(
                    f"{item.get('step', 'workspace')}.{item.get('title', item.get('item', 'item'))}"
                )
            ),
            "step": str(item.get("step") or "workspace"),
            "category": str(item.get("category") or item.get("type") or "report"),
            "owner": (
                item.get("owner") if item.get("owner") in {"qor", "checklist"} else "checklist"
            ),
            "policy": policy,
            "state": state,
            "blocked": policy == "block" and state in {"failed", "unavailable"},
            "title": str(item.get("title") or item.get("item") or "Checklist item"),
            "summary": str(item.get("summary") or item.get("info") or ""),
            "source": item.get("source") if isinstance(item.get("source"), dict) else {},
            "evidence": item.get("evidence") if isinstance(item.get("evidence"), list) else [],
        }
        return normalized

    @classmethod
    def _refresh_summary(cls, data: dict) -> None:
        items = [
            cls._normalize_item(item)
            for item in data.get("checklist", [])
            if isinstance(item, dict)
        ]
        data["checklist"] = items
        summary = {"passed": 0, "blocked": 0, "attention": 0, "unavailable": 0}
        for item in items:
            if item["state"] == "pass":
                summary["passed"] += 1
            elif item["blocked"]:
                summary["blocked"] += 1
            elif item["state"] == "unavailable":
                summary["unavailable"] += 1
            else:
                summary["attention"] += 1
        data["summary"] = summary
        data["status"] = (
            "blocked"
            if summary["blocked"]
            else "attention"
            if (summary["attention"] or summary["unavailable"])
            else "ready"
        )

    def replace(self, items: list[dict]) -> list[dict]:
        self.data = self._default_data()
        self.data["checklist"] = [
            self._normalize_item(item) for item in items if isinstance(item, dict)
        ]
        self.save()
        return self.data["checklist"]

    def replace_step(self, step: str, items: list[dict] | None = None) -> None:
        retained = [
            item
            for item in self.data.get("checklist", [])
            if isinstance(item, dict) and item.get("step") != step
        ]
        for item in items or []:
            item = dict(item)
            item["step"] = step
            retained.append(item)
        self.replace(retained)

    def add(
        self,
        step: str,
        type: str,
        item: str,
        state: str | CheckState,
        info: str = "",
        evidence: dict | None = None,
    ) -> None:
        item_id = self._identifier(f"{step}.{item}")
        if any(
            existing.get("id") == item_id
            for existing in self.data.get("checklist", [])
            if isinstance(existing, dict)
        ):
            return
        self.data["checklist"].append(
            {
                "id": item_id,
                "step": step,
                "category": type.lower().replace(" ", "_"),
                "owner": "checklist",
                "policy": "warn",
                "state": self.state_value(state),
                "title": item,
                "summary": info,
                "source": evidence or {},
                "evidence": [evidence] if evidence else [],
            }
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
        item_id = self._identifier(f"{step}.{item}")
        items = [
            existing
            for existing in self.data.get("checklist", [])
            if isinstance(existing, dict) and existing.get("id") != item_id
        ]
        items.append(
            {
                "id": item_id,
                "step": step,
                "category": type.lower().replace(" ", "_"),
                "owner": "checklist",
                "policy": "warn",
                "state": self.state_value(state),
                "title": item,
                "summary": info,
                "source": evidence or {},
                "evidence": [evidence] if evidence else [],
            }
        )
        self.replace(items)

    def state_statistics(self) -> dict:
        self._refresh_summary(self.data)
        return {"total": len(self.data["checklist"]), **self.data["summary"]}

    def save(self) -> None:
        self.data["schema_version"] = CHECKLIST_SCHEMA_VERSION
        self.data["kind"] = "signoff_checklist"
        self.data["checker_revision"] = CHECKLIST_REVISION
        self.data["generated_at"] = self._timestamp()
        self._refresh_summary(self.data)
        json_write(self.path, self.data)
