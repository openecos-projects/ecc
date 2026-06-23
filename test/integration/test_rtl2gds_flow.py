#!/usr/bin/env python

from pathlib import Path

import pytest

from chipcompiler.rtl2gds import build_rtl2gds_flow

pytestmark = [pytest.mark.integration, pytest.mark.pdk]


def test_ics55_gcd(run_workspace_flow_factory):
    assert run_workspace_flow_factory(
        build_rtl2gds_flow,
        workspace_suffix="ics55_gcd_tool",
        with_engine_db=True,
    )


def test_sg13g2_gcd(run_workspace_flow_factory):
    assert run_workspace_flow_factory(
        build_rtl2gds_flow,
        pdk_name="sg13g2",
        workspace_suffix="sg13g2_gcd_tool",
        pdk_root=Path(__file__).resolve().parents[2] / "ihp-sg13g2",
    )
