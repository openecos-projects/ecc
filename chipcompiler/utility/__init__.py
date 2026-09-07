from typing import TYPE_CHECKING

from .csv import csv_write
from .file import chmod_folder, file_digest, find_files
from .filelist import (
    get_filelist_info,
    parse_filelist,
    parse_incdir_directives,
    resolve_path,
    validate_filelist,
)
from .json import JsonReadError, dict_to_str, json_read, json_read_strict, json_write
from .log import (
    Logger,
    build_timestamped_log_file,
    create_logger,
    init_api_runtime_log,
    redirect_stdio_to_file,
    rotate_log_on_start,
)
from .util import track_process_memory

# Plot helpers pull in matplotlib (~1s import, font scan on cold cache), so
# they are re-exported lazily via PEP 562 instead of at package import time.
_PLOT_EXPORTS = frozenset(
    {"plot_bar_chart", "plot_csv_bar_chart", "plot_csv_map", "plot_csv_table", "plot_metrics"}
)

if TYPE_CHECKING:
    from .plot import (
        plot_bar_chart,
        plot_csv_bar_chart,
        plot_csv_map,
        plot_csv_table,
        plot_metrics,
    )


def __getattr__(name: str):
    if name in _PLOT_EXPORTS:
        from . import plot

        return getattr(plot, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "chmod_folder",
    "json_read",
    "json_read_strict",
    "JsonReadError",
    "json_write",
    "dict_to_str",
    "Logger",
    "create_logger",
    "build_timestamped_log_file",
    "rotate_log_on_start",
    "redirect_stdio_to_file",
    "init_api_runtime_log",
    "track_process_memory",
    "plot_csv_map",
    "plot_metrics",
    "plot_csv_table",
    "plot_csv_bar_chart",
    "plot_bar_chart",
    "parse_filelist",
    "resolve_path",
    "validate_filelist",
    "get_filelist_info",
    "csv_write",
    "parse_incdir_directives",
    "find_files",
    "file_digest",
]
