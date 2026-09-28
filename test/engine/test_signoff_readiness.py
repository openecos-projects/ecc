"""Fixture tests for milestone readiness PASS/WARN/MISS/ERROR (no PDK)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from chipcompiler.engine.signoff_assessment import build_signoff_assessment
from chipcompiler.engine.signoff_readiness import classify_signoff_readiness


def _checklist(*items: dict, status: str | None = None) -> dict:
    payload = {
        "schema_version": 3,
        "kind": "signoff_checklist",
        "status": status or "ready",
        "checklist": list(items),
    }
    return payload


def _item(
    *,
    item_id: str,
    state: str,
    policy: str = "block",
    blocked: bool | None = None,
    title: str = "item",
) -> dict:
    if blocked is None:
        blocked = policy == "block" and state in {"failed", "unavailable"}
    return {
        "id": item_id,
        "step": "drc",
        "category": "quality",
        "owner": "qor",
        "policy": policy,
        "state": state,
        "blocked": blocked,
        "title": title,
        "summary": title,
        "source": {},
        "evidence": [],
    }


@pytest.mark.parametrize(
    "checklist,expected",
    [
        (_checklist(status="ready"), "PASS"),
        (
            _checklist(
                _item(item_id="quality.drc.clean", state="pass"),
                status="ready",
            ),
            "PASS",
        ),
        (
            _checklist(
                _item(item_id="quality.util", state="failed", policy="warn"),
                status="attention",
            ),
            "WARN",
        ),
        (
            _checklist(
                _item(item_id="artifact.sta.report", state="unavailable", policy="block"),
                status="blocked",
            ),
            "MISS",
        ),
        (
            _checklist(
                _item(
                    item_id="artifact.spef",
                    state="failed",
                    policy="block",
                    title="RCX SPEF",
                )
                | {"owner": "checklist", "category": "report"},
                status="blocked",
            ),
            "MISS",
        ),
        (
            _checklist(
                _item(item_id="quality.drc.clean", state="failed", policy="block"),
                status="blocked",
            ),
            "ERROR",
        ),
        (
            _checklist(
                _item(item_id="quality.drc.clean", state="failed", policy="block"),
                _item(item_id="artifact.gds", state="unavailable", policy="block"),
                status="blocked",
            ),
            "ERROR",
        ),
    ],
)
def test_classify_signoff_readiness(checklist, expected):
    assert classify_signoff_readiness(checklist) == expected


def test_unavailable_checklist_is_miss():
    assert (
        classify_signoff_readiness(None, checklist_unavailable=True) == "MISS"
    )


def test_assessment_exposes_readiness_field(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "checklist.json").write_text(
        json.dumps(
            _checklist(
                _item(item_id="quality.drc.clean", state="failed", policy="block"),
                status="blocked",
            )
        ),
        encoding="utf-8",
    )
    workspace = SimpleNamespace(
        directory=Path(tmp_path),
        flow=SimpleNamespace(steps=lambda: [{"name": "drc", "state": "Success"}]),
    )

    result = build_signoff_assessment(workspace)

    assert result["status"] == "blocked"
    assert result["readiness"] == "ERROR"


def test_assessment_pass_readiness(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "checklist.json").write_text(
        json.dumps(
            _checklist(
                _item(item_id="quality.drc.clean", state="pass"),
                status="ready",
            )
        ),
        encoding="utf-8",
    )
    workspace = SimpleNamespace(
        directory=Path(tmp_path),
        flow=SimpleNamespace(steps=lambda: [{"name": "drc", "state": "Success"}]),
    )

    result = build_signoff_assessment(workspace)

    assert result["status"] == "ready"
    assert result["readiness"] == "PASS"


def test_incomplete_flow_readiness_is_miss(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "checklist.json").write_text(
        json.dumps(_checklist(status="ready")),
        encoding="utf-8",
    )
    workspace = SimpleNamespace(
        directory=Path(tmp_path),
        flow=SimpleNamespace(steps=lambda: [{"name": "Synthesis", "state": "Unstart"}]),
    )

    result = build_signoff_assessment(workspace)

    assert result["status"] == "blocked"
    assert result["readiness"] == "MISS"
