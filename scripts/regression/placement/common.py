"""Artifact paths and serialization shared by preparation, execution and auditing."""

import ast
import gzip
import hashlib
import json
import tempfile
from pathlib import Path


def read(path: Path):
    return json.loads(path.read_text())


def write_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(text)
    temporary.replace(path)


def write(path: Path, value):
    write_text(path, json.dumps(value, indent=2) + "\n")


def digest(path: Path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def grid(path: Path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt") as stream:
        return [line.strip() for line in stream if line.startswith(("TRACKS ", "GCELLGRID "))]


def content_digest(path: Path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def cases(batch: Path):
    return read(batch / "cases_manifest.json")["cases"]


def workspace(batch: Path, name: str):
    project = read(batch / "projects" / name / "project.json")
    return Path(project["workspaces"][-1]["workspace_path"])


def effective_parameters(log: Path):
    with log.open(errors="replace") as stream:
        for line in stream:
            if "parameters = " in line:
                return json.loads(json.dumps(ast.literal_eval(line.split("parameters = ", 1)[1])))
    raise ValueError(f"Missing effective parameters: {log}")


def require(condition, message: str):
    if not condition:
        raise ValueError(message)
