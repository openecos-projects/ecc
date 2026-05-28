import json
from collections.abc import Sequence

RESPONSES = {"success", "failed", "error", "warning"}


def workspace_response(
    cmd: str,
    response: str,
    data: dict | None = None,
    message: Sequence[str] | None = None,
) -> dict:
    return {
        "cmd": cmd,
        "response": response,
        "data": data or {},
        "message": list(message or []),
    }


def exit_code_for_response(response: str) -> int:
    return 0 if response in {"success", "warning"} else 1


def render_workspace_response(result: dict, json_output: bool) -> None:
    if json_output:
        print(json.dumps(result, ensure_ascii=False))
        return

    status = result.get("response", "")
    cmd = result.get("cmd", "")
    print(f"{cmd}: {status}")
    for message in result.get("message", []):
        print(message)
