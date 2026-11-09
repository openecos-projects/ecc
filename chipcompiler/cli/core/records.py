def error_record(error: str, **fields: object) -> dict[str, object]:
    record: dict[str, object] = {"kind": "error", "error": error}
    record.update(fields)
    return record


def warning_record(warning: str, **fields: object) -> dict[str, object]:
    record: dict[str, object] = {"kind": "warning", "warning": warning}
    record.update(fields)
    return record


def manifest_error_record(manifest_error: str, **fields: object) -> dict[str, object]:
    """Error record for a manifest selector failure, preserving the kind.

    The manifest_error text carries a "kind: reason" prefix; unknown kinds
    fall back to workspace_not_declared.
    """
    prefix, _, _ = (manifest_error or "").partition(":")
    kind = (
        prefix
        if prefix
        in (
            "manifest_invalid",
            "workspace_required",
            "workspace_not_declared",
            "invalid_workspace",
        )
        else "workspace_not_declared"
    )
    return error_record(kind, reason=manifest_error, **fields)


def legacy_workspace_error_record() -> dict:
    """Error for the removed runs/ layout; users must create a new workspace."""
    return error_record(
        "legacy_workspace_unsupported",
        reason="the legacy runs/ layout is not supported; create a new project and workspace",
    )
