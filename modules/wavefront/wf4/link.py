"""Wavefront IV's TCP server, as tried on the rig (by Oriole TCP).

With "Tcp server" ticked in Wavefront's script engine (Tools → Script engine; one source at a time with "auto-load"
and "Simple file", not remembered across restarts), every message is run as a script: the same JavaScript as a
test.js in its script folder. A message is a Qt QDataStream QByteArray, as arduinoReader sent it (captured on the
rig): its length (4 bytes, big-endian), then the UTF-8 script. Its server opens by itself at every start, listening on
every address, on a new port written after its IP in %TEMP%\\blueBoxServer.

As found on the rig (2026-10-25):
* Wavefront ignores a message identical to the one before it: its server keeps the last one (property clientMsg) and
  passes it on only when it changes. So every script is made unique (wrap: its id in it).
* It can answer: the script object (global ``scriptEngine``) has the server among its children, whose
  broadcastMessage(QString) sends a QDataStream QString (its length in bytes, then UTF-16, big-endian) to every client.
  So every script ends saying "PLERION DONE <id>", or "PLERION ERROR <id> <error>": what ran, and when it ended.
  Oriole TCP's scripts say "ORIOLE ..." instead: each program reads its own answers.
* One connection, kept: Wavefront (Qt 4) runs a script inside the read of its connection, and Qt reads that connection
  again only once the script has ended. A script sent on a second connection while one ran crashed it (QtScript4.dll).
  Plerion sends a script only once the last one answered (or never will).
* A connection made before Tcp server was ticked runs scripts once it is.

Vendored from Oriole TCP (oriole/wavefront/wf4/link.py); Plerion's change: its answers (REPLY, __plerion).
"""
from __future__ import annotations

import struct
import tempfile
from pathlib import Path

from ..tcp import Answer, LinkError, TcpLink

PORT_FILE = Path(tempfile.gettempdir()) / "blueBoxServer"
REPLY = "PLERION"           # what Plerion's scripts answer: PLERION DONE <id> / PLERION ERROR <id> <error>
_ANSWER = ('function __plerion(m) { var k = scriptEngine.findChildren(); for (var i = 0; i < k.length; i++) '
           '{ if (typeof k[i].broadcastMessage == "function") { k[i].broadcastMessage(m); return; } } }\n')


def server_port(path=None) -> int:
    """The port Wavefront IV's server listens on, from the file it writes at every start (IP, then port)."""
    path = Path(path or PORT_FILE)
    try:
        return int(path.read_text().split()[1])
    except (OSError, IndexError, ValueError) as e:
        raise LinkError(f"no Wavefront IV server port in {path} ({e}): is Wavefront IV running?") from e


def frame(js: str) -> bytes:
    """A message as Wavefront IV reads it: a QDataStream QByteArray (length, then the UTF-8 script)."""
    data = js.encode("utf-8")
    return struct.pack(">I", len(data)) + data


def wrap(js: str, sid: int) -> str:
    """``js`` as script ``sid``: answering PLERION DONE <sid> once it ran, PLERION ERROR <sid> <error> if it failed."""
    return (f"{_ANSWER}try {{\n{js}\n__plerion(\"{REPLY} DONE {sid}\");\n}} catch (e) "
            f"{{ __plerion(\"{REPLY} ERROR {sid} \" + e); }}\n")


def read_answers(buf: bytes) -> tuple[list[str], bytes]:
    """The QDataStream QStrings complete in ``buf`` (Wavefront's broadcastMessage), and what is left of it."""
    texts = []
    while len(buf) >= 4:
        n = struct.unpack(">I", buf[:4])[0]
        if n == 0xFFFFFFFF:                             # a null QString
            texts.append("")
            buf = buf[4:]
            continue
        if len(buf) < 4 + n:
            break
        texts.append(buf[4:4 + n].decode("utf-16-be", "replace"))
        buf = buf[4 + n:]
    return texts, buf


def parse_answer(text: str) -> Answer | None:
    """(DONE | ERROR, id, error) from an answer of Plerion's scripts; None for anything else."""
    parts = text.split(" ", 3)
    if len(parts) < 3 or parts[0] != REPLY or parts[1] not in ("DONE", "ERROR") or not parts[2].isdigit():
        return None
    return Answer(parts[1], int(parts[2]), parts[3] if len(parts) > 3 else "")


class Wavefront4Link(TcpLink):
    NAME = "Wavefront IV"

    def server_port(self) -> int:
        return server_port(self.port_file)

    encode = staticmethod(frame)
    wrap = staticmethod(wrap)
    decode = staticmethod(read_answers)
    parse = staticmethod(parse_answer)
