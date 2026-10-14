import json
from pathlib import Path

import pytest
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


@pytest.mark.parametrize("exit_code,status", [(0, "pass"), (6, "fail"), (7, "unknown")])
def test_campaign_quality_preserves_report_and_gate_exit(tmp_path, monkeypatch, exit_code, status):
    manifest = tmp_path / "campaign.json"
    ledger = tmp_path / "ledger.json"
    calls = []

    def inspect(path, requested_ledger):
        calls.append((Path(path), requested_ledger))
        return {"status": status, "exit_code": exit_code}

    monkeypatch.setattr("ecc_experience.api.campaign_quality", inspect)
    result = CliRunner().invoke(
        app,
        [
            "experience",
            "campaign",
            "quality",
            "--manifest",
            str(manifest),
            "--ledger",
            str(ledger),
            "--json",
        ],
    )

    assert result.exit_code == exit_code, result.output
    assert calls == [(manifest, str(ledger))]
    assert json.loads(result.stdout) == [
        {
            "experience": "campaign_quality",
            "status": status,
            "exit_code": exit_code,
        }
    ]
