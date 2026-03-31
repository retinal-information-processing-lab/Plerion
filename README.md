# Plerion

Python/Tkinter control interface for a two-photon holographic stimulation setup. Replaces and unifies several legacy tools (MATLAB scripts, Qt app, standalone GUIs) into a single dark-themed GUI.

---

## Hardware controlled

| Device | Role |
|--------|------|
| DMD (ALP API) | Visual stimulation via `film.exe` subprocess |
| NI-DAQ (Dev1) | Shutter (ao0) and SLM mask signal (ao1), clocked on DMD trigger (PFI0) |
| SLM + WaveFront IV | Phase mask switching via Arduino serial + TCP |
| Arduino LED | Per-trigger LED color mixing (Luciole protocol) |

---

## Requirements

- Windows (NI-DAQ drivers, ALP API)
- Python 3.10+
- [Developer Mode](https://learn.microsoft.com/en-us/windows/apps/get-started/enable-your-device-for-development) enabled (required for `os.symlink` without admin)
- `arduino-cli` in PATH (for Arduino flash)

```
pip install pyserial nidaqmx pandas
```

---

## Installation

```bash
git clone https://github.com/retinal-information-processing-lab/Plerion.git
cd Plerion
pip install -r requirements.txt
```

Launch:
```bash
python plerion_gui.py
# or on Windows:
plerion.bat
```

---

## Configuration

All machine-dependent parameters live in `plerion_params.json`. Edit once for your setup:

```json
{
  "nidaq": {
    "device":     "Dev1",
    "ao_shutter": 0,
    "ao_slm":     1,
    "pfi_clock":  0
  },
  "tcp_slm": {
    "host": "172.17.19.37",
    "port": 55160
  },
  "film_exe":             "E:/VisualStim_DMD/Release/film.exe",
  "binvecs_root":         "E:/VisualStim_DMD/data/binvecs",
  "dh_bin_folder":        "E:/VisualStim_DMD/data/binvecs/00_DigitalHolography/Bin",
  "dh_vec_pattern":       "DigitalHolography_20Hz_{n_spots}HoloSpots_20rep.vec",
  "dh_phasemask_pattern": "DigitalHolography_{n_spots}spots_20rep_PhaseMasksOrder.txt",
  "trigger_timeout_s":    10
}
```

`trigger_timeout_s` — seconds without a NI-DAQ trigger before the protocol auto-stops.

Session state (selected files, ports, last frequency) is saved automatically to `plerion_config.json` on each run and on close.

---

## Tabs

### Visual
DMD-only stimulation. Select a binvec folder, a `.bin` and `.vec` file, set the frequency, and click **RUN PROTOCOL**.

- NI-DAQ trigger counter arms on PFI0 at launch
- Countdown panel shows total duration before run, then live countdown once triggers arrive
- Auto-stops when all triggers are played or when no trigger is received for `trigger_timeout_s` seconds

### DH — Digital Holography
Simplified holography mode. Set the number of spots and frequency; `.bin` / `.vec` / phase mask files are resolved automatically from `plerion_params.json` patterns.

### VDH — Visual + Digital Holography
Full experiment mode: DMD + NI-DAQ + SLM + Arduino. Select a binvec folder with `.bin`, `.vec`, and phase mask files. Connect hardware before running.

---

## VEC file format

5-column space-separated text, one header line (skipped):

| Column | Content | Used by |
|--------|---------|---------|
| 0 | SLM signal (× 5 V → ao1) | sync.py |
| 1 | DMD frame index | film.exe |
| 2 | LED mix index | leds.py |
| 3 | Shutter signal (× 10 V → ao0) | sync.py |
| 4 | Unused | — |

---

## Repository structure

```
Plerion/
├── plerion_gui.py          # Main GUI (Visual / DH / VDH tabs)
├── plerion_params.json     # Machine-dependent parameters
├── plerion_config.json     # Last session state (auto-saved)
├── requirements.txt
├── plerion.bat / .sh       # Launch scripts
├── modules/
│   ├── dmd.py              # film.exe subprocess + symlink management
│   ├── sync.py             # NI-DAQ trigger counter + ao output
│   ├── slm.py              # Arduino SLM serial + TCP WaveFront IV
│   └── leds.py             # Arduino LED (Luciole protocol)
└── arduino/
    ├── arduino_slm/        # sendPeriodOnTrig sketch
    └── arduino_led/        # Luciole LED sketch
```

---

## Run sequence (VDH)

1. Select `.bin`, `.vec`, and phase mask order file (+ LED CSV if using colors)
2. Set frequency (Hz)
3. Flash & connect Arduino SLM and Arduino LED
4. Click **RUN PROTOCOL** — all branches arm and wait for DMD trigger on PFI0
5. Start DMD — triggers drive NI-DAQ, SLM, and LEDs in sync
