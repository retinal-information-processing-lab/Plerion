"""Wavefront IV (wfdIV, Qt 4, 2018), driven over TCP: its program (program), its TCP server (link), its scripts
(scripts). Everything here was found on the rig, by trying it and reading its script plugin: seen, not documented,
so any change to what goes over TCP is tried on the rig again.

Vendored from Oriole TCP (oriole/wavefront/wf4/__init__.py), trimmed to what Plerion uses, with Plerion's protocol
scripts.
"""
from __future__ import annotations

from pathlib import Path

from ..base import Wavefront
from . import link, program, scripts


class WavefrontIV(Wavefront):
    KEY = "IV"
    NAME = "Wavefront IV"
    READY = True
    ROOT_KEY = "wfd_root"
    LAUNCHER = program.LAUNCHER
    PROCESS = program.CORE
    WINDOW_TITLE = program.WINDOW_TITLE
    OUTPUT_FOLDER = program.OUTPUT_FOLDER
    SERVER = "Tcp server"
    SCRIPTS_HINT = 'tick "Tools → Script engine → Tcp server" in Wavefront IV'
    CAN_TICK = True
    TICK_VIA = "script dropped in its script folder"
    TICK_NOT_TAKEN = "not in auto-load mode"

    def new_link(self) -> link.Wavefront4Link:
        return link.Wavefront4Link()

    # ------------------------------------------------------------------ the program
    def install_problem(self, folder=None) -> str | None:
        return program.install_problem(folder or self.root)

    def saves_in(self) -> str | None:
        return program.saves_in()

    # ------------------------------------------------------------------ a protocol
    def prepare_script(self, masks: list[Path]) -> str:
        """Its pattern list emptied: each mask is loaded at its trigger (load_script), none preloaded."""
        return scripts.prepare_script()

    def load_script(self, png: Path, k: int) -> str:
        return scripts.load_script(png)

    # ------------------------------------------------------------------ its Tcp server, ticked by Plerion
    def tick(self, folder) -> int:
        """The script clicking Tcp server, dropped in its script folder: run if Wavefront is in auto-load mode, as it
        starts; its answer comes over TCP like any other."""
        sid, js = self.link.script(scripts.TICK_JS)
        program.drop_script(folder, js)
        return sid

    def tick_waiting(self, folder) -> bool:
        return program.script_waiting(folder)

    def take_back_tick(self, folder):
        program.take_back_script(folder)
