import concurrent.futures
import multiprocessing
import os
from collections.abc import Callable

from tqdm import tqdm

from chipcompiler.utility import plot_csv_map

MAX_PLOT_WORKERS = 4


def plot_array_maps(input_paths: list[str], warn: Callable[[str], None]) -> None:
    valid_paths = [
        path
        for path in input_paths
        if path and os.path.exists(path) and path.lower().endswith(".csv")
    ]
    if not valid_paths:
        warn("No valid CSV files found for plotting.")
        return
    with concurrent.futures.ProcessPoolExecutor(
        max_workers=min(MAX_PLOT_WORKERS, len(valid_paths)),
        mp_context=multiprocessing.get_context("spawn"),
    ) as executor:
        for _ in tqdm(
            executor.map(plot_csv_map, valid_paths),
            total=len(valid_paths),
            desc="Plotting array maps",
            unit="file",
        ):
            pass
