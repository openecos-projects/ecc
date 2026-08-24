def error_record(error: str, **fields) -> dict:
    record = {"kind": "error", "error": error}
    record.update(fields)
    return record


def warning_record(warning: str, **fields) -> dict:
    record = {"kind": "warning", "warning": warning}
    record.update(fields)
    return record


def legacy_layout_hint_record(project: str | None) -> dict:
    """Hint record for pre-migration runs/ projects (discloses ecc migrate)."""
    return warning_record(
        "legacy_layout_detected",
        reason="this project uses the legacy runs/ layout; run 'ecc migrate' to upgrade",
        migrate="ecc migrate --yes"
        if project is None
        else f"ecc migrate --project {project} --yes",
    )
