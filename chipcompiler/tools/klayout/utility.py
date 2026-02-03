#!/usr/bin/env python


def is_eda_exist() -> bool:
    """Check if the KLayout tool is installed and accessible."""
    import importlib.util

    return importlib.util.find_spec("klayout") is not None
