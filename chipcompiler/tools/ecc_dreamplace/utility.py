#!/usr/bin/env python

import logging
import sys
from pathlib import Path

LOGGER = logging.getLogger(__name__)


def ensure_dreamplace_import_path() -> Path | None:
    tool_dir = Path(__file__).resolve().parent
    fallback_root = tool_dir.parents[1] / "thirdparty" / "ecc-dreamplace"
    if not fallback_root.exists():
        return None

    fallback_root_str = str(fallback_root)
    if fallback_root_str not in sys.path:
        sys.path.insert(0, fallback_root_str)

    loaded = sys.modules.get("dreamplace")
    loaded_file = Path(getattr(loaded, "__file__", "")).resolve() if loaded is not None else None
    if loaded_file and fallback_root not in loaded_file.parents:
        for module_name in list(sys.modules):
            if module_name == "dreamplace" or module_name.startswith("dreamplace."):
                sys.modules.pop(module_name, None)

    return fallback_root


def is_eda_exist() -> bool:
    # check ecc exist
    from chipcompiler.tools.ecc.utility import is_eda_exist as is_ecc_exist

    if not is_ecc_exist():
        LOGGER.error("dreamplace: base ECC tool not found")
        return False

    ensure_dreamplace_import_path()

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
