from types import SimpleNamespace

from chipcompiler.tools.ecc import plot as ecc_plot


class _Executor:
    def __init__(self, *, max_workers, mp_context):
        self.max_workers = max_workers
        self.mp_context = mp_context

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def map(self, function, values):
        return [function(value) for value in values]


def test_plot_array_maps_uses_bounded_spawn_process_pool(tmp_path, monkeypatch):
    input_paths = []
    for index in range(5):
        path = tmp_path / f"map_{index}.csv"
        path.write_text("x,y,value\n0,0,1\n", encoding="utf-8")
        input_paths.append(str(path))

    calls = {}

    def make_executor(*, max_workers, mp_context):
        calls["executor"] = _Executor(
            max_workers=max_workers,
            mp_context=mp_context,
        )
        return calls["executor"]

    monkeypatch.setattr(
        ecc_plot.concurrent.futures,
        "ProcessPoolExecutor",
        make_executor,
    )
    monkeypatch.setattr(
        ecc_plot,
        "plot_csv_map",
        lambda path: calls.setdefault("paths", []).append(path),
    )
    monkeypatch.setattr(ecc_plot, "tqdm", lambda values, **_kwargs: values)

    plotter = ecc_plot.ECCToolsPlot(
        workspace=SimpleNamespace(logger=SimpleNamespace(warning=lambda _message: None)),
        step=None,
    )
    plotter.plot_array_maps(input_paths)

    assert calls["executor"].max_workers == ecc_plot.MAX_PLOT_WORKERS
    assert calls["executor"].mp_context.get_start_method() == "spawn"
    assert calls["paths"] == input_paths


def test_plot_array_maps_writes_png_for_each_valid_csv(tmp_path):
    input_paths = []
    for index in range(2):
        path = tmp_path / f"map_{index}.csv"
        path.write_text("0,1\n1,2\n3,4\n", encoding="utf-8")
        input_paths.append(str(path))

    plotter = ecc_plot.ECCToolsPlot(
        workspace=SimpleNamespace(logger=SimpleNamespace(warning=lambda _message: None)),
        step=None,
    )
    plotter.plot_array_maps(input_paths)

    assert {path.name for path in tmp_path.glob("*.png")} == {"map_0.png", "map_1.png"}
