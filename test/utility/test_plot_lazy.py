"""Regression tests: matplotlib must stay off the CLI/package import path.

chipcompiler.utility re-exports the plot helpers lazily (PEP 562) so that
importing the package — and therefore every ecc command — does not pay for
matplotlib's import or its cold-cache fc-list font scan.
"""

import os
import subprocess
import sys
from pathlib import Path


def _run_fresh(code: str, tmp_path: Path) -> subprocess.CompletedProcess:
    env = os.environ | {"MPLCONFIGDIR": str(tmp_path / "mplconfig")}
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )


def test_utility_import_does_not_load_matplotlib(tmp_path):
    result = _run_fresh(
        "import sys, chipcompiler.utility; print('matplotlib' in sys.modules)", tmp_path
    )
    assert result.stdout.strip() == "False"


def test_cli_help_does_not_load_matplotlib(tmp_path):
    result = _run_fresh(
        "import sys; from chipcompiler.cli.main import run; "
        "rc = run(['--help']); "
        "print(rc, 'matplotlib' in sys.modules)",
        tmp_path,
    )
    assert result.stdout.strip().splitlines()[-1] == "0 False"


def test_ecc_tools_probe_import_does_not_load_matplotlib(tmp_path):
    # ecc doctor imports chipcompiler.tools.ecc.utility on a non-plot path.
    result = _run_fresh(
        "import sys; from chipcompiler.tools.ecc.utility import is_eda_exist; "
        "print('matplotlib' in sys.modules)",
        tmp_path,
    )
    assert result.stdout.strip() == "False"


def test_plot_exports_resolve_lazily(tmp_path):
    result = _run_fresh(
        "import sys, chipcompiler.utility as u; "
        "names = ['plot_bar_chart', 'plot_csv_bar_chart', 'plot_csv_map', "
        "'plot_csv_table', 'plot_metrics']; "
        "funcs = [getattr(u, n) for n in names]; "
        "print(all(callable(f) for f in funcs), 'matplotlib' in sys.modules)",
        tmp_path,
    )
    assert result.stdout.strip() == "True True"


def test_ecc_tools_plot_export_resolves_lazily(tmp_path):
    result = _run_fresh(
        "import sys; from chipcompiler.tools.ecc import ECCToolsPlot; "
        "print(callable(ECCToolsPlot), 'matplotlib' in sys.modules)",
        tmp_path,
    )
    assert result.stdout.strip() == "True True"


def test_unknown_attribute_still_raises(tmp_path):
    result = _run_fresh(
        "import chipcompiler.utility as u\n"
        "try:\n"
        "    u.no_such_name\n"
        "except AttributeError:\n"
        "    print('AttributeError')\n",
        tmp_path,
    )
    assert result.stdout.strip() == "AttributeError"


def test_plot_exports_stay_discoverable(tmp_path):
    result = _run_fresh(
        "import chipcompiler.utility as u; "
        "print(all(n in dir(u) and n in u.__all__ for n in "
        "['plot_bar_chart', 'plot_csv_bar_chart', 'plot_csv_map', "
        "'plot_csv_table', 'plot_metrics']))",
        tmp_path,
    )
    assert result.stdout.strip() == "True"
