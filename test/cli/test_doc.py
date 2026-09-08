import sys
from pathlib import Path

import pytest

from chipcompiler.cli import main as cli_main
from chipcompiler.cli.core import docs
from chipcompiler.cli.core.docs import guides_root


def test_guides_root_points_at_repository_docs_in_dev_mode():
    repo_docs = Path(__file__).parents[2] / "chipcompiler" / "docs"

    assert guides_root() == repo_docs
    assert (guides_root() / "ecc-cli-config.en.md").is_file()


def test_all_topics_resolve_in_both_languages():
    for topic in docs.GUIDE_STEMS:
        for lang in ("en", "cn"):
            text = docs.load_guide(topic, lang).decode("utf-8")
            assert text.startswith("# ")


def test_ug_guide_documents_the_doc_command_in_both_languages():
    for lang in ("en", "cn"):
        text = docs.load_guide("ug", lang).decode("utf-8")
        assert "## 1.5. doc" in text
        assert "ecc doc config" in text


def test_doc_config_plain_is_byte_identical_to_the_guide_file(capsysbinary):
    rc = cli_main.run(["doc", "config", "--plain"])

    out = capsysbinary.readouterr().out
    assert rc == 0
    assert out == (guides_root() / "ecc-cli-config.en.md").read_bytes()


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


def test_doc_chinese_language(capsys):
    rc = cli_main.run(["doc", "config", "--lang", "cn", "--plain"])

    out = capsys.readouterr().out
    assert rc == 0
    assert any("一" <= ch <= "鿿" for ch in out)


def test_doc_default_text_output_keeps_unicode_layout_without_ansi(capsys):
    rc = cli_main.run(["doc", "config"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "\x1b[" not in out
    assert "─" in out


def test_doc_pages_the_full_guide_when_stdout_is_a_tty(monkeypatch, capsys):
    import pydoc

    paged = []
    monkeypatch.setattr(pydoc, "pager", paged.append)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr("chipcompiler.cli.commands.doc.supports_color", lambda: False)

    rc = cli_main.run(["doc", "config"])

    assert rc == 0
    assert capsys.readouterr().out == ""
    assert len(paged) == 1
    assert "cts_ecc.json" in paged[0]
    assert "\x1b[" not in paged[0]


def test_doc_pager_keeps_styles_when_color_is_supported(monkeypatch, capsys):
    import pydoc

    paged = []
    monkeypatch.setattr(pydoc, "pager", paged.append)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr("chipcompiler.cli.commands.doc.supports_color", lambda: True)
    # Rich consults NO_COLOR and TERM independently of supports_color();
    # pin them so the styled path is hermetic.
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")

    rc = cli_main.run(["doc", "config"])

    assert rc == 0
    assert capsys.readouterr().out == ""
    assert len(paged) == 1
    assert "\x1b[" in paged[0]


def test_doc_pager_defaults_less_and_restores_the_environment(monkeypatch, capsys):
    import os
    import pydoc

    seen = []
    monkeypatch.setattr(pydoc, "pager", lambda text: seen.append(os.environ.get("LESS")))
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.delenv("LESS", raising=False)

    rc = cli_main.run(["doc", "config"])

    assert rc == 0
    assert seen == ["FRX"]
    assert "LESS" not in os.environ


@pytest.mark.parametrize(
    "argv",
    [
        ["doc", "bogus"],
        ["doc", "dev"],
        ["doc", "CONFIG"],
        ["doc"],
        ["doc", "config", "--lang", "jp"],
        ["doc", "config", "7"],
    ],
    ids=lambda argv: " ".join(argv),
)
def test_doc_invalid_arguments_exit_2(argv, capsys):
    rc = cli_main.run(argv)

    captured = capsys.readouterr()
    assert rc == 2
    assert captured.err
