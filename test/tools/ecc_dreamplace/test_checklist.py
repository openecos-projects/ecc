import json
from pathlib import Path
from types import SimpleNamespace

from chipcompiler.data import StepEnum
from chipcompiler.tools.ecc_dreamplace.checklist import DreamplacePlacementChecklist


def test_placement_checklist_writes_current_empty_v3_snapshot(tmp_path):
    checklist_path = tmp_path / "place_dreamplace" / "checklist.json"
    step = SimpleNamespace(
        name=StepEnum.PLACEMENT.value,
        checklist={"path": str(checklist_path)},
        analysis={},
        feature={},
        output={},
    )

    assert DreamplacePlacementChecklist(SimpleNamespace(), step).check() is True

    data = json.loads(checklist_path.read_text(encoding="utf-8"))
    assert data["schema_version"] == 3
    assert data["kind"] == "signoff_checklist"
    assert data["checklist"] == []
