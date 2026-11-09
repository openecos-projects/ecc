# pyright: strict
"""Shell completion candidates for CLI options."""


def complete_flow_step(incomplete: str) -> list[str]:
    """Canonical rtl2gds step names starting with *incomplete* (case-insensitive)."""
    from chipcompiler.rtl2gds import rtl2gds_step_names

    prefix = incomplete.casefold()
    return [name for name in rtl2gds_step_names() if name.casefold().startswith(prefix)]
