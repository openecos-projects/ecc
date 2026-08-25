import json
import os

from chipcompiler.cli import main as cli_main


def _create_legacy_workspace(project_dir, pdk_root, run_id, states):
    from chipcompiler.data import create_workspace

    rtl_path = os.path.join(project_dir, "rtl", "gcd.v")
    os.makedirs(os.path.dirname(rtl_path), exist_ok=True)
    with open(rtl_path, "w") as f:
        f.write("module gcd(input clk, output y); assign y = clk; endmodule\n")

    run_dir = os.path.join(project_dir, "runs", run_id)
    workspace = create_workspace(
        directory=run_dir,
        origin_def="",
        origin_verilog=rtl_path,
        pdk="ics55",
        parameters={"pdk": "ics55", "design": "gcd", "top_module": "gcd", "clock": "clk"},
        pdk_root=str(pdk_root),
    )
    assert workspace is not None

    steps = [
        {
            "name": "Synthesis",
            "tool": "yosys",
            "state": states[0],
            "runtime": "",
            "peak memory (mb)": 0,
            "info": {},
        },
        {
            "name": "Floorplan",
            "tool": "ecc",
            "state": states[1],
            "runtime": "",
            "peak memory (mb)": 0,
            "info": {},
        },
    ]
    with open(os.path.join(run_dir, "home", "flow.json"), "w") as f:
        json.dump({"steps": steps}, f)
    return run_dir


def _records(capsys):
    return json.loads(capsys.readouterr().out)["records"]


def _manifest(project_dir):
    with open(os.path.join(project_dir, "project.json")) as f:
        return json.load(f)


class TestMigrate:
    def test_full_migration_moves_rebases_and_registers(
        self, tmp_path, capsys, create_cli_project, minimal_ics55_pdk_factory
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        run_dir = _create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes", "--json"])

        assert rc == 0
        target = os.path.join(project_dir, "exp1")
        assert not os.path.exists(run_dir)
        assert os.path.isfile(os.path.join(target, "home", "ecc.toml"))
        assert not os.path.exists(os.path.join(project_dir, "runs"))

        with open(os.path.join(target, "home", "home.json")) as f:
            home = json.load(f)
        assert home["parameters"] == os.path.join(target, "home", "ecc.toml")
        assert home["flow"] == os.path.join(target, "home", "flow.json")
        assert "runs" not in home["flow"]

        manifest = _manifest(project_dir)
        (entry,) = manifest["workspaces"]
        assert entry["workspace_id"] == "exp1"
        assert entry["workspace_path"] == target
        assert entry["start_step"] == "Synth"
        assert entry["end_step"] == "Floor"
        assert entry["status"] == "success"
        assert manifest["design_name"] == "gcd"
        assert manifest["qor_baseline"]["workspace_id"] == "exp1"

        records = _records(capsys)
        assert any(r.get("status") == "migrated" and r.get("run") == "exp1" for r in records)

    def test_non_tty_requires_yes(
        self, tmp_path, capsys, create_cli_project, minimal_ics55_pdk_factory, monkeypatch
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        run_dir = _create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)

        rc = cli_main.run(["migrate", "--project", project_dir, "--json"])

        assert rc != 0
        records = _records(capsys)
        assert records[-1]["error"] == "confirmation_required"
        assert os.path.exists(run_dir)
        assert not os.path.exists(os.path.join(project_dir, "project.json"))

    def test_resume_appends_missing_entries(
        self, tmp_path, capsys, create_cli_project, minimal_ics55_pdk_factory
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        _create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])
        remaining = _create_legacy_workspace(
            project_dir, pdk_root, "exp2", ["Success", "Incomplete"]
        )
        # Partial prior migration: exp1 already at root + registered.
        os.rename(os.path.join(project_dir, "runs", "exp1"), os.path.join(project_dir, "exp1"))
        document = {
            "schema_version": 1,
            "design_name": "gcd",
            "root_path": project_dir,
            "base_design": {"parameters": {"design": "gcd"}},
            "workspaces": [
                {
                    "workspace_id": "exp1",
                    "workspace_path": os.path.join(project_dir, "exp1"),
                    "status": "success",
                    "start_step": "Synth",
                    "end_step": "Floor",
                }
            ],
        }
        with open(os.path.join(project_dir, "project.json"), "w") as f:
            json.dump(document, f)

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes", "--json"])

        assert rc == 0
        manifest = _manifest(project_dir)
        ids = [w["workspace_id"] for w in manifest["workspaces"]]
        assert ids == ["exp1", "exp2"]
        assert manifest["workspaces"][1]["status"] == "failed"
        assert not os.path.exists(remaining)
        assert not os.path.exists(os.path.join(project_dir, "runs"))

    def test_already_migrated_noop(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        document = {
            "schema_version": 1,
            "design_name": "gcd",
            "root_path": project_dir,
            "workspaces": [],
        }
        with open(os.path.join(project_dir, "project.json"), "w") as f:
            json.dump(document, f)

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes", "--json"])

        assert rc == 0
        (record,) = _records(capsys)
        assert record["status"] == "already_migrated"

    def test_collision_skips_that_workspace(
        self, tmp_path, capsys, create_cli_project, minimal_ics55_pdk_factory
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        run_dir = _create_legacy_workspace(project_dir, pdk_root, "rtl", ["Success", "Success"])
        _create_legacy_workspace(project_dir, pdk_root, "exp2", ["Success", "Success"])

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes", "--json"])

        assert rc != 0
        records = _records(capsys)
        collisions = [r for r in records if r.get("error") == "migration_collision"]
        assert len(collisions) == 1
        assert collisions[0]["run"] == "rtl"
        # The colliding workspace stays; the other one moved.
        assert os.path.exists(run_dir)
        assert os.path.exists(os.path.join(project_dir, "exp2"))
        assert os.path.exists(os.path.join(project_dir, "runs"))

    def test_rebase_failure_rolls_back(
        self, tmp_path, capsys, create_cli_project, minimal_ics55_pdk_factory, monkeypatch
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=pdk_root)
        run_dir = _create_legacy_workspace(project_dir, pdk_root, "exp1", ["Success", "Success"])

        def failing_refresh(workspace):
            raise RuntimeError("boom")

        monkeypatch.setattr(
            "chipcompiler.data.refresh_workspace_config",
            failing_refresh,
        )

        rc = cli_main.run(["migrate", "--project", project_dir, "--yes", "--json"])

        assert rc != 0
        records = _records(capsys)
        failures = [r for r in records if r.get("error") == "migration_failed"]
        assert len(failures) == 1
        # Rolled back: the workspace is back under runs/, no manifest, and
        # the rebased home.json pointers were restored to the source path.
        assert os.path.isfile(os.path.join(run_dir, "home", "flow.json"))
        assert not os.path.exists(os.path.join(project_dir, "exp1"))
        assert not os.path.exists(os.path.join(project_dir, "project.json"))
        with open(os.path.join(run_dir, "home", "home.json")) as f:
            home = json.load(f)
        assert home["flow"] == os.path.join(run_dir, "home", "flow.json")
