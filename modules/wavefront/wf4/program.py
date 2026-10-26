"""Wavefront IV as a program (Windows): its install folder, its settings, its script folder.

An install is a copy of Wavefront's zip in a folder of its own (E:\\wfdIV_<date>): its ``wfdIV.exe`` is a launcher
that runs the program itself, ``wfdIVCore.dll`` (also the process name). Its licence expires now and then: the core
then fails to start, or is left empty, and Wavefront is installed again in a new folder (the fix is in "Wavefront IV
Errorcode 7536725.pdf" on the desktop).

Every install shares the settings in %APPDATA%\\wfdIV\\wfdIV.ini (a QSettings ini file), read when Wavefront starts
and written when it starts and exits. As tried on the rig, ``[mainSettings] rootPath`` there is the folder it saves
the masks in, and ``[scriptEngine] autoload`` makes it start running the scripts dropped in its ``script`` folder
(Oriole TCP sets both when it starts Wavefront). Its "Tcp server", which Plerion needs, is not remembered: Plerion ticks
it with a script dropped in that folder (drop_script).

Vendored from Oriole TCP (oriole/wavefront/wf4/program.py): what Plerion uses, unchanged (starting Wavefront is left
to Oriole TCP).
"""
from __future__ import annotations

import os
from pathlib import Path

from .. import qtini

LAUNCHER = "wfdIV.exe"
CORE = "wfdIVCore.dll"
WINDOW_TITLE = "Wavefront Designer IV"      # its main window, open once it is ready
OUTPUT_FOLDER = "GeneratedPhasemasks"       # in the install: where it saves the masks (made by hand: the zip has none)
INI_PATH = Path(os.environ.get("APPDATA", Path.home())) / "wfdIV" / "wfdIV.ini"
LICENCE_HELP = 'the licence expired? Its fix is in "Wavefront IV Errorcode 7536725.pdf" on the desktop'


def install_problem(folder) -> str | None:
    """What keeps Wavefront from starting from ``folder``, if anything."""
    folder = Path(folder)
    if not (folder / LAUNCHER).is_file():
        return f"no {LAUNCHER} in {folder}"
    core = folder / CORE
    if not core.is_file() or core.stat().st_size == 0:
        return f"{CORE} is missing or empty in {folder}: {LICENCE_HELP}"
    if not (folder / OUTPUT_FOLDER).is_dir():
        return f"no {OUTPUT_FOLDER} folder in {folder}: make it"
    return None


def saves_in(path=None) -> str | None:
    """The folder the running Wavefront saves its masks in (written in its settings when it starts)."""
    return qtini.read(path or INI_PATH, "mainSettings", "rootPath")


# ----------------------------------------------------------------------------- script folder
SCRIPT_DIR = "script"               # in the install: Wavefront runs test.js once an empty zdone.js follows it
SCRIPT_NAME, TRIGGER_NAME = "test.js", "zdone.js"


def drop_script(folder, js: str) -> Path:
    """Have Wavefront (started from ``folder``, in auto-load mode) run ``js``: test.js, then the empty zdone.js that
    starts it; Wavefront removes both. The script folder, or OSError (no folder, a script still waiting there)."""
    script_dir = Path(folder) / SCRIPT_DIR
    if not script_dir.is_dir():
        raise FileNotFoundError(f"no {SCRIPT_DIR} folder in {folder}")
    if (script_dir / SCRIPT_NAME).exists():
        raise FileExistsError(f"{script_dir / SCRIPT_NAME} is still waiting there")
    part = script_dir / (SCRIPT_NAME + ".part")
    part.write_text(js, encoding="utf-8")       # written whole, then renamed: never read half written
    os.replace(part, script_dir / SCRIPT_NAME)
    (script_dir / TRIGGER_NAME).write_text("")
    return script_dir


def script_waiting(folder) -> bool:
    """A script dropped in the script folder of ``folder`` is not taken yet."""
    return any((Path(folder) / SCRIPT_DIR / name).exists() for name in (SCRIPT_NAME, TRIGGER_NAME))


def take_back_script(folder):
    """Remove a script Wavefront did not take (not in auto-load mode): the folder left as it was."""
    for name in (SCRIPT_NAME, TRIGGER_NAME, SCRIPT_NAME + ".part"):
        try:
            (Path(folder) / SCRIPT_DIR / name).unlink()
        except FileNotFoundError:
            pass
