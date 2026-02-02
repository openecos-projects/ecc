import os
import time


def track_process_memory(pid):
    peak_rss_kb = 0
    try:
        # check memory usage every 0.1 second
        while os.path.exists(f"/proc/{pid}/status"):
            with open(f"/proc/{pid}/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        # VmRSS is in kB
                        rss_kb = int(line.split()[1])
                        peak_rss_kb = max(peak_rss_kb, rss_kb)
                        break
            time.sleep(0.1)
    except Exception:
        # ignore errors
        pass
    return peak_rss_kb