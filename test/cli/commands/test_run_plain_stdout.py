"""`ecc run --plain` prints records only on stdout (#433).

A step that finishes may log a warning through the workspace logger. On a run
that creates its workspace nothing captures stdio at that point, so the
console handler of that logger decides where the line goes.
"""

import logging

import pytest

from chipcompiler.cli import main as cli_main
from chipcompiler.engine import EngineFlow

DESIGN = "logprobe"
NOTE = "[QOR] Synthesis(yosys) run facts saved; analysis refresh unavailable"


class NotingFlow(EngineFlow):
    """The real ledger; running the steps only logs what a finished step may log."""

    def create_step_workspaces(self, **_kwargs):
        self.workspace_steps = list(self.workspace.flow.data.get("steps", []))

    def run_steps(self, **_kwargs):
        self.workspace.logger.warning(NOTE)
        return True


@pytest.fixture
def project(tmp_path, monkeypatch, minimal_ics55_pdk_factory):
    """A project whose fresh run builds a real workspace with its real logger."""
    monkeypatch.setattr("chipcompiler.engine.EngineFlow", NotingFlow)
    monkeypatch.setattr(
        "chipcompiler.rtl2gds.builder.build_rtl2gds_flow",
        lambda *, skip=(), lec_engine=None: [("Synthesis", "yosys", "Unstart")],
    )
    monkeypatch.setattr(
        "chipcompiler.cli.project.config._validate_pdk_contents",
        lambda name, root, overrides=None: None,
    )
    directory = tmp_path / "project"
    assert cli_main.run(["init", str(directory), "--design-name", DESIGN]) == 0
    pdk = minimal_ics55_pdk_factory(tmp_path / "pdk")
    (directory / f"rtl/{DESIGN}.v").write_text(f"module {DESIGN}(input clk); endmodule\n")
    config = directory / "ecc.toml"
    config.write_text(config.read_text().replace('root = ""', f'root = "{pdk}"'))
    yield directory
    # The logger is named after the design and keeps its handlers for the process.
    logger = logging.getLogger(DESIGN)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


def test_fresh_plain_run_keeps_logger_warnings_off_stdout(capsys, project, plain_records):
    capsys.readouterr()

    assert cli_main.run(["run", "--project", str(project), "--workspace", "fresh", "--plain"]) == 0

    captured = capsys.readouterr()
    assert NOTE not in captured.out
    assert f"{DESIGN} - WARNING - {NOTE}" in captured.err
    lines = [line for line in captured.out.splitlines() if line.strip()]
    records = plain_records(captured.out)
    assert len(records) == len(lines), captured.out
    assert records[-1]["workspace_id"] == "fresh"
    assert records[-1]["status"] == "success"
