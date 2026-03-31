# Plerion — Context for Claude Code

## What is Plerion

Plerion is a Python/Tkinter application that replaces and unifies several existing tools for a two-photon holographic stimulation setup in a visual neuroscience lab. It controls a DMD (Digital Micromirror Device), a SLM (Spatial Light Modulator), a laser (Spectra-Physics InSight DeepSee), NI-DAQ analog outputs, and two Arduino boards, all synchronized on a common DMD trigger TTL signal.

It replaces:
- `film.exe` interaction (C++ console app, ALP API) — not replaced, but driven via subprocess with piped stdin
- `DH_SynchroInactivationScript.m` (MATLAB NI-DAQ script)
- `arduinoReader.exe` (Qt5/QML app managing SLM phase mask switching)
- `luciole_gui.py` (Tkinter app for LED color control)

---

## Repository structure

```
plerion/
├── plerion_gui.py              # Main Tkinter GUI
├── plerion_config.json         # Last session state (paths, ports, LED selection, etc.)
├── plerion_params.json         # Machine-dependent parameters (see below)
├── modules/
│   ├── dmd.py                  # Branch 1: symlinks + film.exe subprocess
│   ├── sync.py                 # Branch 2: NI-DAQ ao0/ao1 clocked on PFI0
│   ├── slm.py                  # Branch 3: Arduino SLM serial + TCP WaveFront IV
│   └── leds.py                 # Branch 4: Arduino LED DAC SPI (Luciole clone)
└── arduino/
    ├── arduino_slm/
    │   └── arduino_slm.ino     # sendPeriodOnTrig — unchanged from original
    └── arduino_led/
        ├── arduino_led.ino     # luciole_arduino — unchanged from original
        ├── ColorSetupLib.cpp
        └── ColorSetupLib.h
```

---

## plerion_params.json — all machine-dependent parameters

```json
{
  "nidaq": {
    "device": "Dev1",
    "ao_shutter": 0,
    "ao_slm": 1,
    "pfi_clock": 0
  },
  "tcp_slm": {
    "host": "172.17.19.37",
    "port": 55160
  },
  "arduino_slm_baud": 128000,
  "arduino_led_baud": 115200,
  "film_exe": "E:/VisualStim_DMD/Release/film.exe",
  "vdh_symlink_bin_dir": "E:/VisualStim_DMD/data/binvecs/test/Bin",
  "vdh_symlink_vec_dir": "E:/VisualStim_DMD/data/binvecs/test/Vec",
  "dh_vec_folder": "E:/VisualStim_DMD/data/binvecs/00_DigitalHolography/VEC",
  "dh_bin_folder": "E:/VisualStim_DMD/data/binvecs/00_DigitalHolography/Bin",
  "dh_phasemask_order_folder": "E:/wfdIV_20241023/PhaseMasksOrders",
  "dh_vec_pattern": "DigitalHolography_20Hz_{n_spots}HoloSpots_20rep.vec",
  "dh_phasemask_pattern": "DigitalHolography_{n_spots}spots_20rep_PhaseMasksOrder.txt"
}
```

All paths use forward slashes. The code must use `os.symlink` (works without admin on Windows with Developer Mode enabled).

---

## VEC file format

5-column space-separated text file. First line is a header (skip it). Columns (0-indexed):

| Col | Content | Used by |
|-----|---------|---------|
| 0 | SLM analog signal (×5V → NI-DAQ ao1) | sync.py |
| 1 | DMD frame index (passed to film.exe as FrameNumbers) | dmd.py (film.exe reads it directly) |
| 2 | LED mix index (indexes into CSV row) | leds.py |
| 3 | Shutter signal (×10V → NI-DAQ ao0) | sync.py |
| 4 | Unused | — |

The same VEC file is shared across all four branches. In VDH mode it is selected by the user via file picker. In DH mode it is auto-resolved from `dh_vec_folder` using `dh_vec_pattern` with `n_spots`.

---

## Branch 1 — DMD (dmd.py)

### Goal
Create symlinks pointing to user-selected .bin and .vec files, then launch `film.exe` with stdin piped to answer its interactive prompts automatically.

### film.exe behavior (C++ ALP API console app)
Located at `params["film_exe"]` = `E:/VisualStim_DMD/Release/film.exe`.

When launched it:
1. Lists subdirectories of `../../data/binvecs/` (relative to its own location = `E:/VisualStim_DMD/data/binvecs/`)
2. Asks `Enter your user number:` → index of subdirectory
3. Lists `.bin` files in `{subdir}/Bin/`
4. Asks `Enter the number of a .bin file:` → index
5. Lists `.vec` files in `{subdir}/Vec/`
6. Asks `Enter the number of a .vec file:` → index
7. Asks `Enter the frame rate (in Hz):` → float
8. Asks `Advanced features (y/n)?` → string

