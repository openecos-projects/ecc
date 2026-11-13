"""The files an RTL file or filelist makes the front end read (an RTL proof's identity)."""

import pytest

from chipcompiler.utility.rtl_inputs import include_targets, rtl_input_files


def _tree(root, files):
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text)


def test_every_file_a_filelist_reads_is_listed(tmp_path):
    _tree(
        tmp_path,
        {
            "src/top.sv": '`include "local.svh"\n`include "c.vh"\nmodule top; endmodule\n',
            "src/local.svh": "",
            "inc1/a.vh": "",
            "inc 2/b.vh": "",
            "inc3/c.vh": '`include "deep.vh"\n',
            "inc3/deep.vh": "",
            "ip/ip.f": "core.sv\n",
            "ip/core.sv": "",
            "abs dir/abs.f": "abs.sv\n",
            "abs dir/abs.sv": "",
            "design.f": (
                "// sources\n"
                "\n"
                f'+incdir+inc1+"{tmp_path / "inc 2"}"\n'
                "-I inc3  # nested headers\n"
                "+define+SYNTHESIS\n"
                '"src/top.sv"\n'
                "-F\tip/ip.f\n"
                f'-F"{tmp_path / "abs dir" / "abs.f"}"\n'
            ),
        },
    )

    assert rtl_input_files(str(tmp_path / "design.f"), filelist=True) == [
        str(tmp_path / name)
        for name in (
            "design.f",
            "src/top.sv",
            # A nested filelist resolves its entries against its own directory.
            "ip/ip.f",
            "ip/core.sv",
            "abs dir/abs.f",
            "abs dir/abs.sv",
            "inc1/a.vh",
            "inc 2/b.vh",
            "inc3/c.vh",
            "inc3/deep.vh",
            # Includes found beside the including file.
            "src/local.svh",
        )
    ]


def test_every_entry_of_a_filelist_line_is_read(tmp_path):
    _tree(
        tmp_path,
        {
            "inc#defs/a.vh": "",
            "empty/.keep": "",
            "inc/b.vh": "",
            "eq/c.vh": "",
            "x.sv": "",
            "y y.sv": "",
            "design.f": (
                # A quoted path keeps its "#"; an unquoted one starts a comment.
                f'+incdir+"{tmp_path / "inc#defs"}"  # comment\n'
                f'-I "{tmp_path / "empty"}" -I"{tmp_path / "inc"}" -I={tmp_path / "eq"}\n'
                'x.sv "y y.sv" // two sources\n'
                "+define+SYNTHESIS+WIDTH=8\n"
            ),
        },
    )

    assert rtl_input_files(str(tmp_path / "design.f"), filelist=True) == [
        str(tmp_path / name)
        for name in (
            "design.f",
            "x.sv",
            "y y.sv",
            "inc#defs/a.vh",
            "empty/.keep",
            "inc/b.vh",
            "eq/c.vh",
        )
    ]


def test_an_rtl_file_brings_its_includes(tmp_path):
    _tree(tmp_path, {"hdr/defs.svh": '`include "more.svh"\n', "hdr/more.svh": ""})
    (tmp_path / "top.v").write_text(
        f'`include "{tmp_path / "hdr" / "defs.svh"}"\n'
        '// `include "commented.svh" is no directive\n'
        '`include "nowhere.svh"\n'
    )

    assert rtl_input_files(str(tmp_path / "top.v"), filelist=False) == [
        str(tmp_path / name) for name in ("top.v", "hdr/defs.svh", "hdr/more.svh")
    ]


def test_an_include_brings_every_file_it_may_name(tmp_path):
    # slang reads <defs.vh> from --isystem only, a quoted name beside the
    # includer first: every candidate is followed, whichever the reader picks.
    _tree(
        tmp_path,
        {
            "rtl.f": "--isystem inc\nsrc/top.sv\n",
            "src/top.sv": "`include <defs.vh>\n",
            "src/defs.vh": "",
            "inc/defs.vh": '`include "../outside/value.vh"\n',
            "outside/value.vh": "",
        },
    )

    assert rtl_input_files(str(tmp_path / "rtl.f"), filelist=True) == [
        str(tmp_path / name)
        for name in ("rtl.f", "src/top.sv", "inc/defs.vh", "src/defs.vh", "outside/value.vh")
    ]


