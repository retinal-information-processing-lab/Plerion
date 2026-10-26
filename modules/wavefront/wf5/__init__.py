"""Wavefront V (wfdV, idv-photonics), driven over TCP: not ready yet ("wavefront": "V" in plerion_params.jsonc falls
back to Wavefront IV).

Known (pythonToWfdVTcpCom.py, next to plerion_qtgui.py): its port file and its message format (link). To make it
ready, found on the rig and filled in here, as Wavefront IV is in wf4 (slm.py and the window need nothing more):
1. its answers (link: wrap, decode, parse): what proves a script ran, and when it ended;
2. its program: process and window names (PROCESS, WINDOW_TITLE), where it saves the masks (OUTPUT_FOLDER, saves_in);
3. its protocol scripts: prepare_script, the protocol's masks fed to its SLM buffer once (hardwareSrv.feedSlmBuffer,
   as scripts/loadBufferSlm.js does), and load_script, the k-th one shown at its trigger
   (displaySlmDriver.displayImgIdx);
4. whether its server must be switched on (CAN_TICK, tick...);
5. then READY = True, and the IV | V switch in the window, as Oriole TCP's.

Vendored from Oriole TCP (oriole/wavefront/wf5/__init__.py), with Plerion's protocol scripts in the list above.
"""
from __future__ import annotations

from ..base import Wavefront
from . import link


class WavefrontV(Wavefront):
    KEY = "V"
    NAME = "Wavefront V"
    READY = False
    ROOT_KEY = "wfd5_root"

    def new_link(self) -> link.Wavefront5Link:
        return link.Wavefront5Link()
