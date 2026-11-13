"""project.json's synthesis LEC (a ``LEC`` chain step) on a run's flow config."""

import json

import pytest

from chipcompiler.cli.project.config import load_project_config
from chipcompiler.cli.project.manifest_flow import entry_flow_config, manifest_synthesis_lec
from chipcompiler.project.manifest import load_manifest


def _entry(project_dir, **fields):
    entry = {
        "workspace_id": "ws_0001",
        "workspace_path": str(project_dir / "ws_0001"),
        "status": "not_started",
        **fields,
    }
    document = {
        "schema_version": 1,
        "design_name": "gcd",
        "root_path": str(project_dir),
        "workspaces": [entry],
    }
    (project_dir / "project.json").write_text(json.dumps(document))
    return load_manifest(str(project_dir)).workspaces[0]


def _config(project_dir, flow_extra=""):
    (project_dir / "ecc.toml").write_text(
        '[design]\nname = "gcd"\ntop = "gcd"\nrtl = ["rtl/gcd.v"]\nclock_port = "clk"\n'
        'frequency_mhz = 100.0\n\n[flow]\npreset = "rtl2gds"\n' + flow_extra
    )
    return load_project_config(str(project_dir / "ecc.toml"))


@pytest.mark.parametrize(
    ("entry_skip", "flow_extra", "inserted"),
    [
        # project.json still lists LEC as a step: keeping it runs lec@Synthesis.
        ([], "", ["lec@Synthesis"]),
        (["DiffOpt"], "", ["lec@Synthesis"]),
        (["LEC", "DiffOpt"], "", None),
        # An undeclared policy skipped the LEC by default.
        (None, "", None),
        # ecc.toml's skip_steps replaces the entry's policy.
        ([], "skip_steps = []\n", None),
    ],
)
def test_an_entry_keeping_the_lec_inserts_the_synthesis_check(
    tmp_path, entry_skip, flow_extra, inserted
):
    fields = {} if entry_skip is None else {"skip_steps": entry_skip}
    entry = _entry(tmp_path, **fields)

    assert manifest_synthesis_lec(entry, _config(tmp_path, flow_extra)) == inserted


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (
            "Synth",
            "LEC",
            {
                "start_step": "Synth",
                "end_step": "Synthesis",
                "insert_steps": ["lec@Synthesis"],
            },
        ),
        ("Synth", "Route", {"start_step": "Synth", "end_step": "Route"}),
    ],
)
def test_a_range_bounded_by_the_lec_ends_at_synthesis_and_inserts_it(
    tmp_path, start, end, expected
):
    entry = _entry(tmp_path, start_step=start, end_step=end)

    assert entry_flow_config(entry) == expected
