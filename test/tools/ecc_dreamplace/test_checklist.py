import json
from types import SimpleNamespace
from typing import Any

from chipcompiler.data import ChecklistState, EccAnalysis, EccFeature, EccOutput, StepEnum
from chipcompiler.tools.ecc_dreamplace.checklist import DreamplacePlacementChecklist


def _ns(**kwargs: object) -> Any:
    return SimpleNamespace(**kwargs)


def test_placement_checklist_writes_current_empty_v3_snapshot(tmp_path):
    checklist_path = tmp_path / "place_dreamplace" / "checklist.json"
    step = _ns(
        name=StepEnum.PLACEMENT.value,
        checklist=ChecklistState(path=checklist_path),
        analysis=EccAnalysis(),
        feature=EccFeature(),
        output=EccOutput(),
    )

    assert DreamplacePlacementChecklist(_ns(directory=tmp_path), step).check() is True

    data = json.loads(checklist_path.read_text(encoding="utf-8"))
    assert data["schema_version"] == 3
    assert data["kind"] == "signoff_checklist"
    assert data["checklist"] == []
