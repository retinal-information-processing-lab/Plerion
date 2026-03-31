# Branch 2 — NI-DAQ sync
# TriggerCounter: counts rising edges on a PFI terminal (ctr0).
# count_vec_triggers: returns the number of trigger lines in a .vec file.
# count_spots_from_folder: infers n_spots from generated phasemask filenames.

import os
import re

try:
    import nidaqmx
    from nidaqmx.constants import Edge
    _NIDAQMX_OK = True
except ImportError:
    _NIDAQMX_OK = False


def count_spots_from_folder(folder: str, pattern: str) -> int:
    """Count the number of unique spots in a GeneratedPhasemasks folder.

    pattern uses one placeholder:
      {n} — spot index (any number of digits, no padding assumed)

    The rest of the pattern is treated as a literal match.
    Returns the count of unique {n} values found, or 0 on error.

    Example pattern: "Pattern{n}_000.algoPhp.png"
    """
    if not folder or not os.path.isdir(folder):
        return 0
    escaped = re.escape(pattern)
    regex_str = escaped.replace(r'\{n\}', r'(\d+)')
    try:
        rx = re.compile(r'^' + regex_str + r'$')
    except re.error:
        return 0
    unique_n = set()
    for fname in os.listdir(folder):
        m = rx.match(fname)
        if m:
            unique_n.add(m.group(1))
    return len(unique_n)


def count_vec_triggers(vec_path: str) -> int:
    """Return the number of trigger lines in a .vec file (first line is header)."""
    with open(vec_path, 'r') as f:
        return max(0, sum(1 for _ in f) - 1)


class TriggerCounter:
    """Counts rising edges on a PFI terminal using a NI-DAQ counter input (ctr0).

    Usage:
        ctr = TriggerCounter('Dev1', pfi_idx=0)
        n   = ctr.read()   # cumulative edge count
        ctr.close()
    """

    def __init__(self, device: str, pfi_idx: int):
        if not _NIDAQMX_OK:
            raise RuntimeError('nidaqmx not installed')
        self._task = nidaqmx.Task()
        ch = self._task.ci_channels.add_ci_count_edges_chan(
            f'{device}/ctr0',
            edge=Edge.RISING,
        )
        ch.ci_count_edges_term = f'/{device}/PFI{pfi_idx}'
        self._task.start()

    def read(self) -> int:
        return self._task.read()

    def close(self) -> None:
        try:
            self._task.stop()
            self._task.close()
        except Exception:
            pass
