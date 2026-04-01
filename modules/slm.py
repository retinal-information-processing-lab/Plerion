# Branch 3 — SLM phase mask switching
# TCP client for WaveFront IV.  Sends the next phase mask path over TCP on each
# DMD trigger where vec_col_slm == 1.

import socket
import threading


class SLMClient:
    """TCP client for WaveFront IV phasemask switching."""

    def __init__(self, host: str, port: int, timeout: float = 2.0):
        self._host    = host
        self._port    = port
        self._timeout = timeout
        self._sock    = None
        self._lock    = threading.Lock()

    @property
    def is_connected(self) -> bool:
        return self._sock is not None

    def connect(self) -> bool:
        """Try to open TCP connection. Returns True on success."""
        with self._lock:
            self._close_socket()
            if not self._host:
                return False
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(self._timeout)
                s.connect((self._host, self._port))
                self._sock = s
                return True
            except OSError:
                return False

    def disconnect(self) -> None:
        with self._lock:
            self._close_socket()

    def send_mask(self, path: str) -> bool:
        """Send phasemask path terminated with newline. Returns True on success."""
        with self._lock:
            if self._sock is None:
                return False
            try:
                self._sock.sendall((path + '\n').encode('utf-8'))
                return True
            except OSError:
                self._close_socket()
                return False

    def _close_socket(self):
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
