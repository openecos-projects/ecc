#!/usr/bin/env python
# -*- encoding: utf-8 -*-

from chipcompiler.tools.ecc.utility import is_eda_exist as is_ecc_exist


def is_eda_exist() -> bool:
    if not is_ecc_exist():
        return False

    try:
        from .module import ECCToolsModule
        from .run_dreamplace import is_dreamplace_available
    except Exception:
        return False

    if not is_dreamplace_available():
        return False

    try:
        return ECCToolsModule().has_dreamplace_db_io()
    except Exception:
        return False
