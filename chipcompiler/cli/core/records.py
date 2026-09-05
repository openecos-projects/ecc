def error_record(error: str, **fields) -> dict:
    record = {"kind": "error", "error": error}
    record.update(fields)
    return record


def warning_record(warning: str, **fields) -> dict:
    record = {"kind": "warning", "warning": warning}
    record.update(fields)
    return record


def manifest_error_record(manifest_error: str, **fields) -> dict:
    """Error record for a manifest selector failure, preserving the kind.

    The manifest_error text carries a "kind: reason" prefix; unknown kinds
    fall back to workspace_not_declared.
    """
    prefix, _, _ = (manifest_error or "").partition(":")
    kind = (
        prefix
        if prefix in ("manifest_invalid", "workspace_not_declared", "invalid_workspace")
        else "workspace_not_declared"
    )
    return error_record(kind, reason=manifest_error, **fields)


def legacy_layout_hint_record(project: str | None) -> dict:
    """Hint record for pre-migration runs/ projects (discloses ecc migrate)."""
    return warning_record(
        "legacy_layout_detected",
        reason="this project uses the legacy runs/ layout; run 'ecc migrate' to upgrade",
        migrate="ecc migrate --yes"
        if project is None
        else f"ecc migrate --project {project} --yes",
    )
