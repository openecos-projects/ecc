#!/usr/bin/env python


def is_eda_exist() -> bool:
    """
    Check if the KLayout tool is installed and accessible.
    """
    try:
        from klayout import lay  # noqa: F401 -- probe import to test availability

        return True
    except ImportError:
        return False
