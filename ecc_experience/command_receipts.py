"""Immutable command requests and bounded, identity-bound completion receipts."""

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from ecc_experience.files import canonical_bytes, digest, read_json, safe_child
from ecc_experience.models import ExperienceError

_LIMIT = 1024 * 1024
_COMMANDS = {
    ("init",),
    ("run",),
    ("status",),
    ("workspace", "import"),
    ("workspace", "derive"),
    ("param", "apply"),
    ("signoff", "check"),
}


@dataclass(frozen=True)
class CommandRequest:
    path: Path
    receipt: Path
    fingerprint: str
    arguments: list[str]

    def metadata(self) -> dict:
        return {
            "request": str(self.path),
            "receipt": str(self.receipt),
            "request_fingerprint": self.fingerprint,
        }


def prepare_request(prefix: Path, arguments: list[str]) -> CommandRequest:
    request = prefix.with_suffix(".request.json")
    payload = {
        "schema_version": 1,
        "kind": "ecc-experience-command-request",
        "token": uuid4().hex,
        "arguments": arguments,
        "receipt": prefix.with_suffix(".receipt.json").name,
    }
    content = canonical_bytes(payload)
    if len(content) > _LIMIT:
        raise ExperienceError("Command request is oversized")
    with request.open("xb") as stream:
        stream.write(content)
    return load_request(request)


def load_request(path: Path) -> CommandRequest:
    if path.is_symlink():
        raise ExperienceError("Command request must not be a symlink")
    payload = read_json(path, _LIMIT)
    arguments = payload.get("arguments")
    if (
        payload.get("schema_version") != 1
        or payload.get("kind") != "ecc-experience-command-request"
        or not isinstance(payload.get("token"), str)
        or len(payload["token"]) != 32
        or not isinstance(arguments, list)
        or not arguments
        or not all(isinstance(item, str) and "\0" not in item for item in arguments)
        or not any(tuple(arguments[: len(command)]) == command for command in _COMMANDS)
        or payload.get("receipt") != path.name.removesuffix(".request.json") + ".receipt.json"
    ):
        raise ExperienceError("Invalid command request", code="experience_command_receipt_invalid")
    return CommandRequest(
        path, safe_child(path.parent, payload["receipt"]), digest(payload), arguments
    )


def read_receipt(request: CommandRequest, expected_fingerprint: str) -> dict | None:
    if request.fingerprint != expected_fingerprint:
        raise ExperienceError("Command request changed", code="experience_source_changed")
    if not request.receipt.exists():
        return None
    receipt = read_json(safe_child(request.path.parent, request.receipt.name), _LIMIT)
    if (
        receipt.get("schema_version") != 1
        or receipt.get("kind") != "ecc-experience-command-receipt"
        or receipt.get("request_fingerprint") != expected_fingerprint
        or receipt.get("status") not in {"running", "complete"}
        or type(receipt.get("process_tree_quiescent")) is not bool
        or (receipt["status"] == "complete" and type(receipt.get("exit_code")) is not int)
    ):
        raise ExperienceError("Invalid command receipt", code="experience_command_receipt_invalid")
    return receipt
