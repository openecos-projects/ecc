#!/usr/bin/env python
import fcntl
from collections.abc import Callable
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path

from chipcompiler.utility import json_read, json_write

from .checklist import Checklist

home_json = {
    "parameters": "",
    "flow": "",
    "layout": "",
    "checklist": "",
    "metrics": {},
}


def _default_home_data() -> dict:
    return deepcopy(home_json)


def _normalize_home_data(data: dict) -> tuple[dict, bool]:
    normalized = _default_home_data()
    changed = not isinstance(data, dict)

    if isinstance(data, dict):
        for key, value in data.items():
            if key == "monitor":
                changed = True
                continue
            normalized[key] = value

    if not isinstance(normalized.get("metrics"), dict):
        normalized["metrics"] = {}
        changed = True

    for key in home_json:
        if key not in normalized:
            normalized[key] = _default_home_data()[key]
            changed = True

    if isinstance(data, dict) and normalized != data:
        changed = True

    return normalized, changed


def _read_normalized_home_data(path: Path) -> tuple[dict, bool]:
    return _normalize_home_data(json_read(path))


class HomeData:
    """
    Home data information
    """

    def __init__(self, path: Path | None = None):
        self.path: Path | None = Path(path) if path else None  # home data file path
        self.data: dict = {}  # home data

    def init(self, path: Path):
        self.path = Path(path)
        self.data: dict = {}

        if self.path.exists():
            self._repair_or_reload()
        else:
            self.reset()

    def reload(self):
        self._repair_or_reload()

    def reset(self):
        self._update(lambda data: data.clear() or data.update(_default_home_data()))

    def save(self):
        source = self.data
        self._update(lambda data: data.clear() or data.update(source), force=True)

    @contextmanager
    def _locked(self):
        path = self._path_required()
        lock_path = path.with_name(f"{path.name}.lock")
        with open(lock_path, "a") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _update(self, mutator: Callable[[dict], bool | None], *, force: bool = False) -> None:
        with self._locked():
            path = self._path_required()
            data, repaired = _read_normalized_home_data(path)
            before = deepcopy(data)
            mutated = mutator(data)
            data, normalized = _normalize_home_data(data)
            changed = force or repaired or normalized or mutated is True or data != before
            if changed:
                json_write(path, data)
            self.data = data

    def _repair_or_reload(self) -> None:
        self._update(lambda data: False)

    def _path_required(self) -> Path:
        if self.path is None:
            raise ValueError("home data path is not set")
        return self.path

    def _set_path_value(self, key: str, path: Path):
        path_text = str(path)

        def mutator(data: dict) -> bool:
            if data.get(key) == path_text:
                return False
            data[key] = path_text
            return True

        self._update(mutator)

    def set_parameters(self, path: Path):
        self._set_path_value("parameters", path)

    def set_flow(self, path: Path):
        self._set_path_value("flow", path)

    def set_layout(self, path: Path):
        self._set_path_value("layout", path)

    def _set_metric(self, key: str, image_path: Path):
        image_path_text = str(image_path)

        def mutator(data: dict) -> bool:
            if data["metrics"].get(key) == image_path_text:
                return False
            data["metrics"][key] = image_path_text
            return True

        self._update(mutator)

    def set_metrics_inst_dist(self, image_path: Path):
        self._set_metric("instances dist.", image_path)

    def set_metrics_layer_via_dist(self, image_path: Path):
        self._set_metric("layer via dist.", image_path)

    def set_metrics_layer_wire_dist(self, image_path: Path):
        self._set_metric("layer wire dist.", image_path)

    def set_metrics_pin_dist(self, image_path: Path):
        self._set_metric("pin dist.", image_path)

    def set_metrics_drc_dist(self, image_path: Path):
        self._set_metric("drc dist.", image_path)

    def set_metrics_cts_skew_map(self, image_path: Path):
        self._set_metric("CTS skew map", image_path)

    def set_checklist(self, checklist_path: Path):
        path = checklist_path
        if not path.exists():
            Checklist(path=path).save()

        self._set_path_value("checklist", path)

    def get_checklist_header(self):
        return Checklist(path=Path(self.data.get("checklist", ""))).header

    def update_checklist(self, step: str, type: str, item: str, state: str, info: str = ""):
        checklist = Checklist(path=Path(self.data.get("checklist", "")))
        checklist.update(step=step, type=type, item=item, state=state, info=info)

    def replace_checklist_step(self, step: str) -> None:
        """Drop all persisted results for a step before a current-output recheck."""
        checklist = Checklist(path=Path(self.data.get("checklist", "")))
        checklist.replace_step(step)
