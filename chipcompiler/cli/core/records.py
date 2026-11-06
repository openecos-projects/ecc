def error_record(error: str, **fields) -> dict:
    record = {"kind": "error", "error": error}
    record.update(fields)
    return record


def warning_record(warning: str, **fields) -> dict:
    record = {"kind": "warning", "warning": warning}
    record.update(fields)
    return record


# Every kind that workspace selection records in CommandContext.manifest_error:
# build_context and _resolve_manifest_workspace (core/invocation.py) and the
# explicit-path checks (project/workspace_location.py).
SELECTION_ERROR_KINDS = frozenset(
    {
        "manifest_invalid",
        "workspace_required",
        "workspace_not_declared",
        "invalid_workspace",
        "workspace_id_conflict",
        "workspace_path_conflict",
        "workspace_path_invalid_id",
        "workspace_path_not_absolute",
        "workspace_path_unsafe",
    }
)


def manifest_error_record(manifest_error: str | None, **fields) -> dict:
    """Error record for a manifest selector failure, preserving the kind.

    The manifest_error text carries a "kind: reason" prefix; unknown kinds
    fall back to workspace_not_declared.
    """
    prefix, _, _ = (manifest_error or "").partition(":")
    kind = prefix if prefix in SELECTION_ERROR_KINDS else "workspace_not_declared"
    return error_record(kind, reason=manifest_error, **fields)


def legacy_workspace_error_record() -> dict:
    """Error for the removed runs/ layout; users must create a new workspace."""
    return error_record(
        "legacy_workspace_unsupported",
        reason="the legacy runs/ layout is not supported; create a new project and workspace",
    )
