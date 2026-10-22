"""Signoff artifact discovery resolves step directories from the data table."""

from chipcompiler.data import StepEnum
from chipcompiler.data.step import STEP_DIRECTORIES
from chipcompiler.engine.signoff.discovery import CollectorDiscoveryMixin


class _Discovery(CollectorDiscoveryMixin):
    pass


def test_design_discovery_reads_the_step_directory_table(tmp_path):
    output = tmp_path / STEP_DIRECTORIES[StepEnum.HARDEN.value] / "output"
    output.mkdir(parents=True)
    (output / "gcd_Harden.gds").write_bytes(b"")

    assert _Discovery()._design_from_outputs(tmp_path) == "gcd"
