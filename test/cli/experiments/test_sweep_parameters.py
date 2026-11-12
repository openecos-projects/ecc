import pytest
from typer.testing import CliRunner

from chipcompiler.cli.app import app
from chipcompiler.cli.experiments import operations


def _create(project, *params):
    args = ["sweep", "create", "--project", str(project), "--name", "probe"]
    for param in params:
        args.extend(["--param", param])
    return CliRunner().invoke(app, args)


def test_create_sweep_rejects_unknown_parameter_name(tmp_path):
    with pytest.raises(operations.UnknownSweepParameterError, match="no.such.parameter"):
        operations.create_sweep(tmp_path, "probe", {"no.such.parameter": ["1"]})

    assert not (tmp_path / "experiments").exists()


def test_unknown_parameter_error_suggests_close_names():
    with pytest.raises(operations.UnknownSweepParameterError) as excinfo:
        operations.check_sweep_parameter_names({"place.target_densty": ["0.5"]})

    assert "unknown_parameter: place.target_densty" in str(excinfo.value)
    assert "place.target_density" in str(excinfo.value)


def test_sweep_create_reports_every_unknown_parameter(tmp_path):
    result = _create(tmp_path, "no.such.parameter=1", "place.target_density=0.5", "bogus=2")

    assert result.exit_code == 1
    assert "unknown_parameter: no.such.parameter" in result.output
    assert "unknown_parameter: bogus" in result.output
    assert "unknown_parameter: place.target_density" not in result.output
    assert not (tmp_path / "experiments").exists()


def test_sweep_create_accepts_known_parameters(tmp_path):
    result = _create(tmp_path, "place.target_density=0.5,0.6", "cts.max_fanout=16")

    assert result.exit_code == 0
    assert (tmp_path / "experiments" / "probe" / "sweep.json").is_file()


def test_sweep_create_keeps_usage_error_for_malformed_parameter(tmp_path):
    result = _create(tmp_path, "place.target_density")

    assert result.exit_code == 2
    assert "KEY=VALUE" in result.output
