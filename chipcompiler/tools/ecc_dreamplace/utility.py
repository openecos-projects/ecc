#!/usr/bin/env python
# -*- encoding: utf-8 -*-

import logging

from chipcompiler.tools.ecc.utility import is_eda_exist as is_ecc_exist

LOGGER = logging.getLogger(__name__)


def is_eda_exist() -> bool:
    # check ecc exist
    from chipcompiler.tools.ecc.utility import is_eda_exist as is_ecc_exist
    if not is_ecc_exist():
        LOGGER.warning("dreamplace: base ECC tool not found")
        return False
    
    # check ecc-dreamplace exist 
    try:
        from dreamplace.Params import Params
        from dreamplace.Placer import PlacementEngine
        return True
    except Exception:
        LOGGER.warning("dreamplace: failed to import module/run_dreamplace", exc_info=True)
        return False

    if not is_dreamplace_available():
        LOGGER.warning("dreamplace: is_dreamplace_available() returned False")
        return False

    try:
        result = ECCToolsModule().has_dreamplace_db_io()
        if not result:
            LOGGER.warning("dreamplace: ECC runtime lacks dreamplace DB I/O APIs")
        return result
    except Exception:
        LOGGER.warning("dreamplace: has_dreamplace_db_io() raised exception", exc_info=True)
        return False
