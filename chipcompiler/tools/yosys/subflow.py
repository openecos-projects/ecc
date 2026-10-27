#!/usr/bin/env python
from chipcompiler.tools.subflow import SubFlow


class YosysSubFlow(SubFlow):
    STAGES = ("run yosys", "analysis")
