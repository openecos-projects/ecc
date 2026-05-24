import json

from chipcompiler.data.home import HomeData


def _read_json(path):
    return json.loads(path.read_text())


def test_init_writes_complete_schema_for_missing_file(tmp_path):
    path = tmp_path / "home.json"

    home = HomeData()
    home.init(str(path))

    data = _read_json(path)
    assert data["layout"] == ""
    assert data["GDS merge"] == ""
    assert data["metrics"] == {}
    assert data["monitor"] == {
        "step": [],
        "memory": [],
        "runtime": [],
        "instance": [],
        "frequency": [],
    }


def test_init_repairs_partial_home_json_preserving_existing_values(tmp_path):
    path = tmp_path / "home.json"
    path.write_text(
        json.dumps(
            {
                "flow": "/ws/home/flow.json",
                "checklist": "/ws/home/checklist.json",
                "parameters": "/ws/home/parameters.json",
            }
        )
    )

    home = HomeData()
    home.init(str(path))

    data = _read_json(path)
    assert data["flow"] == "/ws/home/flow.json"
    assert data["checklist"] == "/ws/home/checklist.json"
    assert data["parameters"] == "/ws/home/parameters.json"
    assert data["layout"] == ""
    assert data["GDS merge"] == ""
    assert data["metrics"] == {}
    assert data["monitor"] == {
        "step": [],
        "memory": [],
        "runtime": [],
        "instance": [],
        "frequency": [],
    }


def test_update_monitor_repairs_partial_home_json(tmp_path):
    path = tmp_path / "home.json"
    path.write_text(json.dumps({"metrics": {}}))

    home = HomeData()
    home.init(str(path))
    home.update_monitor(
        step="Floorplan",
        sub_step="place",
        memory="12M",
        runtime="3s",
        instance=42,
        frequency=100.0,
    )

    data = _read_json(path)
    assert data["monitor"]["step"] == ["Floorplan - place"]
    assert data["monitor"]["memory"] == ["12M"]
    assert data["monitor"]["runtime"] == ["3s"]
    assert data["monitor"]["instance"] == [42]
    assert data["monitor"]["frequency"] == [100.0]


def test_instances_do_not_share_nested_monitor_lists(tmp_path):
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"

    first = HomeData()
    first.init(str(first_path))
    second = HomeData()
    second.init(str(second_path))

    first.update_monitor("Synthesis", "yosys", "10M", "1s")

    assert _read_json(first_path)["monitor"]["step"] == ["Synthesis - yosys"]
    assert _read_json(second_path)["monitor"]["step"] == []


def test_set_metrics_repairs_missing_metrics(tmp_path):
    path = tmp_path / "home.json"
    path.write_text(json.dumps({"monitor": {"step": []}}))

    home = HomeData()
    home.init(str(path))
    home.set_metrics_pin_dist("/tmp/pin.png")

    data = _read_json(path)
    assert data["metrics"]["pin dist."] == "/tmp/pin.png"
    assert data["monitor"]["step"] == []
