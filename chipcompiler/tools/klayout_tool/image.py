#!/usr/bin/env python
import os
from pathlib import Path

from klayout import lay

from chipcompiler.utility.path import path_text


def save_snapshot_image(
    gds_file: str | Path,
    img_file: str | Path,
    width: int = 1920,
    height: int = 1920,
) -> bool:
    """
    Render a GDS file into a PNG image using KLayout's Python API.
    """
    if not gds_file or not img_file or not os.path.exists(gds_file):
        return False

    img_dir = os.path.dirname(path_text(img_file))
    if img_dir:
        os.makedirs(img_dir, exist_ok=True)

    lv = lay.LayoutView()
    lv.set_config("background-color", "#F5F5F5")
    lv.set_config("grid-visible", "false")
    lv.set_config("grid-show-ruler", "false")
    lv.set_config("text-visible", "false")

    lv.load_layout(path_text(gds_file), "")
    lv.max_hier()
    lv.timer()
    lv.save_image(path_text(img_file), int(width), int(height))
    return os.path.exists(img_file)
