import json

from typer.testing import CliRunner

from chipcompiler.cli.app import app
from ecc_experience.knowledge.normalize import normalize_stores
from ecc_experience.knowledge.store import ExperienceStore
from test.experience.test_summary import _case


def test_release_from_manifest_command_reports_partial_promotion(tmp_path):
    source = ExperienceStore(tmp_path / "source")
    source.put(_case(tmp_path, "cli"), {})
    normalize_stores([source.root], tmp_path / "normalized")

    result = CliRunner().invoke(
        app,
        [
            "experience",
            "release",
            "from-manifest",
            "--manifest",
            str(tmp_path / "normalized/normalized-manifest.json"),
            "--store",
            str(tmp_path / "release-store"),
            "--output",
            str(tmp_path / "release.json"),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    record = json.loads(result.stdout)[0]
    assert record["experience"] == "release_from_manifest"
    assert record["release_created"] is True
    assert record["included_count"] == 1
