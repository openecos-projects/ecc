#!/usr/bin/env python
from chipcompiler.tools.subflow import SubFlow


class KeplerFormalSubFlow(SubFlow):
    """kepler-formal LEC inner flow (run lec, analysis)."""

    STAGES = ("run lec", "analysis")
