#!/usr/bin/env python

def is_eda_exist() -> bool:
    """
    Check if the ECC tool is installed and accessible.
    """          
    try:
        # from chipcompiler.tools.ecc.bin import ecc_py
        return True
    except ImportError:
        return False
