# Plerion

Python/PySide6 control interface for a two-photon holographic stimulation setup. Replaces and unifies several legacy tools (MATLAB scripts, Qt app, standalone GUIs) into a single dark-themed GUI.

---

## Plerion TCP (branch `dev`)

The SLM's phase masks are shown by **Wavefront IV over its TCP server**, as Oriole TCP drives it. This replaces the script folder (`test.js` + `zdone.js`, which never answered), and Plerion now does arduinoReader's job itself. At each SLM trigger, Plerion loads the next mask of the order list. An SLM trigger is a rising edge of vec column 0 in the triggers counted by NI-DAQ. No Arduino is needed.

* **The code.**
  * `modules/wavefront/` is vendored from Oriole TCP (`E:\Oriole-tcp`, branch `tcp`, `b6c5d60`) with the same layout: `wf4` for Wavefront IV and `wf5` for Wavefront V, not ready yet. A fix found in one is ported to the other.
  * `modules/slm.py` is the SLM driver, with no Qt.
* **The connection.** Plerion reads Wavefront's port from `%TEMP%\blueBoxServer` and keeps one connection to it.
  * Every script ends by answering (`PLERION DONE <id>`), so Plerion knows what ran.
  * Wavefront runs scripts only with *Tools → Script engine → Tcp server* ticked, and it doesn't remember that setting. Plerion pings Wavefront once its window is open. If there is no answer, Plerion ticks the box itself with a one-line script dropped in Wavefront's `script` folder. **Check** (status bar) pings again.
  * The status bar shows *TCP ✓ (port n)* in green once Wavefront answers.
* **Phase masks folder** (DH and VDH, shared, remembered). Oriole TCP stores the masks of a session in `<experiment>\Phasemasks`: pick that folder with **…**.
  * Each mask named in the order file is looked for there by file name. Order files keep the paths of the PC that wrote them. If the name isn't there, Plerion tries the path written in the order file.
  * With no folder picked, Plerion uses the folder where Wavefront saves (`rootPath` in `wfdIV.ini`).
  * Masks found nowhere show in red, and **Scan** counts the spots in that folder.
* **RUN** is refused if:
  * Wavefront isn't running,
  * another program (Oriole TCP) just ran scripts in it, or
  * a mask of the order list is missing.

  Otherwise, Plerion arms the SLM first: Wavefront's pattern list is emptied once, then NI-DAQ and `film.exe` start.
* **At each SLM trigger** Plerion sends `cleanAllBlob(); deleteProfile(0); loadProfile("<mask>", 2);`. This is the same command as DHgui, the script folder and Oriole TCP's Load.
  * Only one script runs at a time. A trigger arriving before the last load answered waits.
  * Each load is logged with its latency. It's flagged **LATE** if it answered after the shutter opened.
  * A failed load, or a mask deleted since RUN, is logged in red and the protocol goes on. The SLM keeps the previous mask.
  * A summary closes the protocol.
* **With Oriole TCP open**, don't use its *Load*, *Generate* or *Check* during a protocol, and don't start or restart Oriole then. Two scripts running at once crash Wavefront. Plerion says so if it sees Oriole's scripts during a run.
* **Wavefront V**: `"wavefront": "V"` will choose it once `modules/wavefront/wf5` is ready. Its docstring lists what is left to find on the rig.
* **Tests** run without Qt or hardware: `C:\Users\S8\anaconda3\envs\oriole\python.exe -m pytest tests` (the `Plerion` env has no pytest).

---

## Hardware controlled

| Device | Role |
|--------|------|
| DMD (ALP API) | Visual stimulation via `film.exe` subprocess |
| NI-DAQ (Dev1) | Shutter (ao0) and SLM mask signal (ao1), clocked on DMD trigger (PFI0) |
| SLM + WaveFront IV | Phase mask switching over Wavefront IV's TCP server, one mask per SLM trigger |
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
python plerion_qtgui.py
# or on Windows:
plerion.bat
```

---

## Configuration

All machine-dependent parameters live in `plerion_params.jsonc` (JSON with comments). Edit once for your setup, for example:

```jsonc
{
  "nidaq": {
    "device":     "Dev1",
    "ao_shutter": 0,
    "ao_slm":     1,
    "pfi_clock":  0
  },
  "wavefront":            "IV",                    // Wavefront driven over TCP ("V" not ready yet)
  "wfd_root":             "E:\\wfdIV_20261022",    // Wavefront IV install
  "slm_load_timeout_s":   2,                       // a mask load not answered within this: failed
  "experiment_drive":     "D:\\",                  // where the phase masks folder dialog opens
  "film_exe":             "E:\\VisualStim_DMD\\x64\\Release\\film.exe",
  "binvecs_root":         "E:\\VisualStim_DMD\\data\\binvecs",
  "dh_stim_folder":       "E:\\VisualStim_DMD\\data\\binvecs\\00_DigitalHolography",
  "dh_vec_pattern":       "DigitalHolography_20Hz_{n_spots}HoloSpots_20rep.vec",
  "dh_phasemask_pattern": "DigitalHolography_{n_spots}spots_20rep_PhaseMasksOrder.txt",
  "trigger_timeout_s":    10
}
```

`trigger_timeout_s` — seconds without a NI-DAQ trigger before the protocol auto-stops.

Session state (selected files, the phase masks folder, last frequency) is saved automatically to `plerion_config.jsonc` on each run and on close.

---

## Tabs

### Visual
DMD-only stimulation. Select a binvec folder, a `.bin` and `.vec` file, set the frequency, and click **RUN PROTOCOL**.

- NI-DAQ trigger counter arms on PFI0 at launch
- Countdown panel shows total duration before run, then live countdown once triggers arrive
- Auto-stops when all triggers are played or when no trigger is received for `trigger_timeout_s` seconds

### DH — Digital Holography
Simplified holography mode. Set the number of spots and frequency; `.bin` / `.vec` / phase mask order files are resolved automatically from `plerion_params.jsonc` patterns. Pick the session's phase masks folder (shared with VDH).

### VDH — Visual + Digital Holography
Full experiment mode: DMD + NI-DAQ + SLM. Select a binvec folder with `.bin`, `.vec`, and phase mask order files, and the session's phase masks folder (shared with DH). Wavefront IV must be running.

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
├── plerion_qtgui.py        # Main GUI (Visual / DH / VDH tabs)
├── plerion_params.jsonc    # Machine-dependent parameters
├── plerion_config.jsonc    # Last session state (auto-saved)
├── requirements.txt
├── plerion.bat             # Launch script
├── modules/
│   ├── dmd.py              # film.exe subprocess (readdir indices piped to stdin)
│   ├── sync.py             # NI-DAQ trigger counter + ao output, vec columns
│   ├── slm.py              # SLM phase masks: order files, SlmDriver (Wavefront over TCP)
│   └── wavefront/          # Wavefront programs over TCP, vendored from Oriole TCP
│       ├── tcp.py          #   one kept connection, unique scripts that answer
│       ├── wf4/            #   Wavefront IV: link, program, scripts
│       └── wf5/            #   Wavefront V: not ready yet
└── tests/                  # pytest, no Qt, no hardware (fake Wavefront server)
```

---

## Run sequence (VDH)

1. Select `.bin`, `.vec`, and phase mask order file, and the session's phase masks folder
2. Set frequency (Hz)
3. Have Wavefront IV running (the status bar shows *TCP ✓* once it answers)
4. Click **RUN PROTOCOL** — the SLM is armed first, then NI-DAQ and film.exe; all wait for the DMD trigger on PFI0
5. Each SLM trigger loads the next phase mask; the log shows each load and a summary at the end
