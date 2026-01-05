#!/usr/bin/env python
# -*- encoding: utf-8 -*-

def is_eda_exist() -> bool:
    """
    Check if the iEDA tool is installed and accessible.
    """          
    try:
        # from chipcompiler.tools.iEDA.bin import ieda_py
        from chipcompiler.thirdparty.iEDA.bin import ieda_py    
        return True
    except ImportError:
        return False
