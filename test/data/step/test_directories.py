"""Flow ledger steps record the directory their step is built in."""

from pathlib import Path

import pytest

from chipcompiler.data import LecDualStep, OriginDesign, Workspace, WorkspaceStep
from chipcompiler.data.step import (
    engine_step_directory,
    new_step_directory,
    recorded_step_directory,
)
from chipcompiler.data.workspace.flow_data import build_dynamic_flow_data
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
        {"start_step": "Synthesis", "end_step": "Harden", "skip_steps": [], "lec_engine": "dual"}
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
        "01_Synthesis_yosys",
        "23_Harden_ecc",
    )


def test_ledgers_without_directories_keep_the_names_they_were_created_with(tmp_path):
    ledger = _rtl2gds_ledger()
    for record in ledger.get("steps", []):
        record.pop("directory", None)

    flow = _flow(tmp_path, ledger)

    assert [_directory_name(step) for step in flow.workspace_steps] == [
        new_step_directory(record["name"], record["tool"]) for record in ledger.get("steps", [])
    ]
    assert _directory_name(flow.workspace_steps[0]) == "Synthesis_yosys"


def test_a_recorded_directory_is_where_the_step_is_built(tmp_path):
    ledger = _rtl2gds_ledger()
    for index, record in enumerate(ledger.get("steps", []), start=1):
        record["directory"] = new_step_directory(record["name"], record["tool"], index=index)

    flow = _flow(tmp_path, ledger)

    place = flow.get_workspace_step("place")
    lec = flow.get_workspace_step("lec")
    assert place is not None and isinstance(lec, LecDualStep)
    assert (_directory_name(place), _directory_name(lec)) == ("07_place_dreamplace", "02_lec_dual")
    assert {name: _directory_name(step) for name, step in lec.engine_steps.items()} == {
        "yosys_lec": "02_lec_yosys_lec",
        "kepler_formal": "02_lec_kepler_formal",
    }


@pytest.mark.parametrize(
    ("step", "tool", "index", "expected"),
    [
        ("Synthesis", "yosys", None, "Synthesis_yosys"),
        ("Timing optimization", "sizer", 11, "11_timing_optimization_sizer"),
        ("postRouteLec", "lec_dual", 18, "18_postRouteLec_dual"),
        ("place", "ecc", 7, "07_place_ecc"),
    ],
)
def test_new_step_directory_names(step, tool, index, expected):
    assert new_step_directory(step, tool, index=index) == expected


@pytest.mark.parametrize("directory", ["../place_dreamplace", "a/b", "..", "", 7])
def test_a_recorded_directory_must_be_a_single_name(directory):
    with pytest.raises(ValueError, match="single directory name"):
        recorded_step_directory({"name": "place", "tool": "dreamplace", "directory": directory})


def test_engine_directories_of_a_non_dual_step_are_rejected():
    with pytest.raises(ValueError, match="not a dual LEC step directory"):
        engine_step_directory(Path("/ws/02_lec_kepler_formal"), "yosys_lec")


def test_step_directories_follow_recorded_names_and_keep_legacy_ones(tmp_path):
    from chipcompiler.data.step import StepDirectories

    records = [
        {"name": "place", "tool": "dreamplace", "directory": "07_place_dreamplace"},
        {"name": "sta", "tool": "ecc"},
    ]

    directories = StepDirectories.from_records(tmp_path, records)

    assert [directories.path("place"), directories.path("sta"), directories.path("drc")] == [
        tmp_path / "07_place_dreamplace",
        tmp_path / "sta_ecc",
        tmp_path / "drc_ecc",
    ]
    assert directories.scan_names()[:2] == ["07_place_dreamplace", "Synthesis_yosys"]


def test_step_directories_read_the_persisted_ledger(tmp_path):
    import json

    from chipcompiler.data.step import StepDirectories

    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "flow.json").write_text(
        json.dumps({"steps": [{"name": "RCX", "tool": "ecc", "directory": "18_RCX_ecc"}]}),
        encoding="utf-8",
    )

    assert StepDirectories.at(tmp_path).name("RCX") == "18_RCX_ecc"


@pytest.mark.parametrize(
    ("tool", "expected"),
    [
        ("yosys_lec", "postRouteLec_yosys_lec"),
        ("lec_dual", "postRouteLec_dual"),
        ("kepler_formal", "postRouteLec_kepler_formal"),
    ],
)
def test_unrecorded_ledger_steps_keep_their_engine_directory(tmp_path, tool, expected):
    from chipcompiler.data.step import StepDirectories

    directories = StepDirectories.from_records(tmp_path, [{"name": "postRouteLec", "tool": tool}])

    assert directories.name("postRouteLec") == expected


@pytest.mark.parametrize(
    ("directories", "expected"),
    [
        ([], 1),
        (["01_Synthesis_yosys", "03_place_dreamplace"], 4),
        (["Synthesis_yosys"], None),
        (["01_Synthesis_yosys", None], None),
    ],
)
def test_appended_steps_take_the_next_free_index(directories, expected):
    from chipcompiler.data.step import next_step_index

    records = [
        {"name": "step", "tool": "ecc"} | ({} if directory is None else {"directory": directory})
        for directory in directories
    ]

    assert next_step_index(records) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("07_place_dreamplace", "place_dreamplace"),
        ("120_route_ecc", "route_ecc"),
        ("CTS_ecc", "CTS_ecc"),
    ],
)
def test_unindexed_step_directory_names(name, expected):
    from chipcompiler.data.step import unindexed_step_directory

    assert unindexed_step_directory(name) == expected


def test_added_steps_extend_an_indexed_ledger_and_keep_a_legacy_one(tmp_path):
    workspace = Workspace(directory=tmp_path)
    flow = EngineFlow(workspace)
    flow.add_step("place", "dreamplace", "Unstart")
    flow.add_step("CTS", "ecc", "Unstart")
    legacy = EngineFlow(Workspace(directory=tmp_path / "legacy"))
    legacy.workspace.flow.data = {"steps": [{"name": "place", "tool": "dreamplace", "state": "x"}]}
    legacy.add_step("CTS", "ecc", "Unstart")

    assert [record.get("directory") for record in flow.workspace.flow.steps()] == [
        "01_place_dreamplace",
        "02_CTS_ecc",
    ]
    assert legacy.workspace.flow.steps()[-1].get("directory") == "CTS_ecc"


def test_a_step_dropped_from_the_ledger_is_found_in_its_inherited_directory(tmp_path):
    """A derived workspace keeps the directories of the steps its ledger dropped."""
    from chipcompiler.data.step import StepDirectories

    for name in ("18_RCX_ecc", "19_RCX_ecc", "20_sta_ecc"):
        (tmp_path / name).mkdir()
    records = [{"name": "sta", "tool": "ecc", "directory": "20_sta_ecc"}]

    directories = StepDirectories.from_records(tmp_path, records)

    assert [directories.name("sta"), directories.name("RCX"), directories.name("drc")] == [
        "20_sta_ecc",
        "19_RCX_ecc",
        "drc_ecc",
    ]
    # Scans visit the newest inherited directory of each step, not every copy.
    assert directories.scan_names()[:2] == ["20_sta_ecc", "19_RCX_ecc"]
    assert "18_RCX_ecc" not in directories.scan_names()


def test_a_legacy_directory_wins_over_an_inherited_indexed_one(tmp_path):
    from chipcompiler.data.step import StepDirectories

    for name in ("RCX_ecc", "19_RCX_ecc"):
        (tmp_path / name).mkdir()

    assert StepDirectories.from_records(tmp_path, []).name("RCX") == "RCX_ecc"
