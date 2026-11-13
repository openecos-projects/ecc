from types import SimpleNamespace

import pytest

from chipcompiler.tools.lec_result import lec_result_status, write_step_result


def _tree(root, files):
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text)


def _proven_result(tmp_path, golden, gate, *, golden_kind):
    result = tmp_path / "result.json"
    step = SimpleNamespace(
        input=SimpleNamespace(golden_verilog=golden, gate_verilog=gate),
        output=SimpleNamespace(json=result),
        report=SimpleNamespace(equiv_status=None, status=None),
    )
    write_step_result(step, proven=True, golden_kind=golden_kind)
    return result


@pytest.mark.parametrize(
    "edited",
    [
        "filelist",
        "src/top.sv",
        "src/local.svh",
        "inc/defs.svh",
        "inc/sub/more.svh",
        "ip/ip.f",
        "ip/core.sv",
        "outside/value.vh",
    ],
)
def test_editing_any_file_the_rtl_reads_makes_its_proof_stale(tmp_path, edited):
    _tree(
        tmp_path,
        {
            # top.sv includes a header beside it; inc/ holds the include directory.
            "src/top.sv": '`include "local.svh"\n`include <sys.vh>\nmodule top; endmodule\n',
            "src/local.svh": "`define L 1\n",
            "inc/defs.svh": "`define W 1\n",
            "inc/sub/more.svh": "`define V 1\n",
            # <sys.vh> is read from --isystem, not the decoy beside top.sv.
            "src/sys.vh": "`define VALUE 0\n",
            "sys/sys.vh": '`include "../outside/value.vh"\n',
            "outside/value.vh": "`define VALUE 0\n",
            # The nested filelist resolves its entries against its own directory.
            "ip/ip.f": "core.sv\n",
            "ip/core.sv": "module core; endmodule\n",
            "filelist": ("+incdir+inc\n--isystem sys\n\nsrc/top.sv\n-F\tip/ip.f  // the IP\n"),
            "gate.v": "module top; endmodule\n",
        },
    )
    golden, gate = tmp_path / "filelist", tmp_path / "gate.v"
    result = _proven_result(tmp_path, golden, gate, golden_kind="rtl_filelist")
    assert lec_result_status(result, golden_verilog=golden, gate_verilog=gate) == "proven"

    with (tmp_path / edited).open("a") as handle:
        handle.write("// edited\n")

    assert lec_result_status(result, golden_verilog=golden, gate_verilog=gate) == "stale"


@pytest.mark.parametrize(
    "prefix",
    ["", "/* configuration */ ", 'wire \\"escaped ; '],
    ids=["plain", "after a comment", "after an escaped identifier"],
)
def test_an_rtl_files_proof_follows_its_includes(tmp_path, prefix):
    _tree(tmp_path, {"hdr/defs.svh": "`define X 1\n", "gate.v": "module t; endmodule\n"})
    (tmp_path / "t.sv").write_text(
        f'{prefix}`include "{tmp_path / "hdr" / "defs.svh"}"\nmodule t; endmodule\n'
    )
    golden, gate = tmp_path / "t.sv", tmp_path / "gate.v"
    result = _proven_result(tmp_path, golden, gate, golden_kind="rtl")

    (tmp_path / "hdr" / "defs.svh").write_text("`define X 0\n")

    assert lec_result_status(result, golden_verilog=golden, gate_verilog=gate) == "stale"


@pytest.mark.parametrize(
    "include",
    ["{root}/links/entry.vh", "link/../defs.vh"],
    ids=["through a linked header", "dot-dot after a linked directory"],
)
def test_a_header_reached_through_a_symbolic_link_identifies_the_proof(tmp_path, include):
    _tree(
        tmp_path,
        {
            "ip/sub/.keep": "",
            "ip/entry.vh": '`include "defs.vh"\n',
            "ip/defs.vh": "`define MASK 1'b0\n",
            # A decoy beside the RTL: link/.. is ip, not the RTL's directory.
            "defs.vh": "`define MASK 1'b0\n",
            "gate.v": "module t; endmodule\n",
        },
    )
    (tmp_path / "links").mkdir()
    (tmp_path / "links/entry.vh").symlink_to("../ip/entry.vh")
    (tmp_path / "link").symlink_to("ip/sub")
    (tmp_path / "t.sv").write_text(f'`include "{include.format(root=tmp_path)}"\n')
    golden, gate = tmp_path / "t.sv", tmp_path / "gate.v"
    result = _proven_result(tmp_path, golden, gate, golden_kind="rtl")

    (tmp_path / "ip/defs.vh").write_text("`define MASK 1'b1\n")

    assert lec_result_status(result, golden_verilog=golden, gate_verilog=gate) == "stale"


@pytest.mark.parametrize(
    "option",
    # -f resolves against the reading tool's working directory; a library
    # map names sources of its own.
    ["-f ip.f", "--libmap=lib.map"],
)
def test_rtl_whose_inputs_cannot_be_identified_is_never_proven(tmp_path, option):
    _tree(
        tmp_path,
        {
            "ip.f": "ip.sv\n",
            "lib.map": "library work ip.sv;\n",
            "ip.sv": "module ip; endmodule\n",
            "design.f": f"{option}\n",
            "gate.v": "module ip; endmodule\n",
        },
    )
    golden, gate = tmp_path / "design.f", tmp_path / "gate.v"
    result = _proven_result(tmp_path, golden, gate, golden_kind="rtl_filelist")

    assert lec_result_status(result, golden_verilog=golden, gate_verilog=gate) == "stale"
