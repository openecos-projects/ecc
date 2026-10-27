#!/usr/bin/env python
from chipcompiler.tools.subflow import SubFlow


class YosysLecSubFlow(SubFlow):
    STAGES = ("run lec", "analysis")
