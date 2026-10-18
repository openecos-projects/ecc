import json
from pathlib import Path

import pytest

from chipcompiler.cli import main as cli_main


@pytest.mark.parametrize(
    "step,tool,display",
    [("preplace", "sizer", "Preplace"), ("diff_sizing", "dreamplace", "DiffSizing")],
)
def test_migration_preserves_timing_range_endpoints(
    tmp_path,
    create_cli_project,
    minimal_ics55_pdk_factory,
    create_legacy_workspace,
    step,
    tool,
    display,
):
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    project = Path(create_cli_project(pdk_root=pdk_root))
    home = (
        Path(
            create_legacy_workspace(str(project), pdk_root, "timing_range", ["Success", "Success"])
        )
        / "home"
    )
    (home / "flow.json").write_text(
        json.dumps({"steps": [{"name": step, "tool": tool, "state": "Success"}]})
    )

    result = cli_main.run(["migrate", "--project", str(project), "--yes", "--plain"])

    assert result == 0
    entry = json.loads((project / "project.json").read_text())["workspaces"][0]
    assert {key: entry[key] for key in ("start_step", "end_step")} == {
        "start_step": display,
        "end_step": display,
    }
