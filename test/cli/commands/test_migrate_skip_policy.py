"""Migration carries a workspace's persisted skip policy into its
manifest entry (moved out of test_migrate.py, over the size guideline).
"""

import json
import os

from chipcompiler.cli import main as cli_main


def _manifest(project_dir):
    with open(os.path.join(project_dir, "project.json")) as f:
        return json.load(f)


class TestMigrationSkipPolicy:
    def test_persisted_skip_policy_carries_into_the_manifest_entry(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        create_legacy_workspace,
    ):
        from chipcompiler.data.workspace_config import (
            load_workspace_config,
            save_workspace_config,
        )

        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        run_dir = create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
        # A declared policy (here: timing optimization) on the existing payload.
        payload = load_workspace_config(run_dir)
        payload.pop("_flow", None)
        assert save_workspace_config(
            run_dir,
            payload,
            {"start": "Synthesis", "end": "postFloorplan", "skip_steps": ["TimingOpt"]},
        )

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes"])

        assert rc == 0
        (workspace,) = _manifest(project_dir)["workspaces"]
        # The persisted policy is normalized by save_workspace_config, so
        # the manifest entry carries the canonical step value.
        assert workspace["skip_steps"] == ["Timing optimization"]

    def test_undeclared_and_empty_skip_policies_stay_distinct_after_migration(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        create_legacy_workspace,
    ):
        from chipcompiler.data.workspace_config import (
            load_workspace_config,
            save_workspace_config,
        )

        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        absent_dir = create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
        empty_dir = create_legacy_workspace(project_dir, pdk_root, "exp2", ["Success", "Success"])
        for run_dir, section in (
            (empty_dir, {"start": "Synthesis", "end": "postFloorplan", "skip_steps": []}),
            (absent_dir, {"start": "Synthesis", "end": "postFloorplan"}),
        ):
            payload = load_workspace_config(run_dir)
            payload.pop("_flow", None)
            assert save_workspace_config(run_dir, payload, section)

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes"])

        assert rc == 0
        entries = {entry["workspace_id"]: entry for entry in _manifest(project_dir)["workspaces"]}
        assert "skip_steps" not in entries["exp1"]
        assert entries["exp2"]["skip_steps"] == []