def test_a_symbolic_link_resolves_from_the_file_it_names(tmp_path):
    # kepler-formal resolves a relative include, and a filelist's relative
    # entries, from the real file a symbolic link names; the decoys beside
    # the links are never read.
    _tree(
        tmp_path,
        {
            "ip/entry.vh": '`include "defs.vh"\n',
            "ip/defs.vh": "",
            "ip/design.f": "+incdir+inc\ncore.sv\n",
            "ip/core.sv": '`include "cfg.vh"\n',
            "ip/inc/cfg.vh": "",
            "links/defs.vh": "",
            "links/core.sv": "",
            "links/inc/cfg.vh": "",
        },
    )
    (tmp_path / "links/entry.vh").symlink_to("../ip/entry.vh")
    (tmp_path / "links/design.f").symlink_to("../ip/design.f")
    (tmp_path / "top.sv").write_text(f'`include "{tmp_path / "links/entry.vh"}"\n')

    # Every file is listed where it really is.
    assert rtl_input_files(str(tmp_path / "top.sv"), filelist=False) == [
        str(tmp_path / name) for name in ("top.sv", "ip/entry.vh", "ip/defs.vh")
    ]
    assert rtl_input_files(str(tmp_path / "links/design.f"), filelist=True) == [
        str(tmp_path / name) for name in ("ip/design.f", "ip/core.sv", "ip/inc/cfg.vh")
    ]


def test_dot_dot_after_a_symbolic_link_leaves_the_links_target(tmp_path):
    # link -> real/sub, so link/.. is real, not the directory holding the link.
    _tree(
        tmp_path,
        {
            "real/sub/.keep": "",
            "real/defs.vh": "",
            "real/inc/cfg.vh": "",
            "defs.vh": "",
            "inc/cfg.vh": "",
            "top.sv": '`include "link/../defs.vh"\n',
            "design.f": "+incdir+link/../inc\n",
        },
    )
    (tmp_path / "link").symlink_to("real/sub")

    assert rtl_input_files(str(tmp_path / "top.sv"), filelist=False) == [
        str(tmp_path / name) for name in ("top.sv", "real/defs.vh")
    ]
    assert rtl_input_files(str(tmp_path / "design.f"), filelist=True) == [
        str(tmp_path / name) for name in ("design.f", "real/inc/cfg.vh")
    ]


def test_include_directives_are_read_around_comments_and_strings():
    text = (
        '/* configuration */ `include "a.svh"\n'
        '// `include "commented.svh"\n'
        '/* `include "in_block.svh" */\n'
        'initial $display("`include \\"in_string.svh\\"");\n'
        "`define X 1 `include <b.svh>\n"
        "`include_guard_macro\n"
        '`include /* why */ "c.svh"\n'
        '`include\f"d.svh"\n'
        # An escaped identifier may hold a quote or a comment marker.
        'wire \\"escaped ; wire \\//x ; `include "e.svh"\n'
    )

    assert include_targets(text, "top.sv") == ["a.svh", "b.svh", "c.svh", "d.svh", "e.svh"]


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("design.f", "top.sv\n-f lists/ip.f\n"),
        ("design.f", "top.sv\n-flists/ip.f\n"),
        ("design.f", "top.sv\n-v lib.v\n"),
        ("design.f", "top.sv\n-y libdir\n"),
        ("design.f", "top.sv\n--libdir=libdir\n"),
        # Any other option may read files, alone on its line or not.
        ("design.f", "top.sv\n--libmap=lib.map\n"),
        ("design.f", "top.sv\n--compat-mode\n"),
        ("design.f", "--top gcd\n"),
        ("design.f", "top.sv\n+libext+.v\n"),
        ("design.f", 'top.sv\n-I"unterminated\n'),
        ("design.f", "top.sv\n-I\n"),
        # The front end expands environment variables in paths.
        ("design.f", "+incdir+$INC\ntop.sv\n"),
        ("design.f", "${SRC}/top.sv\n"),
        ("design.f", "top.sv\n-I $(INC)\n"),
        ("top.sv", "`include defs.vh\n"),
        ("top.sv", '`include "defs.vh\n'),
        ("top.sv", "`include `HEADER\n"),
    ],
)
def test_inputs_that_cannot_be_placed_are_rejected(tmp_path, name, text):
    (tmp_path / "top.sv").write_text("module top; endmodule\n")
    (tmp_path / name).write_text(text)

    with pytest.raises(ValueError):
        rtl_input_files(str(tmp_path / name), filelist=name == "design.f")
