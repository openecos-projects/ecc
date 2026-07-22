#!/usr/bin/env python
"""Workspace top-level path names: the on-disk directory/file contract.

These names are written by ``create_workspace``/``load_workspace`` and read
back across modules (signoff, runtime API, CLI). Members are ``str``, so they
compose directly with ``Path /`` and ``os.path.join``.
"""

from enum import StrEnum


class WorkspaceDir(StrEnum):
    """Top-level workspace directories."""

    HOME = "home"
    ORIGIN = "origin"
    LOG = "log"
    CONFIG = "config"


class WorkspaceFile(StrEnum):
    """Workspace contract files (under ``home/`` unless noted)."""

    FLOW = "flow.json"
    PARAMETERS = "parameters.json"
    HOME = "home.json"
    CHECKLIST = "checklist.json"
    PDK = "pdk.json"
    # Under ``origin/``: the canonical input filelist, not runtime temp staging.
    FILELIST = "filelist"
    CLI_PARAM_OVERRIDES = "cli-param-overrides.json"
