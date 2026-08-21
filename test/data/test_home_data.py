import json
from multiprocessing import Process
from pathlib import Path

from chipcompiler.data.home import HomeData


def _read_json(path):
    return json.loads(path.read_text())


def test_init_writes_complete_schema_for_missing_file(tmp_path):
    path = tmp_path / "home.json"

    home = HomeData()
    home.init(path)

    assert _read_json(path) == {
        "parameters": "",
        "flow": "",
        "layout": "",
        "checklist": "",
        "metrics": {},
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
    home.init(path)

    assert _read_json(path) == {
        "parameters": "/ws/home/parameters.json",
        "flow": "/ws/home/flow.json",
        "layout": "",
        "checklist": "/ws/home/checklist.json",
        "metrics": {},
    }


def test_set_metrics_repairs_missing_metrics(tmp_path):
    path = tmp_path / "home.json"
    path.write_text(json.dumps({}))

    home = HomeData()
    home.init(path)
    home.set_metrics_pin_dist(Path("/tmp/pin.png"))

    data = _read_json(path)
    assert data["metrics"]["pin dist."] == "/tmp/pin.png"


def test_setters_do_not_rewrite_healthy_current_values(tmp_path):
    path = tmp_path / "home.json"

    home = HomeData()
    home.init(path)
    home.set_flow(Path("/ws/home/flow.json"))
    home.set_parameters(Path("/ws/home/parameters.json"))
    home.set_checklist(Path("/ws/home/checklist.json"))
    before = path.stat().st_mtime_ns

    reloaded = HomeData()
    reloaded.init(path)
    reloaded.set_flow(Path("/ws/home/flow.json"))
    reloaded.set_parameters(Path("/ws/home/parameters.json"))
    reloaded.set_checklist(Path("/ws/home/checklist.json"))

    assert path.stat().st_mtime_ns == before


def _set_flow(path, value):
    home = HomeData()
    home.init(path)
    home.set_flow(value)


def _set_checklist(path, value):
    home = HomeData()
    home.init(path)
    home.set_checklist(value)


def _set_parameters(path, value):
    home = HomeData()
    home.init(path)
    home.set_parameters(value)


def test_concurrent_home_updates_preserve_schema(tmp_path):
    path = tmp_path / "home.json"
    home = HomeData()
    home.init(path)
    home.set_layout(Path("/ws/Floorplan_ecc/output/layout.png"))
    home.set_metrics_pin_dist(Path("/ws/Floorplan_ecc/output/pin.png"))
    processes = [
        Process(target=_set_flow, args=(path, Path("/ws/home/flow.json"))),
        Process(target=_set_checklist, args=(path, Path("/ws/home/checklist.json"))),
        Process(target=_set_parameters, args=(path, Path("/ws/home/parameters.json"))),
    ]

    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=10)

    assert [process.exitcode for process in processes] == [0, 0, 0]
    data = _read_json(path)
    assert data["layout"] == "/ws/Floorplan_ecc/output/layout.png"
    assert data["metrics"]["pin dist."] == "/ws/Floorplan_ecc/output/pin.png"
    assert data["flow"] == "/ws/home/flow.json"
    assert data["checklist"] == "/ws/home/checklist.json"
    assert data["parameters"] == "/ws/home/parameters.json"
    assert path.with_name("home.json.lock").exists()


def test_init_accepts_path_and_stores_path_object(tmp_path):
    path = tmp_path / "home.json"

    home = HomeData()
    home.init(path)

    assert isinstance(home.path, Path)
    assert home.path == path
    assert path.exists()


def test_path_setters_accept_path_and_persist_strings(tmp_path):
    path = tmp_path / "home.json"
    flow_path = tmp_path / "flow.json"
    parameters_path = tmp_path / "parameters.json"
    checklist_path = tmp_path / "checklist.json"

    home = HomeData()
    home.init(path)
    home.set_flow(flow_path)
    home.set_parameters(parameters_path)
    home.set_checklist(checklist_path)

    data = _read_json(path)
    assert data["flow"] == str(flow_path)
    assert data["parameters"] == str(parameters_path)
    assert data["checklist"] == str(checklist_path)


def test_reset_clears_run_state_but_preserves_workspace_paths(tmp_path):
    path = tmp_path / "home.json"
    home = HomeData()
    home.init(path)
    home.set_flow(tmp_path / "flow.json")
    home.set_parameters(tmp_path / "parameters.json")
    home.set_checklist(tmp_path / "checklist.json")
    home.set_layout(tmp_path / "layout.png")
    home.set_metrics_pin_dist(tmp_path / "pin.png")

    home.reset()

    expected = {
        "parameters": str(tmp_path / "parameters.json"),
        "flow": str(tmp_path / "flow.json"),
        "layout": "",
        "checklist": str(tmp_path / "checklist.json"),
        "metrics": {},
    }
    assert _read_json(path) == expected
    assert home.data == expected
