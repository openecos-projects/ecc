import json
from pathlib import Path

from typer.testing import CliRunner

from chipcompiler.cli.app import app


def test_campaign_run_passes_retry_and_preserves_exit_code(tmp_path, monkeypatch):
    manifest = tmp_path / "campaign.json"
    calls = []

    def execute(path, *, retry_failed):
        calls.append((Path(path), retry_failed))
        return {"status": "completed_with_failures", "exit_code": 6}

    monkeypatch.setattr("ecc_experience.api.run_campaign", execute)
    result = CliRunner().invoke(
        app,
        [
            "experience",
            "campaign",
            "run",
            "--manifest",
            str(manifest),
            "--retry-failed",
            "--json",
        ],
    )

    assert result.exit_code == 6, result.output
    assert calls == [(manifest, True)]
    assert json.loads(result.stdout) == [
        {
            "experience": "campaign_run",
            "status": "completed_with_failures",
            "exit_code": 6,
        }
    ]
