#!/usr/bin/env python

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from chipcompiler.utility import json_read, json_write

CHECKLIST_SCHEMA_VERSION = 3
CHECKLIST_REVISION = "signoff-v1"


def workspace_checklist_path(workspace_dir: Path | str | None) -> Path:
    if workspace_dir is None:
        raise ValueError("Workspace directory is not set")
    return Path(workspace_dir) / "home" / "checklist.json"


class CheckState(StrEnum):
    """Checklist item states, spelled as the checklist stores them."""

    UNAVAILABLE = "unavailable"
    PASS = "pass"
    FAILED = "failed"
    WARNING = "warning"


class CheckPolicy(StrEnum):
    """Whether a failed or unavailable item blocks signoff."""

    BLOCK = "block"
    WARN = "warn"


class CheckOwner(StrEnum):
    """The producer of a checklist item."""

    QOR = "qor"
    CHECKLIST = "checklist"


@dataclass(frozen=True)
class ChecklistItem:
    """One checklist requirement; its record is the stored JSON object."""

    id: str
    step: str
    category: str
    owner: CheckOwner
    policy: CheckPolicy
    state: CheckState
    title: str
    summary: str = ""
    source: dict = field(default_factory=dict)
    evidence: list[dict] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return self.policy is CheckPolicy.BLOCK and self.state in {
            CheckState.FAILED,
            CheckState.UNAVAILABLE,
        }

    @classmethod
    def from_record(cls, record: Mapping) -> "ChecklistItem":
        """Parse a stored item; a missing field or unknown value raises ValueError."""
        try:
            item = cls(
                id=record["id"],
                step=record["step"],
                category=record["category"],
                owner=CheckOwner(record["owner"]),
                policy=CheckPolicy(record["policy"]),
                state=CheckState(record["state"]),
                title=record["title"],
                summary=record.get("summary", ""),
                source=record.get("source", {}),
                evidence=record.get("evidence", []),
            )
        except KeyError as exc:
            raise ValueError(f"checklist item is missing {exc.args[0]!r}") from None
        texts = (item.id, item.step, item.category, item.title, item.summary)
        if not all(isinstance(text, str) for text in texts) or not item.id:
            raise ValueError(f"invalid checklist item: {record.get('id')!r}")
        if not isinstance(item.source, dict) or not isinstance(item.evidence, list):
            raise ValueError(f"invalid checklist item evidence: {item.id!r}")
        return item

    def to_record(self) -> dict:
        return {
            "id": self.id,
            "step": self.step,
            "category": self.category,
            "owner": str(self.owner),
            "policy": str(self.policy),
            "state": str(self.state),
            "blocked": self.blocked,
            "title": self.title,
            "summary": self.summary,
            "source": self.source,
            "evidence": self.evidence,
        }


def checklist_records(items: Iterable["ChecklistItem | Mapping"]) -> list[dict]:
    """Stored records of *items*, each validated and its ``blocked`` derived."""
    return [
        (item if isinstance(item, ChecklistItem) else ChecklistItem.from_record(item)).to_record()
        for item in items
    ]


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

    @classmethod
    def from_items(cls, path: Path | str, items) -> dict:
        """Build normalized checklist data without reading or writing a file."""
        checklist = cls.__new__(cls)
        checklist.path = Path(path)
        checklist.data = checklist._default_data()
        checklist.data["checklist"] = checklist_records(items)
        cls._refresh_summary(checklist.data)
        return checklist.data

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
            "requirements_status": "none",
            "checklist": [],
        }

    def _load_current_data(self) -> dict:
        data = json_read(self.path) if self.path.exists() else {}
        if self.path.exists() and (
            not isinstance(data, dict)
            or data.get("schema_version") != CHECKLIST_SCHEMA_VERSION
            or data.get("kind") != "signoff_checklist"
            or not isinstance(data.get("checklist"), list)
        ):
            raise ValueError(f"incompatible signoff checklist: {self.path}; create a new workspace")
        if not self.path.exists():
            data = self._default_data()
            json_write(self.path, data)
            return data
        self._refresh_summary(data)
        return data

    @staticmethod
    def _identifier(value: str) -> str:
        token = re.sub(r"[^a-z0-9]+", ".", value.lower()).strip(".")
        return token or "item"

    @classmethod
    def _refresh_summary(cls, data: dict) -> None:
        items = checklist_records(data.get("checklist", []))
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
        data["requirements_status"] = "none" if not items else "present"
        data["status"] = (
            "blocked"
            if summary["blocked"]
            else "attention"
            if (summary["attention"] or summary["unavailable"])
            else "ready"
        )

    def replace(self, items: Iterable[ChecklistItem | Mapping]) -> list[dict]:
        self.data = self._default_data()
        self.data["checklist"] = checklist_records(items)
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
            self._tool_item(item_id, step, type, item, state, info, evidence).to_record()
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
            existing for existing in self.data.get("checklist", []) if existing.get("id") != item_id
        ]
        items.append(self._tool_item(item_id, step, type, item, state, info, evidence))
        self.replace(items)

    @staticmethod
    def _tool_item(item_id, step, type, item, state, info, evidence) -> ChecklistItem:
        """A warn-policy item a tool reports through :meth:`add` or :meth:`update`."""
        return ChecklistItem(
            id=item_id,
            step=step,
            category=type.lower().replace(" ", "_"),
            owner=CheckOwner.CHECKLIST,
            policy=CheckPolicy.WARN,
            state=CheckState(state),
            title=item,
            summary=info,
            source=evidence or {},
            evidence=[evidence] if evidence else [],
        )

    def state_statistics(self) -> dict:
        self._refresh_summary(self.data)
        return {"total": len(self.data["checklist"]), **self.data["summary"]}

    def save(self) -> bool:
        self.data["schema_version"] = CHECKLIST_SCHEMA_VERSION
        self.data["kind"] = "signoff_checklist"
        self.data["checker_revision"] = CHECKLIST_REVISION
        self.data["generated_at"] = self._timestamp()
        self._refresh_summary(self.data)
        return bool(json_write(self.path, self.data))
