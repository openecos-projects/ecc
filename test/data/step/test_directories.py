"""Flow ledger steps record the directory their step is built in."""

import pytest

from chipcompiler.data import KeplerFormalStep, OriginDesign, Workspace, WorkspaceStep
from chipcompiler.data.flow.build import build_dynamic_flow_data
from chipcompiler.data.step import new_step_directory, recorded_step_directory
from chipcompiler.engine.flow import EngineFlow


def _flow(tmp_path, ledger) -> EngineFlow:
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd", origin_verilog=tmp_path / "gcd.v"),
    )
    flow = EngineFlow(workspace)
    flow.workspace.flow.data = ledger
    flow.create_step_workspaces(executable_steps=set(), initialize_config=False)
    return flow


def _rtl2gds_ledger():
    return build_dynamic_flow_data(
        {
            "start_step": "synthesis",
            "end_step": "harden",
            "skip_steps": [],
            "insert_steps": ["lec@synthesis"],
        }
    )


def _directory_name(step: WorkspaceStep) -> str:
    assert step.directory is not None
    return step.directory.name


def test_new_ledgers_record_the_directory_each_step_is_built_in(tmp_path):
    ledger = _rtl2gds_ledger()

    flow = _flow(tmp_path, ledger)

    records = ledger.get("steps", [])
    assert [record.get("directory") for record in records] == [
        _directory_name(step) for step in flow.workspace_steps
    ]
    assert (records[0].get("directory"), records[-1].get("directory")) == (
        "01_synthesis_yosys",
        "23_harden_ecc",
    )


def test_ledgers_without_directories_are_rejected(tmp_path):
    ledger = _rtl2gds_ledger()
    for record in ledger.get("steps", []):
        record.pop("directory", None)

    with pytest.raises(ValueError, match="no recorded directory"):
        _flow(tmp_path, ledger)


def test_a_recorded_directory_is_where_the_step_is_built(tmp_path):
    ledger = _rtl2gds_ledger()
    for index, record in enumerate(ledger.get("steps", []), start=1):
        record["directory"] = new_step_directory(record["name"], record["tool"], index=index)

    flow = _flow(tmp_path, ledger)

    place = flow.get_workspace_step("placement")
    lec = flow.get_workspace_step("lec@synthesis")
    assert place is not None and isinstance(lec, KeplerFormalStep)
    assert (_directory_name(place), _directory_name(lec)) == (
        "07_placement_dreamplace",
        "02_lec@synthesis_kepler_formal",
    )


@pytest.mark.parametrize(
    ("step", "tool", "index", "expected"),
    [
        ("synthesis", "yosys", None, "synthesis_yosys"),
        ("timing_optimization", "sizer", 11, "11_timing_optimization_sizer"),
        ("post_route_lec", "kepler_formal", 18, "18_post_route_lec_kepler_formal"),
        ("placement", "ecc", 7, "07_placement_ecc"),
    ],
)
def test_new_step_directory_names(step, tool, index, expected):
    assert new_step_directory(step, tool, index=index) == expected


@pytest.mark.parametrize("directory", ["../placement_dreamplace", "a/b", "..", "", 7])
def test_a_recorded_directory_must_be_a_single_name(directory):
    with pytest.raises(ValueError, match="single directory name"):
        recorded_step_directory({"name": "placement", "tool": "dreamplace", "directory": directory})


def test_step_directories_use_recorded_names(tmp_path):
    from chipcompiler.data.step import StepDirectories

    records = [
        {"name": "placement", "tool": "dreamplace", "directory": "07_placement_dreamplace"},
        {"name": "sta", "tool": "ecc", "directory": "19_sta_ecc"},
    ]

    directories = StepDirectories.from_records(tmp_path, records)

    assert [directories.path("placement"), directories.path("sta")] == [
        tmp_path / "07_placement_dreamplace",
        tmp_path / "19_sta_ecc",
    ]
    assert directories.scan_names() == ["07_placement_dreamplace", "19_sta_ecc"]


def test_step_directories_reject_a_record_without_a_directory(tmp_path):
    from chipcompiler.data.step import StepDirectories

    with pytest.raises(ValueError, match="no recorded directory"):
        StepDirectories.from_records(tmp_path, [{"name": "sta", "tool": "ecc"}])


def test_step_directories_read_the_persisted_ledger(tmp_path):
    import json

    from chipcompiler.data.step import StepDirectories

    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "flow.json").write_text(
        json.dumps(
            {
                "schema_version": 3,
                "steps": [
                    {
                        "name": "rcx",
                        "tool": "ecc",
                        "state": "Success",
                        "category": "CHECKER",
                        "directory": "18_rcx_ecc",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert StepDirectories.at(tmp_path).name("rcx") == "18_rcx_ecc"


def test_unrecorded_ledger_steps_are_rejected(tmp_path):
    from chipcompiler.data.step import StepDirectories

    with pytest.raises(ValueError, match="no recorded directory"):
        StepDirectories.from_records(
            tmp_path, [{"name": "post_route_lec", "tool": "kepler_formal"}]
        )


def test_an_inherited_indexed_directory_wins_over_a_legacy_one(tmp_path):
    from chipcompiler.data.step import StepDirectories

    for name in ("rcx_ecc", "19_rcx_ecc"):
        (tmp_path / name).mkdir()

    assert StepDirectories.from_records(tmp_path, []).name("rcx") == "19_rcx_ecc"
