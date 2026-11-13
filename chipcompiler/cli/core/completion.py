# pyright: strict
"""Shell completion candidates for CLI options."""


def complete_flow_step(incomplete: str) -> list[str]:
    """Canonical rtl2gds step names starting with *incomplete* (case-insensitive)."""
    from chipcompiler.rtl2gds import rtl2gds_step_names

    prefix = incomplete.casefold()
    return [name for name in rtl2gds_step_names() if name.casefold().startswith(prefix)]


def complete_inserted_step(incomplete: str) -> list[str]:
    """Insertable ``STEP@AFTER`` names starting with *incomplete* (case-insensitive)."""
    from chipcompiler.data import StepEnum
    from chipcompiler.rtl2gds import inserted_step_name, lec_insert_anchors

    prefix = incomplete.casefold()
    names = [inserted_step_name(StepEnum.LEC.value, anchor) for anchor in lec_insert_anchors()]
    return [name for name in names if name.casefold().startswith(prefix)]
