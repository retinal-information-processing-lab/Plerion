# Branch 2 — NI-DAQ sync
# TriggerCounter: counts rising edges on a PFI terminal (ctr0).
# count_vec_triggers: returns the number of trigger lines in a .vec file.
# count_spots_from_folder: infers n_spots from generated phasemask filenames.

import os
import re

try:
    import nidaqmx
    from nidaqmx.constants import Edge, AcquisitionType
    _NIDAQMX_OK = True
except ImportError:
    _NIDAQMX_OK = False


def probe_nidaq(device: str) -> bool:
    """Return True if the NI-DAQ device is reachable (read-only, no Task opened)."""
    if not _NIDAQMX_OK:
        return False
    try:
        import nidaqmx.system
        return device in [d.name for d in nidaqmx.system.System.local().devices]
    except Exception:
        return False


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


def read_vec_columns(vec_path: str) -> tuple:
    """Return (col0_list, col3_list) from a vec file (header line skipped).

    col0 = column index 0 of the vec (raw, caller decides meaning)
    col3 = column index 3 of the vec (raw, caller decides meaning)
    """
    col0, col3 = [], []
    try:
        with open(vec_path, 'r') as f:
            next(f)  # skip header
            for line in f:
                parts = line.split()
                if len(parts) >= 4:
                    col0.append(int(float(parts[0])))
                    col3.append(int(float(parts[3])))
    except Exception:
        pass
    return col0, col3


class WaveformOutput:
    """Hardware-timed NI-DAQ AO: plays shutter + SLM waveforms clocked on external trigger.

    Loads entire vec columns as analog waveforms at arm time.
    Each rising edge on the PFI source advances one sample — zero CPU involvement.

    Usage:
        col0, col3 = read_vec_columns(vec_path)
        wf = WaveformOutput('Dev1', pfi_source=0,
                            ao_shutter=0, ao_slm=1,
                            shutter_col=col0, slm_col=col3)
        wf.start()       # armed — hardware plays on each trigger
        ...
        wf.close()       # writes 0V on both channels, releases task
    """

    def __init__(self, device: str, pfi_source: int,
                 ao_shutter: int, ao_slm: int,
                 shutter_col: list, slm_col: list):
        if not _NIDAQMX_OK:
            raise RuntimeError('nidaqmx not installed')
        n = len(shutter_col)
        if n == 0:
            raise ValueError('empty waveform columns')
        self._task = nidaqmx.Task()
        self._task.ao_channels.add_ao_voltage_chan(
            f'{device}/ao{ao_shutter}', min_val=0.0, max_val=10.0)
        self._task.ao_channels.add_ao_voltage_chan(
            f'{device}/ao{ao_slm}', min_val=0.0, max_val=5.0)
        self._task.timing.cfg_samp_clk_timing(
            rate=1000.0,
            source=f'/{device}/PFI{pfi_source}',
            active_edge=Edge.RISING,
            sample_mode=AcquisitionType.FINITE,
            samps_per_chan=n)
        shutter_v = [float(s) * 10.0 for s in shutter_col]
        slm_v     = [float(s) * 5.0  for s in slm_col]
        self._task.write([shutter_v, slm_v], auto_start=False)

    def start(self):
        self._task.start()

    def is_done(self) -> bool:
        return self._task.is_task_done()

    def close(self):
        try:
            self._task.stop()
            self._task.close()
        except Exception:
            pass


class ShutterOutput:
    """Single-sample NI-DAQ analog output for the shutter (0 V = closed, 10 V = open).

    Software-timed single-point AO: do NOT call task.start() — write() uses
    auto_start=True (nidaqmx default) which handles start/commit internally.

    Usage:
        shutter = ShutterOutput('Dev1', ao_channel=0)
        shutter.write(10.0)   # open
        shutter.write(0.0)    # close
        shutter.close()       # writes 0 V then releases task
    """

    def __init__(self, device: str, ao_channel: int):
        if not _NIDAQMX_OK:
            raise RuntimeError('nidaqmx not installed')
        self._task = nidaqmx.Task()
        self._task.ao_channels.add_ao_voltage_chan(
            f'{device}/ao{ao_channel}',
            min_val=0.0,
            max_val=10.0,
        )
        # Do NOT call task.start() — write() with auto_start=True handles it

    def write(self, voltage: float) -> None:
        self._task.write(float(voltage), auto_start=True)

    def close(self) -> None:
        try:
            self._task.write(0.0, auto_start=True)   # ensure shutter is closed
        except Exception:
            pass
        try:
            self._task.stop()
            self._task.close()
        except Exception:
            pass


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
        return int(self._task.read())

    def close(self) -> None:
        try:
            self._task.stop()
            self._task.close()
        except Exception:
            pass
