import os

from chipcompiler.tools.replay_retention import prune_completed
from chipcompiler.tools.replay_storage import atomic_json


def test_cleanup_retains_current_previous_unfinished_and_external_links(tmp_path):
    root = tmp_path / "replay"
    for i, status in enumerate(["complete", "diagnostic_only", "complete", "complete", "sealed"]):
        name = f"{i:032x}"
        path = root / "attempts" / name / "manifest.json"
        atomic_json(path, {"status": status, "attempt_id": name})
        os.utime(path, ns=(i + 1, i + 1))
    atomic_json(root / "manifest.json", {"status": "complete", "attempt_id": f"{3:032x}"})
    external = tmp_path / "external"
    external.mkdir()
    (root / "attempts" / f"{5:032x}").symlink_to(external, target_is_directory=True)
    prune_completed(root)
    assert sorted(p.name for p in (root / "attempts").iterdir()) == [
        f"{i:032x}" for i in [2, 3, 4, 5]
    ]
    assert external.is_dir()
    assert list((root / ".retired").iterdir()) == []
