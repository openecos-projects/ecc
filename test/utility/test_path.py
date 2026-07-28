from pathlib import Path

from chipcompiler.utility.path import (
    optional_path,
    path_is_within,
    path_list,
    path_text,
    path_texts,
    stringify_paths,
)


def test_stringify_paths_converts_nested_path_values():
    data = {
        "path": Path("/tmp/workspace"),
        "items": [Path("/tmp/a"), {"child": Path("/tmp/b")}],
        "text": "keep",
        "none": None,
    }

    assert stringify_paths(data) == {
        "path": "/tmp/workspace",
        "items": ["/tmp/a", {"child": "/tmp/b"}],
        "text": "keep",
        "none": None,
    }


def test_path_text_converts_optional_path_values():
    assert path_text(None) == ""
    assert path_text(Path("/tmp/workspace")) == "/tmp/workspace"
    assert path_text("relative/file.v") == "relative/file.v"


def test_path_texts_filters_none_and_converts_paths():
    assert path_texts([Path("/tmp/a"), None, "b"]) == ["/tmp/a", "b"]


def test_optional_path_converts_non_empty_values_to_paths():
    assert optional_path(None) is None
    assert optional_path("") is None
    assert optional_path("relative/file.v") == Path("relative/file.v")
    assert optional_path(Path("/tmp/workspace")) == Path("/tmp/workspace")


def test_path_list_filters_empty_values_and_converts_to_paths():
    assert path_list(["a.lef", "", None, Path("b.lef")]) == [
        Path("a.lef"),
        Path("b.lef"),
    ]


def test_path_is_within_accepts_nested_paths_and_rejects_escapes(tmp_path):
    root = tmp_path / "workspace"
    child = root / "step" / "output"
    sibling = tmp_path / "outside"
    child.mkdir(parents=True)
    sibling.mkdir()

    assert path_is_within(child, root)
    assert not path_is_within(sibling, root)
