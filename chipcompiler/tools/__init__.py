from .eda import (
    load_eda_module,
    create_step,
    run_step,
    save_layout_image,
    build_step_metrics,
    get_step_info
)

global _gui_notify
_gui_notify = None

def gui_notify():
    global _gui_notify
    return _gui_notify

def set_gui_notify(gui_notify):
    _gui_notify = gui_notify

__all__ = [
    'load_eda_module',
    'create_step',
    'run_step',
    'save_layout_image',
    'build_step_metrics',
    'get_step_info',
    'gui_notify',
    'set_gui_notify'
]

