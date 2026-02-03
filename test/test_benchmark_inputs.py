#!/usr/bin/env python
"""
Test benchmark input validation and priority logic.

Tests 8 input combinations (filelist/rtl/netlist):
- Validation: 7 valid + 1 invalid
- Priority: filelist > rtl > netlist
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

current_dir = os.path.dirname(os.path.abspath(__file__))
root = os.path.dirname(current_dir)
sys.path.insert(0, root)

from benchmark.benchmark import run_benchmark, run_single_design  # noqa: E402
from chipcompiler.data import StepEnum  # noqa: E402

FIXTURES_DIR = os.path.join(current_dir, "fixtures", "benchmark")


@pytest.fixture
def _mock_multiprocessing():
    """Mock multiprocessing.Process to prevent actual process spawn."""
    with patch("multiprocessing.Process") as mock_cls:
        mock_proc = MagicMock()
        mock_proc.is_alive.return_value = False
        mock_cls.return_value = mock_proc
        yield mock_cls


@pytest.fixture
def mock_engine_flow():
    """Mock EngineFlow to capture steps without running."""
    captured_steps = []

    def capture_step(step, tool, state):
        captured_steps.append((step, tool, state))

    with (
        patch("benchmark.benchmark.EngineFlow.run_steps"),
        patch("benchmark.benchmark.EngineFlow.add_step", side_effect=capture_step),
    ):
        yield captured_steps


# Valid input files that should pass validation
VALID_INPUTS = [
    "test_filelist.json",
    "test_rtl.json",
    "test_netlist.json",
    "test_filelist_rtl.json",
    "test_filelist_netlist.json",
    "test_rtl_netlist.json",
    "test_all_inputs.json",
]

# Files that should have SYNTHESIS step (filelist or rtl present)
INPUTS_WITH_SYNTHESIS = [
    ("test_filelist.json", "#1: filelist only"),
    ("test_rtl.json", "#2: rtl only"),
    ("test_filelist_rtl.json", "#4: filelist + rtl"),
    ("test_filelist_netlist.json", "#5: filelist + netlist"),
    ("test_rtl_netlist.json", "#6: rtl + netlist"),
    ("test_all_inputs.json", "#7: all inputs"),
]


@pytest.mark.usefixtures("_mock_multiprocessing")
class TestValidation:
    """Test JSON validation logic."""

    @pytest.mark.parametrize("json_file", VALID_INPUTS)
    def test_valid_inputs_pass(self, json_file):
        """Valid inputs should pass validation."""
        json_path = os.path.join(FIXTURES_DIR, json_file)
        run_benchmark(json_path)  # Should not raise

    def test_no_input_fails(self):
        """No input should fail validation."""
        json_path = os.path.join(FIXTURES_DIR, "test_no_input.json")
        with pytest.raises(ValueError, match="missing required fields"):
            run_benchmark(json_path)


class TestPriority:
    """Test input priority logic (filelist > rtl > netlist)."""

    def _run_and_get_steps(self, json_file: str, mock_engine_flow) -> list:
        """Run design and return captured steps."""
        from chipcompiler.utility import json_read

        json_path = os.path.join(FIXTURES_DIR, json_file)
        data = json_read(json_path)
        workspace_dir = f"/tmp/test_{json_file.replace('.json', '')}"

        from contextlib import suppress

        with suppress(Exception):
            run_single_design(workspace_dir, data["pdk"], data["designs"][0])

        return mock_engine_flow

    @pytest.mark.parametrize("json_file,desc", INPUTS_WITH_SYNTHESIS)
    def test_has_synthesis(self, json_file, desc, mock_engine_flow):
        """Inputs with filelist or rtl should have SYNTHESIS step."""
        steps = self._run_and_get_steps(json_file, mock_engine_flow)
        step_types = [s[0] for s in steps]
        assert StepEnum.SYNTHESIS in step_types, f"{desc}: expected SYNTHESIS"

    def test_netlist_only_skips_synthesis(self, mock_engine_flow):
        """#3: netlist only -> no SYNTHESIS step."""
        steps = self._run_and_get_steps("test_netlist.json", mock_engine_flow)
        step_types = [s[0] for s in steps]
        assert StepEnum.SYNTHESIS not in step_types


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
