import gzip
import json
import stat

from chipcompiler.utility.json import json_read, json_write


class Unserializable:
    pass


def test_json_write_keeps_existing_file_when_normal_json_dump_fails(tmp_path):
    path = tmp_path / "data.json"
    path.write_text(json.dumps({"existing": True}))

    assert json_write(str(path), {"bad": Unserializable()}) is False

    assert json.loads(path.read_text()) == {"existing": True}
    assert list(tmp_path.iterdir()) == [path]


def test_json_write_preserves_existing_file_mode(tmp_path):
    path = tmp_path / "data.json"
    path.write_text(json.dumps({"existing": True}))
    path.chmod(0o664)

    assert json_write(str(path), {"updated": True})

    assert stat.S_IMODE(path.stat().st_mode) == 0o664
    assert json.loads(path.read_text()) == {"updated": True}


def test_json_write_preserves_symlink_and_updates_target(tmp_path):
    target = tmp_path / "target.json"
    link = tmp_path / "link.json"
    target.write_text(json.dumps({"existing": True}))
    link.symlink_to(target)

    assert json_write(str(link), {"updated": True})

    assert link.is_symlink()
    assert link.resolve() == target
    assert json.loads(target.read_text()) == {"updated": True}


def test_json_read_accepts_path_input(tmp_path):
    path = tmp_path / "data.json"
    path.write_text(json.dumps({"value": 1}))

    assert json_read(path) == {"value": 1}


def test_json_write_accepts_path_input(tmp_path):
    path = tmp_path / "data.json"

    assert json_write(path, {"value": 1})

    assert json.loads(path.read_text()) == {"value": 1}


def test_json_read_accepts_gz_path_input(tmp_path):
    path = tmp_path / "data.json.gz"
    with gzip.open(path, "wt") as f:
        json.dump({"value": 1}, f)

    assert json_read(path) == {"value": 1}


def test_json_write_accepts_gz_path_input(tmp_path):
    path = tmp_path / "data.json.gz"

    assert json_write(path, {"value": 1})

    with gzip.open(path, "rt") as f:
        assert json.load(f) == {"value": 1}
