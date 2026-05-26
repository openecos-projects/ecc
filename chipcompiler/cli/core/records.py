def error_record(error: str, **fields) -> dict:
    record = {"kind": "error", "error": error}
    record.update(fields)
    return record
