"""What Plerion needs from a Wavefront, whatever its version: the interface every version implements (wf4: Wavefront
IV, wf5: Wavefront V). slm.py and the window only use what is here, so a version is added without touching them.

A version is one installed copy of the program, in ``root`` (its install folder, from plerion_params.jsonc): its program
(found running, its window open), its TCP link (tcp.TcpLink), its scripts (a protocol prepared, a phase mask shown at
an SLM trigger), and what it takes for its server to run Plerion's scripts. The texts below are its words in the log.
Only one Wavefront runs at a time: they share the SLM.

Vendored from Oriole TCP (oriole/wavefront/base.py), trimmed to what Plerion uses; prepare_script and load_script are
Plerion's, made for a version that preloads the masks of a protocol (Wavefront V's SLM buffer) as well as for one that
loads each mask when it is shown (Wavefront IV).
"""
from __future__ import annotations

from pathlib import Path

from . import winproc
from .tcp import TcpLink
from .winproc import Process


class Wavefront:
    KEY = ""                        # in plerion_params.jsonc ("IV", "V")
    NAME = ""                       # in the log ("Wavefront IV")
    READY = False                   # can be chosen (a version not ready falls back to the default one)
    ROOT_KEY = ""                   # the plerion_params.jsonc key holding its install folder
    LAUNCHER = ""                   # in its install: what starts it
    PROCESS = ""                    # the executable of its process doing the work ("" : not known)
    WINDOW_TITLE = ""               # how its main window's title starts (shown: it is ready)
    OUTPUT_FOLDER = ""              # in its install: where it saves the phase masks it computes
    SERVER = "TCP server"           # what must be on for it to run Plerion's scripts
    SCRIPTS_HINT = ""               # how to switch that on by hand
    CAN_TICK = False                # Plerion can switch it on itself (tick)
    TICK_VIA = ""                   # ... with what: "script dropped in its script folder"
    TICK_NOT_TAKEN = ""             # ... why that may not be taken
    PING = ""                       # a script doing nothing: does it run Plerion's scripts?

    def __init__(self, root):
        self.root = Path(root)
        self.link: TcpLink = self.new_link()

    @property
    def output_dir(self) -> Path | None:
        """Its own folder, where it saves the phase masks it computes (None: not known)."""
        return self.root / self.OUTPUT_FOLDER if self.OUTPUT_FOLDER else None

    @property
    def supported(self) -> bool:
        """Plerion sees it run on this PC (Windows)."""
        return winproc.SUPPORTED

    def _missing(self, what: str):
        return NotImplementedError(f"{self.NAME}: {what} not known yet")

    def new_link(self) -> TcpLink:
        raise self._missing("its TCP link")

    # ------------------------------------------------------------------ the program
    def running(self) -> Process | None:
        """Its process doing the work, when it runs (from whichever install)."""
        return winproc.running([self.PROCESS]).get(self.PROCESS.lower()) if self.PROCESS else None

    def window_open(self, pid: int) -> bool:
        """The process ``pid`` shows its main window: started, ready."""
        return winproc.window_open(pid, self.WINDOW_TITLE)

    def install_problem(self, folder=None) -> str | None:
        """What keeps it from starting from ``folder`` (its root by default), if anything."""
        return None

    def saves_in(self) -> str | None:
        """Where the running one saves the masks it computes, as far as it says (None: not known)."""
        return None

    # ------------------------------------------------------------------ a protocol
    def prepare_script(self, masks: list[Path]) -> str:
        """Run once before a protocol showing ``masks`` (one per SLM trigger); its answer arms the protocol. By default
        the ping: nothing to prepare."""
        return self.PING

    def load_script(self, png: Path, k: int) -> str:
        """Show ``png`` on the SLM, mask ``k`` of the protocol's list (a version that preloaded the list shows its
        k-th)."""
        raise self._missing("its load script")

    # ------------------------------------------------------------------ its server switched on by Plerion (CAN_TICK)
    def tick(self, folder) -> int:
        """Have the Wavefront running from ``folder`` switch its server on: the id of the script doing it (its answer
        comes over TCP), or OSError."""
        raise self._missing("how to switch its server on")

    def tick_waiting(self, folder) -> bool:
        """The tick is still waiting to be taken."""
        return False

    def take_back_tick(self, folder):
        """Undo a tick not taken."""
