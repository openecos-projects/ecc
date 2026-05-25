import json
from multiprocessing import Process

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


def test_update_monitor_repairs_short_monitor_columns_preserving_history(tmp_path):
    path = tmp_path / "home.json"
    path.write_text(
        json.dumps(
            {
                "monitor": {
                    "step": ["Floorplan - place"],
                    "memory": [],
                    "runtime": [],
                    "instance": [],
                    "frequency": [],
                }
            }
        )
    )

    home = HomeData()
    home.init(str(path))
    data = _read_json(path)
    assert data["monitor"]["step"] == ["Floorplan - place"]
    assert data["monitor"]["memory"] == [""]
    assert data["monitor"]["runtime"] == [""]
    assert data["monitor"]["instance"] == [0]
    assert data["monitor"]["frequency"] == [0.0]

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


def test_setters_do_not_rewrite_healthy_current_values(tmp_path):
    path = tmp_path / "home.json"

    home = HomeData()
    home.init(str(path))
    home.set_flow("/ws/home/flow.json")
    home.set_parameters("/ws/home/parameters.json")
    home.set_checklist("/ws/home/checklist.json")
    before = path.stat().st_mtime_ns

    reloaded = HomeData()
    reloaded.init(str(path))
    reloaded.set_flow("/ws/home/flow.json")
    reloaded.set_parameters("/ws/home/parameters.json")
    reloaded.set_checklist("/ws/home/checklist.json")

    assert path.stat().st_mtime_ns == before


def _set_flow(path, value):
    home = HomeData()
    home.init(str(path))
    home.set_flow(value)


def _set_checklist(path, value):
    home = HomeData()
    home.init(str(path))
    home.set_checklist(value)


def _set_parameters(path, value):
    home = HomeData()
    home.init(str(path))
    home.set_parameters(value)


def _update_monitor(path):
    home = HomeData()
    home.init(str(path))
    home.update_monitor("Floorplan", "place", "12M", "3s", instance=42, frequency=100.0)


def test_concurrent_home_updates_preserve_schema_and_monitor_rows(tmp_path):
    path = tmp_path / "home.json"
    home = HomeData()
    home.init(str(path))
    home.set_layout("/ws/Floorplan_ecc/output/layout.png")
    home.set_metrics_pin_dist("/ws/Floorplan_ecc/output/pin.png")
    home.update_monitor("Synthesis", "yosys", "10M", "1s", instance=10, frequency=50.0)

    processes = [
        Process(target=_set_flow, args=(path, "/ws/home/flow.json")),
        Process(target=_set_checklist, args=(path, "/ws/home/checklist.json")),
        Process(target=_set_parameters, args=(path, "/ws/home/parameters.json")),
        Process(target=_update_monitor, args=(path,)),
    ]

    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=10)

    assert [process.exitcode for process in processes] == [0, 0, 0, 0]
    data = _read_json(path)
    assert data["layout"] == "/ws/Floorplan_ecc/output/layout.png"
    assert data["metrics"]["pin dist."] == "/ws/Floorplan_ecc/output/pin.png"
    assert data["monitor"]["step"] == ["Synthesis - yosys", "Floorplan - place"]
    assert data["monitor"]["memory"] == ["10M", "12M"]
    assert data["flow"] == "/ws/home/flow.json"
    assert data["checklist"] == "/ws/home/checklist.json"
    assert data["parameters"] == "/ws/home/parameters.json"
    assert path.with_name("home.json.lock").exists()
