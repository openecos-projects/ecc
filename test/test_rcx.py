#!/usr/bin/env python

import pytest
from integration.conftest import run_workspace_flow

from chipcompiler.rtl2gds import build_rcx_flow

pytestmark = [pytest.mark.integration, pytest.mark.pdk]


def test_ics55_gcd():
    assert run_workspace_flow(
        build_rcx_flow,
        workspace_suffix="ics55_gcd_rcx",
    )


if __name__ == "__main__":
    test_ics55_gcd()

    exit(0)
