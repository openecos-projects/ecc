from typing import TYPE_CHECKING

from .builder import build_step, build_step_config, build_step_space
from .utility import is_eda_exist

if TYPE_CHECKING:
    from .image import save_snapshot_image
    from .module import KlayoutModule
    from .runner import run_step, save_gds_image
    from .viewer import view_gds

__all__ = [
    "is_eda_exist",
    "build_step",
    "build_step_space",
    "build_step_config",
    "run_step",
    "KlayoutModule",
    "save_gds_image",
    "save_snapshot_image",
    "view_gds",
]


def __getattr__(name):
    if name == "save_snapshot_image":
        from .image import save_snapshot_image

        return save_snapshot_image
    if name == "KlayoutModule":
        from .module import KlayoutModule

        return KlayoutModule
    if name == "run_step":
        from .runner import run_step

        return run_step
    if name == "save_gds_image":
        from .runner import save_gds_image

        return save_gds_image
    if name == "view_gds":
        from .viewer import view_gds

        return view_gds
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
