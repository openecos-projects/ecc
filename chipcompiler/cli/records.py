from chipcompiler.cli.output import disclosure_cmd


def error_record(error: str, **fields) -> dict:
    record = {"kind": "error", "error": error}
    record.update(fields)
    return record


def missing_config_record(project: str | None = None) -> dict:
    return error_record(
        "missing_config",
        inspect_cmd=disclosure_cmd("ecc check", project),
    )


def corrupt_config_record(project: str | None = None) -> dict:
    return error_record(
        "invalid_config",
        inspect_cmd=disclosure_cmd("ecc check", project),
    )
