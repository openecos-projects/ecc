import json
from pathlib import Path

from chipcompiler.data.checklist import Checklist


def test_checklist_accepts_path_and_persists_string_path(tmp_path):
    path = tmp_path / "checklist.json"

    checklist = Checklist(path)

    assert isinstance(checklist.path, Path)
    assert checklist.path == path
    assert json.loads(path.read_text()) == {
        "path": str(path),
        "checklist": [],
    }
