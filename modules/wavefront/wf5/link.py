"""Wavefront V's TCP server, as pythonToWfdVTcpCom.py (next to plerion_qtgui.py) talks to it: not tried on the rig yet.

Its port is the only thing in idv-photonics\\wfdV\\tcpPort.txt (in %APPDATA%; ~/.local/share on Linux). A message is
a magic number 0xABCDEF88, the length of the command, the UTF-8 command, then its CRC-16 (Qt's qChecksum), all
big-endian. A command is a call such as ``blobEditorSrv.drawSpot(x,y,z,d)``; a ``|`` after it makes it synchronous
(the next command waits for its end), as ``shapingAlgoLogic.proceedFullShapingAlgo()|``. The demo counts the length in
characters: the same as in bytes for an ASCII command, which every command is.

Still to find on the rig: what it answers, and how (decode, parse); how a script answers once it ran (wrap); whether
it ignores a message identical to the previous one, as Wavefront IV does.

Vendored from Oriole TCP (oriole/wavefront/wf5/link.py), unchanged.
"""
from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

from ..tcp import Answer, LinkError, TcpLink

_DATA = (Path(os.environ.get("APPDATA", Path.home())) if sys.platform == "win32"
         else Path.home() / ".local" / "share")
PORT_FILE = _DATA / "idv-photonics" / "wfdV" / "tcpPort.txt"
MAGIC = 0xABCDEF88
_CRC_TABLE = (0x0000, 0x1081, 0x2102, 0x3183, 0x4204, 0x5285, 0x6306, 0x7387,
              0x8408, 0x9489, 0xA50A, 0xB58B, 0xC60C, 0xD68D, 0xE70E, 0xF78F)


def crc16(data: bytes) -> int:
    """Qt's qChecksum (CRC-16-CCITT of ISO 3309, as pythonToWfdVTcpCom.py computes it)."""
    crc = 0xFFFF
    for c in data:
        crc = ((crc >> 4) & 0x0FFF) ^ _CRC_TABLE[(crc ^ c) & 15]
        crc = ((crc >> 4) & 0x0FFF) ^ _CRC_TABLE[(crc ^ (c >> 4)) & 15]
    return ~crc & 0xFFFF


def frame(command: str) -> bytes:
    """A message as Wavefront V reads it: magic, length, UTF-8 command, CRC-16."""
    data = command.encode("utf-8")
    return struct.pack(">II", MAGIC, len(data)) + data + struct.pack(">H", crc16(data))


def server_port(path=None) -> int:
    """The port Wavefront V's server listens on, from the file it writes."""
    path = Path(path or PORT_FILE)
    try:
        return int(path.read_text().split()[0])
    except (OSError, IndexError, ValueError) as e:
        raise LinkError(f"no Wavefront V server port in {path} ({e}): is Wavefront V running?") from e


class Wavefront5Link(TcpLink):
    NAME = "Wavefront V"

    def server_port(self) -> int:
        return server_port(self.port_file)

    encode = staticmethod(frame)

    def wrap(self, js: str, sid: int) -> str:
        raise NotImplementedError("Wavefront V: how a script answers is not known yet")

    def decode(self, buf: bytes) -> tuple[list[str], bytes]:
        raise NotImplementedError("Wavefront V: its answers are not known yet")

    def parse(self, text: str) -> Answer | None:
        raise NotImplementedError("Wavefront V: its answers are not known yet")
