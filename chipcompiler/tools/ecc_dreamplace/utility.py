#!/usr/bin/env python
# -*- encoding: utf-8 -*-

import logging

LOGGER = logging.getLogger(__name__)


def is_eda_exist() -> bool:
    # check ecc exist
    from chipcompiler.tools.ecc.utility import is_eda_exist as is_ecc_exist
    if not is_ecc_exist():
        LOGGER.error("dreamplace: base ECC tool not found")
        return False

    # check ecc-dreamplace exist
    try:
        from dreamplace.Params import Params  # noqa: F401
        from dreamplace.Placer import PlacementEngine  # noqa: F401
        return True
    except ImportError as e:
        LOGGER.error("dreamplace: import failed — %s", e)
        return False
    except Exception:
        LOGGER.error("dreamplace: unexpected error during import", exc_info=True)
        return False
