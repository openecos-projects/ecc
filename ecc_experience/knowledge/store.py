import os
import re
import shutil
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from pydantic import ValidationError

from ecc_experience.files import canonical_bytes, case_identity, read_json, safe_child
from ecc_experience.knowledge.verify import verify_integrity
from ecc_experience.models import CaseContents, ExperienceCase, ExperienceError

try:
    import fcntl
except ImportError:  # pragma: no cover - ECC runtime is POSIX-only.
    fcntl = None

CASE_ID_PATTERN = re.compile(r"case-[0-9a-f]{64}\Z")
STORE_LOCK_TIMEOUT_SECONDS = 60.0
STORE_LOCK_POLL_SECONDS = 0.05


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
        directory_fd = None
        try:
            if fcntl is not None:
                directory_fd = os.open(self.root, os.O_RDONLY)
                deadline = time.monotonic() + STORE_LOCK_TIMEOUT_SECONDS
                while True:
                    try:
                        fcntl.flock(directory_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError as exc:
                        if time.monotonic() >= deadline:
                            raise ExperienceError(
                                "Another collector holds the store lock; recover a stale lock "
                                "only after confirming that its writer has stopped",
                                code="experience_store_busy",
                            ) from exc
                        time.sleep(STORE_LOCK_POLL_SECONDS)
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
        finally:
            if directory_fd is not None:
                if fcntl is not None:
                    fcntl.flock(directory_fd, fcntl.LOCK_UN)
                os.close(directory_fd)

    def put(self, case: ExperienceCase, copies: dict[str, bytes]) -> str:
        return self.put_many([CaseContents(case, copies)])[case.case_id]

    def put_many(
        self, entries: list[CaseContents], *, release: dict | None = None
    ) -> dict[str, str]:
        identifiers = [entry.case.case_id for entry in entries]
        if len(set(identifiers)) != len(identifiers):
            raise ExperienceError("Duplicate cases in store transaction")
        with self._writer():
            safe_child(self.root, "cases").mkdir(parents=True, exist_ok=True)
            temporary = Path(tempfile.mkdtemp(prefix=".collect-", dir=self.root))
            statuses: dict[str, str] = {}
            pending: list[tuple[Path, Path]] = []
            published: list[Path] = []
            try:
                for entry in entries:
                    case = entry.case
                    if case_identity(case.model_dump()) != case.case_id:
                        raise ExperienceError("Invalid case identity")
                    destination = self.case_directory(case.case_id)
                    if destination.exists():
                        existing = self.read(case.case_id)
                        if any(
                            item.status == "fail"
                            for item in verify_integrity(existing, destination)
                        ):
                            raise ExperienceError(
                                "Existing case evidence is corrupt",
                                code="experience_case_conflict",
                            )
                        statuses[case.case_id] = "already_present"
                        continue
                    staged = temporary / case.case_id
                    staged.mkdir()
                    for reference, content in entry.copies.items():
                        target = safe_child(staged, reference)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        self._write(target, content)
                    self._write(staged / "case.json", canonical_bytes(case.model_dump()))
                    if any(item.status == "fail" for item in verify_integrity(case, staged)):
                        raise ExperienceError("Incomplete staged evidence")
                    pending.append((staged, destination))
                    statuses[case.case_id] = "created"
                if release is not None:
                    release_id = release["release_id"]
                    if not re.fullmatch(r"release-[0-9a-f]{64}", release_id):
                        raise ExperienceError("Invalid release ID")
                    destination = safe_child(self.root, f"releases/{release_id}.json")
                    if destination.exists():
                        existing_release = read_json(destination)
                        if {
                            key: value
                            for key, value in existing_release.items()
                            if key != "created_at"
                        } != {key: value for key, value in release.items() if key != "created_at"}:
                            raise ExperienceError(
                                "Existing release contains different data",
                                code="experience_release_conflict",
                            )
                        statuses[release_id] = "already_present"
                    else:
                        staged = temporary / "release.json"
                        self._write(staged, canonical_bytes(release))
                        pending.append((staged, destination))
                        statuses[release_id] = "created"
                for staged, destination in pending:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    os.rename(staged, destination)
                    published.append(destination)
            except BaseException:
                for destination in reversed(published):
                    if destination.is_dir():
                        shutil.rmtree(destination)
                    else:
                        destination.unlink()
                raise
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
        return statuses

    @staticmethod
    def _write(path: Path, content: bytes) -> None:
        with path.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
