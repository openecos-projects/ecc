import sys
from pathlib import Path

import pytest

from chipcompiler.cli import main as cli_main
from chipcompiler.cli.core import docs
from chipcompiler.cli.core.docs import guides_root


def test_guides_root_points_at_repository_docs_in_dev_mode():
    repo_docs = Path(__file__).parents[2] / "docs"

    assert guides_root() == repo_docs
    assert (guides_root() / "ecc-cli-config.en.md").is_file()


def test_all_four_topics_resolve_in_both_languages():
    for topic in docs.GUIDE_STEMS:
        for lang in ("en", "cn"):
            text = docs.load_guide(topic, lang).decode("utf-8")
            assert text.startswith("# ")


def test_doc_config_plain_is_byte_identical_to_the_guide_file(capsysbinary):
    rc = cli_main.run(["doc", "config", "--plain"])

    out = capsysbinary.readouterr().out
    assert rc == 0
    assert out == (guides_root() / "ecc-cli-config.en.md").read_bytes()


def test_doc_config_section_plain_output_is_byte_exact(capsysbinary):
    rc = cli_main.run(["doc", "config", "7", "--plain"])

    out = capsysbinary.readouterr().out
    assert rc == 0
    assert out in (guides_root() / "ecc-cli-config.en.md").read_bytes()


def test_doc_plain_preserves_crlf_line_endings(tmp_path, monkeypatch, capsysbinary):
    guide = tmp_path / "docs" / "ecc-cli-config.en.md"
    guide.parent.mkdir()
    guide.write_bytes(b"# Packaged guide\r\n\r\ntext\r\n")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    rc = cli_main.run(["doc", "config", "--plain"])

    out = capsysbinary.readouterr().out
    assert rc == 0
    assert out == b"# Packaged guide\r\n\r\ntext\r\n"


def test_rendered_output_survives_non_utf8_stdout_via_plain_fallback(tmp_path, monkeypatch, capsys):
    import io

    guide = tmp_path / "docs" / "ecc-cli-config.en.md"
    guide.parent.mkdir()
    guide.write_bytes("# Packaged guide\n\ntext with ünïcode\n".encode())
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    ascii_stdout = io.TextIOWrapper(io.BytesIO(), encoding="ascii")
    monkeypatch.setattr(sys, "stdout", ascii_stdout)

    rc = cli_main.run(["doc", "config", "--plain"])
    assert rc == 0

    rc = cli_main.run(["doc", "config"])
    captured = capsys.readouterr()
    assert rc == 1
    assert "Error:" in captured.err


def test_doc_uses_packaged_docs_when_frozen(tmp_path, monkeypatch, capsys):
    guide = tmp_path / "docs" / "ecc-cli-config.en.md"
    guide.parent.mkdir()
    guide.write_text("# Packaged guide\n", encoding="utf-8")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    rc = cli_main.run(["doc", "config", "--plain"])

    out = capsys.readouterr().out
    assert rc == 0
    assert out == "# Packaged guide\n"


def test_missing_guide_resource_fails_with_exit_1(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    rc = cli_main.run(["doc", "config", "--plain"])

    captured = capsys.readouterr()
    assert rc == 1
    assert "Error: doc resource not found: ecc-cli-config.en.md" in captured.err


def test_doc_section_slice_selects_exactly_one_section(capsys):
    rc = cli_main.run(["doc", "config", "7", "--plain"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "cts_ecc.json" in out
    assert out.startswith("## 7.")
    assert "## 8." not in out


def test_doc_section_tokens_match_exactly(capsys):
    rc = cli_main.run(["doc", "ug", "8", "--plain"])

    out = capsys.readouterr().out
    assert rc == 0
    assert out.startswith("## 8. config")
    assert "## 8.5." not in out

    rc = cli_main.run(["doc", "ug", "8.5", "--plain"])

    out = capsys.readouterr().out
    assert rc == 0
    assert out.startswith("## 8.5.")


def test_doc_unknown_section_lists_available_tokens(capsys):
    rc = cli_main.run(["doc", "config", "99"])

    captured = capsys.readouterr()
    assert rc == 1
    assert "no section 99" in captured.err
    for token in ("0", "7", "16"):
        assert token in captured.err


def test_doc_without_section_shows_the_full_guide(capsys):
    rc = cli_main.run(["doc", "tutorial", "1", "--plain"])

    out = capsys.readouterr().out
    assert rc == 0
    assert out.startswith("## 1.")


def test_doc_chinese_language(capsys):
    rc = cli_main.run(["doc", "config", "--lang", "cn", "--plain"])

    out = capsys.readouterr().out
    assert rc == 0
    assert any("\u4e00" <= ch <= "\u9fff" for ch in out)


def test_doc_default_text_output_keeps_unicode_layout_without_ansi(capsys):
    rc = cli_main.run(["doc", "config", "1"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "\x1b[" not in out
    assert "\u2500" in out


@pytest.mark.parametrize(
    "argv",
    [
        ["doc", "bogus"],
        ["doc", "CONFIG"],
        ["doc"],
        ["doc", "config", "--lang", "jp"],
    ],
    ids=lambda argv: " ".join(argv),
)
def test_doc_invalid_arguments_exit_2(argv, capsys):
    rc = cli_main.run(argv)

    captured = capsys.readouterr()
    assert rc == 2
    assert captured.err
