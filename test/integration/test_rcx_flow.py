#!/usr/bin/env python

import pytest

from chipcompiler.rtl2gds import build_rcx_flow

pytestmark = [pytest.mark.integration, pytest.mark.pdk]


def test_ics55_gcd(run_workspace_flow_factory):
    assert run_workspace_flow_factory(
        build_rcx_flow,
        workspace_suffix="ics55_gcd_rcx",
    )
