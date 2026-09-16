"""Migration carries a workspace's persisted skip policy into its
manifest entry (moved out of test_migrate.py, over the size guideline).
"""

import json
import os
from pathlib import Path

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

    def test_malformed_params_toml_blocks_migration_instead_of_dropping_policy(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        create_legacy_workspace,
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        run_dir = create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
        Path(run_dir, "home", "params.toml").write_bytes(b"[flow\nskip_steps = [")

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes"])

        assert rc != 0
        assert os.path.exists(run_dir), "a blocked workspace must stay under runs/"

    def test_invalid_skip_steps_value_blocks_migration(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        create_legacy_workspace,
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        run_dir = create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
        # Write raw invalid policy bypassing save-time validation.
        toml_path = Path(run_dir, "home", "params.toml")
        toml_path.write_text(toml_path.read_text() + "\n[flow.skip_steps]\nroute = true\n")

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes"])

        assert rc != 0
        assert os.path.exists(run_dir)

    def test_ledgers_omitting_declared_skipped_steps_migrate(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        create_legacy_workspace,
    ):
        """A ledger legitimately omitting its declared skipped steps
        (postRouteLec, Timing optimization) is contiguous under the policy
        and must not be blocked as gapped."""
        import json

        from chipcompiler.data.workspace_config import (
            load_workspace_config,
            save_workspace_config,
        )

        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)

        # Build a with-skip ledger directly: Synthesis..Harden minus the
        # two skipped steps, matching the declared policy below.
        from chipcompiler.rtl2gds.builder import build_rtl2gds_flow

        chain = [
            (step.value if hasattr(step, "value") else str(step), str(tool))
            for step, tool, _state in build_rtl2gds_flow()
        ]
        skipped = {"postRouteLec", "Timing optimization"}
        kept = [(name, tool) for name, tool in chain if name not in skipped]

        rtl_path = os.path.join(project_dir, "rtl", "gcd.v")
        os.makedirs(os.path.dirname(rtl_path), exist_ok=True)
        with open(rtl_path, "w") as f:
            f.write("module gcd(input clk); endmodule\n")

        run_dir = os.path.join(project_dir, "runs", "exp1")
        from chipcompiler.data import create_workspace

        workspace = create_workspace(
            directory=run_dir,
            origin_def="",
            origin_verilog=rtl_path,
            pdk="ics55",
            parameters={"pdk": "ics55", "design": "gcd", "top_module": "gcd", "clock": "clk"},
            pdk_root=str(pdk_root),
        )
        assert workspace is not None
        home = os.path.join(run_dir, "home")
        with open(os.path.join(home, "flow.json"), "w") as f:
            json.dump(
                {
                    "steps": [
                        {
                            "name": name,
                            "tool": tool,
                            "state": "Success",
                            "runtime": "",
                            "peak memory (mb)": 0,
                            "info": {},
                        }
                        for name, tool in kept
                    ]
                },
                f,
            )
        payload = load_workspace_config(run_dir)
        payload.pop("_flow", None)
        assert save_workspace_config(
            run_dir,
            payload,
            {"start": "Synthesis", "end": "Harden", "skip_steps": sorted(skipped)},
        )

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes"])

        assert rc == 0
        (entry,) = _manifest(project_dir)["workspaces"]
        assert entry["skip_steps"] == ["Timing optimization", "postRouteLec"]

    def test_explicit_empty_policy_with_lec_less_ledger_is_blocked(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        minimal_ics55_pdk_factory,
        create_legacy_workspace,
    ):
        """Explicit skip_steps = [] is authoritative: a LEC-less ledger is
        NOT accepted by the legacy-era tolerance, because the declared
        policy says the LEC should have run."""
        from chipcompiler.data.workspace_config import (
            load_workspace_config,
            save_workspace_config,
        )

        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        run_dir = create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
        # Rewrite the ledger WITHOUT the LEC, then declare skip_steps = [].
        ledger_path = Path(run_dir, "home", "flow.json")
        ledger = json.loads(ledger_path.read_text())
        ledger["steps"] = [step for step in ledger["steps"] if step["name"] != "lec"]
        ledger_path.write_text(json.dumps(ledger))
        payload = load_workspace_config(run_dir)
        payload.pop("_flow", None)
        assert save_workspace_config(
            run_dir,
            payload,
            {"start": "Synthesis", "end": "postFloorplan", "skip_steps": []},
        )

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes"])

        assert rc != 0
        assert os.path.exists(run_dir), "a blocked workspace must stay under runs/"
