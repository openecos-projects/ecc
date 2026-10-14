import os
import re
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path

from pydantic import ValidationError

from ecc_experience.files import canonical_bytes, case_identity, read_json, safe_child
from ecc_experience.knowledge.verify import verify_integrity
from ecc_experience.models import ExperienceCase, ExperienceError

CASE_ID_PATTERN = re.compile(r"case-[0-9a-f]{64}\Z")


class ExperienceStore:
    def __init__(self, directory: str | Path):
        requested = Path(directory).expanduser().absolute()
        if requested.is_symlink():
            raise ExperienceError("Store root must not be a symlink")
        self.root = requested.resolve()

    def case_directory(self, case_id: str) -> Path:
        if not CASE_ID_PATTERN.fullmatch(case_id):
            raise ExperienceError("Invalid case ID", code="experience_case_id_invalid")
        return safe_child(self.root, f"cases/{case_id}")

    def read(self, case_id: str) -> ExperienceCase:
        directory = self.case_directory(case_id)
        payload = read_json(safe_child(directory, "case.json"))
        try:
            case = ExperienceCase.model_validate(payload)
        except ValidationError as exc:
            raise ExperienceError(f"Invalid experience case: {case_id}") from exc
        if case.case_id != case_id or case_identity(case.model_dump()) != case_id:
            raise ExperienceError(f"Case identity mismatch: {case_id}")
        return case

    def list_ids(self) -> list[str]:
        directory = safe_child(self.root, "cases")
        if not directory.exists():
            if not self.root.is_dir():
                raise ExperienceError("Experience store does not exist")
            return []
        result = []
        for entry in sorted(directory.iterdir()):
            if (
                entry.is_symlink()
                or not CASE_ID_PATTERN.fullmatch(entry.name)
                or not entry.is_dir()
            ):
                raise ExperienceError(f"Invalid case directory: {entry.name}")
            result.append(entry.name)
        return result

    @contextmanager
    def _writer(self):
        self.root.mkdir(parents=True, exist_ok=True)
        lock = safe_child(self.root, ".write-lock")
        try:
            lock.mkdir()
        except FileExistsError as exc:
            raise ExperienceError(
                "Another collector holds the store lock; recover a stale lock only after "
                "confirming that its writer has stopped",
                code="experience_store_busy",
            ) from exc
        try:
            yield
        finally:
            lock.rmdir()

    def put(self, case: ExperienceCase, copies: dict[str, bytes]) -> str:
        payload = case.model_dump()
        if case_identity(payload) != case.case_id:
            raise ExperienceError("Invalid case identity")
        with self._writer():
            destination = self.case_directory(case.case_id)
            if destination.exists():
                existing = self.read(case.case_id)
                if any(item.status == "fail" for item in verify_integrity(existing, destination)):
                    raise ExperienceError("Existing case evidence is corrupt")
                return "already_present"
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = Path(tempfile.mkdtemp(prefix=".collect-", dir=self.root))
            try:
                for reference, content in copies.items():
                    target = safe_child(temporary, reference)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    self._write(target, content)
                self._write(temporary / "case.json", canonical_bytes(payload))
                if any(item.status == "fail" for item in verify_integrity(case, temporary)):
                    raise ExperienceError("Incomplete staged evidence")
                os.rename(temporary, destination)
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
        return "created"

    @staticmethod
    def _write(path: Path, content: bytes) -> None:
        with path.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