### Strategy
- Fixed subdirectory `test/` always exists inside `data/binvecs/`
- `test/Bin/` contains a single symlink `BIN_link.bin` → selected .bin file
- `test/Vec/` contains a single symlink `VEC_link.vec` → selected .vec file
- Pipe stdin: `"0\n0\n0\n{freq}\nn\n"` (user index 0 = test, bin index 0, vec index 0)
- Read stdout in a thread and forward to the shared console log

### Symlink creation (Windows, Developer Mode)
```python
import os

def make_symlink(target_path: str, link_path: str):
    if os.path.islink(link_path) or os.path.exists(link_path):
        os.remove(link_path)
    os.symlink(target_path, link_path)
```

---

## Branch 2 — Sync / NI-DAQ (sync.py)

### Goal
Replace `DH_SynchroInactivationScript.m`. Output two analog signals clocked on the DMD trigger.

### NI-DAQ session
- `ao0` (`Dev1/ao0`) → shutter: `col3 × 10.0` volts
- `ao1` (`Dev1/ao1`) → SLM mask signal: `col0 × 5.0` volts
- Clock source: `Dev1/PFI0` (external, = DMD trigger)
- Sample rate: set to stimulus frequency (same as film.exe frame rate)
- `ExternalTriggerTimeout = Inf`

### VEC parsing for NI-DAQ
```python
import pandas as pd
df = pd.read_csv(vec_path, sep=r'\s+', skiprows=1, header=None)
shutter_signal = df[3].values * 10.0   # ao0
slm_signal     = df[0].values * 5.0    # ao1
```

### nidaqmx Python pattern
```python
import nidaqmx
from nidaqmx.constants import AcquisitionType

with nidaqmx.Task() as task:
    task.ao_channels.add_ao_voltage_chan(f"{device}/ao0")
    task.ao_channels.add_ao_voltage_chan(f"{device}/ao1")
    task.timing.cfg_samp_clk_timing(
        rate=freq_hz,
        source=f"/{device}/PFI{pfi}",
        sample_mode=AcquisitionType.FINITE,
        samps_per_chan=len(shutter_signal)
    )
    task.write([shutter_signal.tolist(), slm_signal.tolist()])
    task.start()
    # non-blocking: task runs in background clocked on trigger
```

---

## Branch 3 — SLM phase mask (slm.py)

### Goal
Replace `arduinoReader.exe`. At each DMD trigger, send the next phase mask path to WaveFront IV via TCP.

### Phase mask order file format
Text file, first line is a comment (skip). Each subsequent line is an absolute path to a `.algoPhp.png` file:
```
---- This line will not be read ----
E:/wfdIV_20241023/GeneratedPhasemasks/Pattern4_000.algoPhp.png
E:/wfdIV_20241023/GeneratedPhasemasks/Pattern2_000.algoPhp.png
...
```
500 lines (after header) for a 25-spot 20-rep experiment.

### Arduino SLM
Sketch: `arduino/arduino_slm/arduino_slm.ino` = `sendPeriodOnTrig.ino` unchanged.
- Baud: 128000
- On each DMD trigger (rising edge on pin 2): captures Timer1, sends a framed serial message
- Frame format: `0x88 0x88 0x88 0x88 | 0x00 0x02 | MSB LSB | 0xFF 0xFF 0xFF 0xFF` (12 bytes)
- MSB/LSB = Timer1 count at trigger time (period measurement, not used for indexing)
- Python just needs to detect each incoming 12-byte frame as a "trigger received" event

### TCP connection to WaveFront IV
- Persistent TCP connection to `host:port` from params
- On each trigger event from Arduino serial: send the next path from the order list
- Message format: path string as bytes, terminated with `\n` (to confirm at first run — may be `\r\n` or null)

```python
import socket

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.connect((host, port))

# On each trigger:
path = phase_mask_list[current_index]
sock.sendall((path + '\n').encode('utf-8'))
current_index += 1
```

### Serial reading (Arduino SLM trigger detection)
```python
import serial

FRAME_SIZE = 12
HEADER = bytes([0x88, 0x88, 0x88, 0x88])

def read_trigger_frames(ser):
    buf = bytearray()
    while running:
        buf += ser.read(ser.in_waiting or 1)
        # find header
        idx = buf.find(HEADER)
        if idx >= 0 and len(buf) >= idx + FRAME_SIZE:
            frame = buf[idx:idx+FRAME_SIZE]
            buf = buf[idx+FRAME_SIZE:]
            yield frame  # one trigger event
```

---

## Branch 4 — LED colors (leds.py)

### Goal
Identical logic to `luciole_gui.py` communication thread. Synchronize LED colors with DMD triggers.

### Arduino LED
Sketch: `arduino/arduino_led/arduino_led.ino` = `luciole_arduino.ino` unchanged.
- Baud: 115200
- Waits for `'S'` + mask byte, then initial buffer fill, then sends `'R'` handshake
- On each DMD trigger (pin A2): consumes one mix from circular buffer, outputs DAC values via SPI
- Sends back: `MSG_REFILL (0x01)` + count, `MSG_FREQ (0x02)` + uint16 Hz, `MSG_TRIG_ERR (0x03)` + uint32 µs

