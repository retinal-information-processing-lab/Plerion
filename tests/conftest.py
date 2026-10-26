import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.wavefront import LinkError  # noqa: E402
from modules.wavefront.wf4.link import wrap  # noqa: E402


class FakeLink:
    """Wavefront IV's TCP server as Plerion sees it (wavefront.tcp.TcpLink): the scripts sent, in order (unwrapped),
    and their ids. A script answers at once while ``runs`` (Tcp server ticked), unless ``hold(js)`` says the test
    answers it itself (answer()). ``down``: not reachable. ``foreign``: other clients' answers, as the real link keeps
    them. Ported from Oriole TCP's tests (conftest.FakeLink)."""
    PORT = 59454

    def __init__(self, port_file=None):
        self.sent, self.sids, self.queue, self.foreign = [], [], [], []
        self.down, self.runs, self.hold = False, True, None
        self.port, self.connections, self.next_id = None, 0, 100

    def script(self, js: str) -> tuple[int, str]:
        self.next_id += 1
        return self.next_id, wrap(js, self.next_id)

    def send(self, js: str) -> int:
        if self.down:
            raise LinkError(f"Wavefront IV not reachable over TCP (port {self.PORT}): refused")
        if self.port is None:
            self.port, self.connections = self.PORT, self.connections + 1
        sid, _ = self.script(js)
        self.sent.append(js)
        self.sids.append(sid)
        if self.runs and not (self.hold and self.hold(js)):
            self.answer(sid)
        return sid

    def answer(self, sid: int | None = None, error: str = ""):
        """Wavefront ran script ``sid`` (the last one sent): DONE, or ERROR with ``error``."""
        if self.runs:
            self.queue.append(("ERROR" if error else "DONE", self.sids[-1] if sid is None else sid, error))

    def answers(self):
        out, self.queue = self.queue, []
        return out

    def close(self):
        self.port = None
