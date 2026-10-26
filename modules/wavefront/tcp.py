"""A Wavefront's TCP server, as Plerion talks to it, whatever the version: what was learnt on the rig with Wavefront IV
(by Oriole TCP).

* Its port is read from the file Wavefront writes at every start, before every send: a new port says it restarted. The
  file can outlive Wavefront: a refused connection then says it is not running.
* One connection, kept, and made again only when it broke or Wavefront restarted (one connection per script crashed
  Wavefront IV). What Wavefront sent is read before every send: answers left unread make a closed connection look open.
* A short connect timeout: on Windows a refused connection to this PC takes the whole timeout to fail.
* Every script carries an id of its own and ends answering with it (wrap), so that its answer says what ran and when it
  ended; scripts are sent one at a time by slm.SlmDriver, the next only once the last answered.
* Wavefront sends every answer to every client connected: other clients' answers (Oriole TCP's) are kept in
  ``foreign``, to know another program is running scripts in Wavefront.

A version (TcpLink subclass) says where its port is, how a message is framed, how a script answers and how its answers
read: server_port, encode, wrap, decode, parse.

Vendored from Oriole TCP (oriole/wavefront/tcp.py); Plerion's change: ``foreign``.
"""
from __future__ import annotations

import socket
import time
from typing import NamedTuple


class LinkError(RuntimeError):
    """Wavefront's server cannot be reached."""


class Answer(NamedTuple):
    kind: str                       # "DONE" or "ERROR"
    sid: int                        # the id of the script answering
    error: str = ""                 # Wavefront's message, for an ERROR


class TcpLink:
    """The connection to a Wavefront's TCP server: made when first needed, made again when it broke or Wavefront
    restarted. Scripts go wrapped, each with an id of its own; their answers are read by answers()."""

    NAME = "Wavefront"              # in the messages
    CONNECT_S = 0.5                 # Wavefront on this PC accepts at once; a refused connection takes 2 s to fail
    TIMEOUT_S = 2.0

    def __init__(self, port_file=None):
        self.port_file = port_file                  # None: the version's own
        self.port: int | None = None
        self.connections = 0                        # connections made so far
        self.foreign: list[str] = []                # other clients' answers, read by answers(), not taken yet
        self._sock: socket.socket | None = None
        self._buf = b""                             # what came, not a whole message yet
        self._texts: list[str] = []                 # what came, whole, not read by answers() yet
        self._next_id = int(time.time() * 1000) % 10**9     # unique across Plerion's runs too

    # ------------------------------------------------------------------ what a version defines
    def server_port(self) -> int:
        """The port its server listens on now (LinkError when it cannot be read)."""
        raise NotImplementedError

    def encode(self, script: str) -> bytes:
        """A message as Wavefront reads it."""
        raise NotImplementedError

    def wrap(self, js: str, sid: int) -> str:
        """``js`` as script ``sid``: answering once it ran, or failed."""
        raise NotImplementedError

    def decode(self, buf: bytes) -> tuple[list[str], bytes]:
        """The messages complete in what Wavefront sent, and what is left of it."""
        raise NotImplementedError

    def parse(self, text: str) -> Answer | None:
        """The answer of one of Plerion's scripts in a message; None for anything else."""
        raise NotImplementedError

    # ------------------------------------------------------------------ the same for every version
    def script(self, js: str) -> tuple[int, str]:
        """``js`` as a new script (wrap), and its id: also for one that goes another way (Wavefront IV's script
        folder); its answer still comes here."""
        self._next_id += 1
        return self._next_id, self.wrap(js, self._next_id)

    def send(self, js: str) -> int:
        """Send ``js`` as a new script: its id, or LinkError when Wavefront cannot be reached."""
        sid, script = self.script(js)
        data = self.encode(script)
        for attempt in (1, 2):                      # a connection found dead while sending is made again once
            sock = self._connected()
            try:
                sock.sendall(data)
                return sid
            except OSError as e:
                self.close()
                if attempt == 2:
                    raise LinkError(f"{self.NAME} not reachable over TCP (port {self.port}): {e}") from e

    def answers(self) -> list[Answer]:
        """The answers of Plerion's scripts arrived since the last call, without waiting; anything else that came
        (other clients' answers) added to ``foreign``."""
        if self._sock is not None and not self._drain():
            self.close()
        texts, self._texts = self._texts, []
        found = []
        for text in texts:
            answer = self.parse(text)
            if answer is None:
                self.foreign.append(text)
            else:
                found.append(answer)
        return found

    def close(self):
        """Hang up; the answers already arrived are kept for answers()."""
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        self._sock, self._buf = None, b""

    def _drain(self) -> bool:
        """Read what Wavefront sent, without waiting (kept for answers()): False when the connection is closed or
        broken."""
        alive = True
        try:
            self._sock.setblocking(False)
            while True:
                data = self._sock.recv(65536)
                if not data:                            # closed by Wavefront
                    alive = False
                    break
                self._buf += data
        except BlockingIOError:
            pass
        except OSError:
            alive = False
        finally:
            self._sock.settimeout(self.TIMEOUT_S)
        texts, self._buf = self.decode(self._buf)
        self._texts += texts
        return alive

    def _connected(self) -> socket.socket:
        port = self.server_port()
        if self._sock is not None and (port != self.port or not self._drain()):
            self.close()                                # Wavefront restarted, or closed the connection
        if self._sock is None:
            self.port = port
            try:
                self._sock = socket.create_connection(("127.0.0.1", port), timeout=self.CONNECT_S)
            except OSError as e:
                raise LinkError(f"{self.NAME} not reachable over TCP (port {port}): {e}") from e
            self._sock.settimeout(self.TIMEOUT_S)
            self.connections += 1
        return self._sock
