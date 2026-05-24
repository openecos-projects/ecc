import json

from chipcompiler.utility.json import json_write


class Unserializable:
    pass


def test_json_write_keeps_existing_file_when_normal_json_dump_fails(tmp_path):
    path = tmp_path / "data.json"
    path.write_text(json.dumps({"existing": True}))

    assert json_write(str(path), {"bad": Unserializable()}) is False

    assert json.loads(path.read_text()) == {"existing": True}
    assert list(tmp_path.iterdir()) == [path]
