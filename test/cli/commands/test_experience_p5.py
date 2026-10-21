import json

from typer.testing import CliRunner

from chipcompiler.cli.app import app
from ecc_experience import api


def test_model_seed_sweep_uses_current_project(tmp_path, monkeypatch):
    (tmp_path / "ecc.toml").write_text("")
    monkeypatch.chdir(tmp_path)
    calls = []

    def seed(project, advice, model_release, name):
        calls.append((project, advice, model_release, name))
        return {"status": "created", "name": name, "candidate_count": 2, "safe_to_apply": False}

    monkeypatch.setattr(api, "model_seed_sweep", seed)
    result = CliRunner().invoke(
        app,
        [
            "experience",
            "model",
            "seed-sweep",
            "--advice",
            "advice.json",
            "--model-release",
            "release.json",
            "--name",
            "model-seeded",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert calls[0][0] == str(tmp_path)
    assert json.loads(result.stdout)[0]["safe_to_apply"] is False
