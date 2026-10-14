import importlib.util
import json
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from chipcompiler.cli.app import app


def test_smoke_checks_the_real_cli_contract_and_preserves_source(tmp_path, monkeypatch):
    path = Path(__file__).parents[2] / "packaging/experience_cli_smoke.py"
    specification = importlib.util.spec_from_file_location("experience_cli_smoke", path)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    project = tmp_path / "generic project"
    home = project / "workspace/home"
    home.mkdir(parents=True)
    (project / "ecc.toml").write_text("")
    flow = home / "flow.json"
    flow.write_text(json.dumps({"steps": [{"name": "STA", "state": "Success"}]}))
    original = flow.read_bytes()
    runner = CliRunner()

    def invoke(command, **kwargs):
        result = runner.invoke(app, command[1:])
        return subprocess.CompletedProcess(command, result.exit_code, result.stdout, result.stderr)

    monkeypatch.setattr(module.subprocess, "run", invoke)
    result = module.run_smoke(Path("ecc"), project, "workspace", tmp_path / "output")
    assert result["status"] == "pass"
    assert flow.read_bytes() == original
    assert not (home / "engineering-snapshot.json").exists()
    assert (tmp_path / "output/verify-corrupt.exit").read_text() == "6"
    assert (tmp_path / "output/quality.exit").read_text() == "7"
    assert (tmp_path / "output/quality-corrupt.exit").read_text() == "6"
