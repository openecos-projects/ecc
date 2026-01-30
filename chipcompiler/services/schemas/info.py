#!/usr/bin/env python
# -*- encoding: utf-8 -*-

from enum import Enum

class InfoEnum(Enum):
    views = "views" # information while switch web page
    layout = "layout" # step design layout
    metrics = "metrics" # step metrics
    subflow = "subflow" # sub steps for this step
    analysis = "analysis" # analysis metrics
    maps = "maps" # maps for this step such as density map
    checklist = "checklist" # step checklist