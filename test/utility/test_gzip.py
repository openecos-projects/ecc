import gzip

from chipcompiler.utility.gzip import read_text_maybe_gzip, write_text_maybe_gzip


def test_read_text_maybe_gzip_reads_plain_text(tmp_path):
    path = tmp_path / "netlist.v"
    path.write_text("module top; endmodule\n", encoding="utf-8")

    assert read_text_maybe_gzip(path) == "module top; endmodule\n"


def test_read_text_maybe_gzip_reads_gzip_text(tmp_path):
    path = tmp_path / "netlist.v.gz"
    with gzip.open(path, "wt", encoding="utf-8") as file:
        file.write("module top; endmodule\n")

    assert read_text_maybe_gzip(path) == "module top; endmodule\n"


def test_write_text_maybe_gzip_writes_gzip_text(tmp_path):
    path = tmp_path / "netlist.v.gz"

    write_text_maybe_gzip(path, "module top; endmodule\n")

    with gzip.open(path, "rt", encoding="utf-8") as file:
        assert file.read() == "module top; endmodule\n"


def test_read_text_plain_content_in_gz_named_file(tmp_path):
    # Some tools write plain text into a .gz-named file
    # (e.g. yosys built without zlib). The reader must fall back
    # to plain text instead of raising BadGzipFile.
    path = tmp_path / "netlist.v.gz"
    path.write_text("module top(); endmodule", encoding="utf-8")

    assert "module top" in read_text_maybe_gzip(path)