### Protocol (Python → Arduino)
1. Send `b'S'` + `bytes([led_mask])` — 1 bit per wavelength [385, 420, 490, 530, 625]
2. Send initial buffer: 99 mixes × N_leds × 2 bytes each (uint16 big-endian DAC value)
3. Wait for `b'R'` handshake
4. Main loop: on `MSG_REFILL`, send N more mixes

### CSV format
No header. Each row = one mix. Columns = selected wavelengths in ascending order.
Values are voltages (0–2.5V). Conversion: `raw = int((v / 2.0) * (4095 / 2.5))`, clamp 0–4095.

### VEC column for LED
Column 2 of the VEC file is the mix index into the CSV.

```python
df_vec = pd.read_csv(vec_path, sep=r'\s+', skiprows=1, header=None)
sequence = df_vec[2].astype(int).tolist()  # mix index per trigger
```

---

## GUI structure

### Two tabs
- **VDH** — full experiment mode
- **DH** — digital holography simplified mode

### Shared elements
- Single console log (black background, green monospace text, colored tags: warn=yellow, error=red, freq=cyan)
- Both tabs use the same console widget

### VDH tab layout (left column + right column, same spirit as Luciole)

**Left column:**
- File pickers: `.bin`, `.vec`, phasemask order file
- Checkbox **"Use colors"** — enables/disables LED section
- If colors enabled: CSV file picker + LED wavelength toggles [385, 420, 490, 530, 625] + color palette table

**Right column:**
- Frequency input field (float, Hz)
- Hardware section:
  - Arduino SLM: COM port combobox + `FLASH & CONNECT` button + status dot
  - Arduino LED: COM port combobox + `FLASH & CONNECT` button + status dot (grayed if colors off)
  - NI-DAQ: status indicator
  - TCP WaveFront: status indicator
- Console log (shared)
- Progress bar + duration/remaining label
- `RUN PROTOCOL` button (bottom, full width)

### DH tab layout

- Frequency input (default 20 Hz)
- Number of spots (spinbox, integer) → auto-resolves vec + phasemask order from params patterns
- BIN selection: radio button or toggle between "Bright" / "Dark" (2 files in `dh_bin_folder`)
- Arduino SLM: COM port combobox + `FLASH & CONNECT` button + status dot
- (No colors, no Arduino LED)
- Console log (shared with VDH)
- `RUN PROTOCOL` button

### Arduino flash logic (both tabs)
```python
def flash_arduino(port, sketch_path, fqbn="arduino:avr:uno"):
    cmd = ["arduino-cli", "compile", "--upload",
           "-p", port, "--fqbn", fqbn, sketch_path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0, result.stderr
```
Run in a daemon thread. On success: open serial port and start reading.

---

## Visual style (match Luciole)

```python
COLOR_BG   = '#121212'
COLOR_CARD = '#1E1E1E'
COLOR_TEXT = '#E0E0E0'
LED_COLORS = {385: "#7D00FF", 420: "#0033FF", 490: "#00CCFF",
              530: "#00FF00", 625: "#FF0000"}
```
- Dark theme throughout
- `ttk.Style` with `clam` theme
- Log tags: `info=#00FF00`, `warn=#FFD700`, `error=#FF4444`, `freq=#00CCFF`

---

## Run sequence (VDH)

1. User selects .bin, .vec, phasemask order file, (CSV if colors)
2. User enters frequency
3. User flashes/connects both Arduinos
4. Click **RUN**:
   a. `dmd.py`: create symlinks, launch `film.exe` subprocess, pipe stdin
   b. `sync.py`: parse VEC col0+col3, start NI-DAQ task (waits for PFI0 clock)
   c. `slm.py`: load phasemask list, connect TCP, start serial read thread
   d. `leds.py` (if colors): load CSV+VEC col2, send buffer to Arduino LED, wait handshake
5. All branches armed and waiting for DMD trigger
6. Log: `">>> ALL SYSTEMS ARMED — START DMD NOW <<<"`

## Run sequence (DH)

Same as VDH but:
- Files auto-resolved from params + n_spots
- No LED branch
- BIN is bright or dark from fixed folder

---

## Key constraints

- Windows only (NI-DAQ, ALP API, arduino-cli)
- Developer Mode must be enabled for `os.symlink` without admin
- `film.exe` path is relative to its own directory (`../../data/binvecs/`) — symlink dirs must be inside that tree
- TCP message terminator for WaveFront IV is assumed `\n` — may need to test `\r\n` or null byte
- Arduino SLM baud: 128000 — Arduino LED baud: 115200
- NI-DAQ clock is external (PFI0 = DMD trigger) so `task.start()` is non-blocking until first trigger
- All serial/TCP/subprocess operations run in daemon threads, never blocking the GUI mainloop

---

## Dependencies

```
pip install pyserial nidaqmx pandas
# arduino-cli must be installed and in PATH
```
