#!/usr/bin/env python

import pytest
from integration.conftest import REPO_ROOT, run_workspace_flow

from chipcompiler.rtl2gds import build_rtl2gds_flow

pytestmark = [pytest.mark.integration, pytest.mark.pdk]


def test_ics55_gcd():
    assert run_workspace_flow(
        build_rtl2gds_flow,
        workspace_suffix="ics55_gcd_tool",
        with_engine_db=True,
    )


def test_sg13g2_gcd():
    assert run_workspace_flow(
        build_rtl2gds_flow,
        pdk_name="sg13g2",
        workspace_suffix="sg13g2_gcd_tool",
        pdk_root=REPO_ROOT / "ihp-sg13g2",
    )


if __name__ == "__main__":
    test_ics55_gcd()
    test_sg13g2_gcd()

    exit(0)
