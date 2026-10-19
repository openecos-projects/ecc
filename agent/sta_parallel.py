"""Compatibility exports for Agent callers of the shared ECC STA scheduler."""

from chipcompiler.tools.ecc.sta_parallel import (
    _arm_parent_death_signal as _arm_parent_death_signal,
)
from chipcompiler.tools.ecc.sta_parallel import (
    run_parallel_sta as run_parallel_sta,
)
from chipcompiler.tools.ecc.sta_parallel import (
    sta_workers as sta_workers,
)
from chipcompiler.tools.ecc.sta_parallel import (
    track_sta_process_memory as track_sta_process_memory,
)
