"""slm.py without the window (no Qt): order files and masks found by name, and SlmDriver driving a pretend Wavefront
(tests.conftest.FakeLink): Wavefront watched and pinged, a protocol armed, one mask loaded per SLM trigger."""
import ntpath
from pathlib import Path

import pytest

from modules import slm
from modules.wavefront import Process, Wavefront
from tests.conftest import FakeLink


class Pretend(Wavefront):
    """A Wavefront on a pretend PC: running from its root, ready; its server FakeLink."""
    KEY, NAME, READY = "T", "Wavefront T", True
    OUTPUT_FOLDER = "GeneratedPhasemasks"
    SCRIPTS_HINT = "switch its server on"
    supported = True
    saved_in = None
    proc = Process(7, None)

    def new_link(self):
        return FakeLink()

    def running(self):
        return self.proc

    def window_open(self, pid):
        return True

    def saves_in(self):
        return self.saved_in

    def prepare_script(self, masks):
        return f"prepare {len(masks)}"

    def load_script(self, png, k):
        return f"load {Path(png).name}"


class Ticking(Pretend):
    """One whose server Plerion switches on itself (as Wavefront IV, through its script folder)."""
    CAN_TICK, SERVER, TICK_VIA, TICK_NOT_TAKEN = True, "Tcp server", "script dropped", "not in auto-load mode"

    def tick(self, folder):
        sid, _ = self.link.script("tick")
        return sid


class View:
    def __init__(self):
        self.lines, self.armed, self.loaded, self.changes = [], [], [], 0

    def log(self, text, level="info"):
        self.lines.append((level, text))

    def wavefront_changed(self):
        self.changes += 1

    def slm_armed(self, ok, why):
        self.armed.append((ok, why))

    def slm_loaded(self, event, k, ok, ms, late):
        self.loaded.append((event, k, ok, late))


def _masks(folder: Path, n: int) -> list:
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for i in range(1, n + 1):
        p = folder / f"Pattern{i}_000.algoPhp.png"
        p.write_bytes(b"png")
        paths.append(p)
    return paths


def _started(wf, view):
    """Wavefront seen running and ready, then pinged FIRST_CHECK_S later."""
    d = slm.SlmDriver(wf, view, load_timeout_s=2.0)
    d.watch()
    d.check_at -= slm.FIRST_CHECK_S
    d.poll()
    return d


@pytest.fixture
def driver(tmp_path):
    view = View()
    return _started(Pretend(tmp_path / "wfdT"), view), view


def _armed(d, view, masks, budgets=None):
    """A protocol armed; from then on the test answers each load itself."""
    d.arm(masks, budgets or [10.0] * (len(masks) + 1))
    d.poll()
    assert view.armed[-1] == (True, "") and d.protocol.armed
    d.wf.link.hold = lambda js: js.startswith("load")


def test_order_file_and_masks_found_by_name(tmp_path):
    """Order files keep the paths of the PC that wrote them: each mask is found by name in the session's folder, else
    at the path written; found nowhere, listed."""
    session = tmp_path / "D" / "exp" / "Phasemasks"
    _masks(session, 2)
    elsewhere = tmp_path / "wfdIV_old" / "GeneratedPhasemasks"
    elsewhere.mkdir(parents=True)
    (elsewhere / "Pattern9_000.algoPhp.png").write_bytes(b"png")
    order = tmp_path / "DigitalHolography_004spots_20rep_PhaseMasksOrder.txt"
    order.write_bytes(b"---- This line will not be read ---- \r\n"
                      b"E:/wfdIV_20241023/GeneratedPhasemasks/Pattern2_000.algoPhp.png\r\n"
                      b"C:\\Users\\User\\Pattern1_000.algoPhp.png\r\n"
                      b"\r\n"
                      + str(elsewhere / "Pattern9_000.algoPhp.png").encode() + b"\r\n"
                      b"C:/Users/User/Pattern7_000.algoPhp.png\r\n")
    lines = slm.read_order_file(order)
    assert [ntpath.basename(line) for line in lines] == [
        "Pattern2_000.algoPhp.png", "Pattern1_000.algoPhp.png", "Pattern9_000.algoPhp.png", "Pattern7_000.algoPhp.png"]
    paths, missing = slm.resolve_masks(lines, str(session))
    assert paths == [session / "Pattern2_000.algoPhp.png", session / "Pattern1_000.algoPhp.png",
                     elsewhere / "Pattern9_000.algoPhp.png", None]
    assert missing == ["Pattern7_000.algoPhp.png"]

    order.write_text("### This row is not read ###\nC:/Users/User/Pattern1_000.algoPhp.png\n")   # the other header
    assert slm.read_order_file(order) == ["C:/Users/User/Pattern1_000.algoPhp.png"]
    assert slm.resolve_masks(["C:/Users/User/Pattern1_000.algoPhp.png"], "") == ([None], ["Pattern1_000.algoPhp.png"])


def test_default_mask_folder(tmp_path):
    """Where Wavefront saves the masks it computes: as its settings say, else its install's GeneratedPhasemasks."""
    wf = Pretend(tmp_path / "wfdT")
    own = str(tmp_path / "wfdT" / "GeneratedPhasemasks")
    assert slm.default_mask_folder(wf) == own
    wf.saved_in = str(tmp_path / "gone")
    assert slm.default_mask_folder(wf) == own
    (tmp_path / "saved").mkdir()
    wf.saved_in = str(tmp_path / "saved")
    assert slm.default_mask_folder(wf) == str(tmp_path / "saved")


def test_pinged_once_ready(driver):
    d, view = driver
    assert d.runs_scripts and d.status() == ("Wavefront T: TCP ✓ (port 59454)", "ok")
    assert view.lines[-1] == ("info", "[SLM] Wavefront T runs Plerion's scripts (port 59454)")
    assert d.wf.link.sent == [""] and not d.active and d.busy() is None


def test_no_answer_no_ping_on_its_own(tmp_path):
    """Not answered: said, and not pinged again on its own (a ping landing while Oriole's script runs could crash
    Wavefront); Check pings it again."""
    view, wf = View(), Pretend(tmp_path / "wfdT")
    wf.link.runs = False
    d = _started(wf, view)
    d.waiting.sent -= slm.PING_WAIT_S
    d.poll()
    assert d.runs_scripts is False and d.waiting is None
    assert view.lines[-1] == ("error", "[SLM] Wavefront T does not run Plerion's scripts: switch its server on, then "
                                       "press Check")
    assert d.status() == ("Wavefront T: no answer (tick TCP server, then Check)", "error")
    for _ in range(3):
        d.watch()
        d.poll()
    assert wf.link.sent == [""]
    wf.link.runs = True
    d.check()
    d.poll()
    assert d.runs_scripts and wf.link.sent == ["", ""]


def test_server_ticked_when_not_answering(tmp_path):
    view, wf = View(), Ticking(tmp_path / "wfdT")
    wf.link.runs = False
    d = _started(wf, view)
    d.waiting.sent -= slm.PING_WAIT_S
    d.poll()                                            # not answered: ticked
    assert d.waiting.kind == "tick" and d.status() == ("Wavefront T: ticking its Tcp server…", "warn")
    wf.link.runs = True
    wf.link.answer(d.waiting.sid)
    d.poll()
    assert d.runs_scripts and view.lines[-1][1].startswith("[SLM] Tcp server ticked by Plerion")


def test_closed_then_started_again(driver):
    d, view = driver
    d.wf.proc = None
    d.watch()
    assert d.status() == ("Wavefront T: not running", "dim") and d.wf.link.port is None
    assert d.not_ready() == "Wavefront T is not running: start it (Oriole TCP does), then RUN again"
    d.wf.proc = Process(8, None)                        # started again: a new process, pinged once ready
    d.watch()
    d.check_at -= slm.FIRST_CHECK_S
    d.poll()
    assert d.runs_scripts and d.wf.link.sent == ["", ""] and d.not_ready() is None


def test_a_protocol_one_mask_at_a_time(driver, tmp_path):
    d, view = driver
    link = d.wf.link
    masks = _masks(tmp_path / "Phasemasks", 3)
    d.arm(masks, [5.25, 0.5, 0.5])
    assert link.sent[-1] == "prepare 3" and d.active and d.busy() == "a protocol is running"
    d.poll()
    assert view.armed == [(True, "")]
    link.hold = lambda js: js.startswith("load")
    d.show(1)
    assert link.sent[-1] == "load Pattern1_000.algoPhp.png"
    d.show(2)                                           # trigger 1's mask not answered yet: trigger 2 waits...
    d.show(3)                                           # ... replaced by trigger 3 (skipped, said)
    assert link.sent[-1] == "load Pattern1_000.algoPhp.png" and d.protocol.pending == 3
    assert view.lines[-1] == ("error", "[SLM] Trigger 2: skipped, trigger 3 came before the mask of trigger 1 answered")
    link.answer(link.sids[-1])
    d.poll()                                            # trigger 1 loaded, then trigger 3's mask sent
    assert view.loaded == [(1, 0, True, False)] and link.sent[-1] == "load Pattern3_000.algoPhp.png"
    assert view.lines[-1][1].startswith("[SLM] Trigger 1: Pattern1_000.algoPhp.png loaded (1/3, ")
    link.answer(link.sids[-1])
    d.poll()
    assert view.loaded[-1] == (3, 2, True, False)
    d.finish()
    assert view.lines[-1][0] == "warn"
    assert view.lines[-1][1].startswith("[SLM] 3 SLM triggers: 2 loaded, 0 failed, 0 late, 1 skipped")
    assert not d.active and d.busy() is None


def test_late_failed_timed_out_and_gone(driver, tmp_path):
    """Problems during a protocol: logged in red (or yellow when late) with the trigger and the mask, and it goes on."""
    d, view = driver
    link = d.wf.link
    masks = _masks(tmp_path / "Phasemasks", 4)
    _armed(d, view, masks, [0.5, 0.5, 0.5, 0.5])
    d.show(1)
    d.protocol.in_flight.sent -= 0.6                    # answered 600 ms after it was sent: after the shutter opened
    link.answer(link.sids[-1])
    d.poll()
    assert view.loaded[-1] == (1, 0, True, True) and view.lines[-1][0] == "warn" and "LATE" in view.lines[-1][1]
    d.show(2)
    link.answer(link.sids[-1], error="ReferenceError: x")
    d.poll()
    assert view.loaded[-1] == (2, 1, False, False)
    assert view.lines[-1] == ("error", "[SLM] Trigger 2: Pattern2_000.algoPhp.png NOT loaded (Wavefront's script failed: "
                                       "ReferenceError: x): the SLM still shows the previous mask")
    d.show(3)
    d.protocol.in_flight.sent -= d.load_timeout_s       # no answer in time
    d.poll()
    assert view.loaded[-1] == (3, 2, False, False) and "no answer within 2 s" in view.lines[-1][1]
    assert d.runs_scripts is False
    masks[3].unlink()                                   # deleted after RUN: nothing sent (it would load nothing)
    sent = len(link.sent)
    d.show(4)
    assert len(link.sent) == sent and view.loaded[-1] == (4, 3, False, False)
    assert "the file is gone, deleted or moved since RUN; nothing sent" in view.lines[-1][1]
    d.finish()
    assert view.lines[-1][1].startswith("[SLM] 4 SLM triggers: 1 loaded, 3 failed, 1 late, 0 skipped")


def test_the_list_wraps(driver, tmp_path):
    """More SLM triggers than masks (the DH vecs have one more): the list starts again, as arduinoReader's did."""
    d, view = driver
    _armed(d, view, _masks(tmp_path / "Phasemasks", 2))
    d.wf.link.hold = None                               # every load answered at once
    for event in (1, 2, 3):
        d.show(event)
        d.poll()
    assert [s for s in d.wf.link.sent if s.startswith("load")] == [
        "load Pattern1_000.algoPhp.png", "load Pattern2_000.algoPhp.png", "load Pattern1_000.algoPhp.png"]
    assert [x[:3] for x in view.loaded] == [(1, 0, True), (2, 1, True), (3, 0, True)]


def test_not_armed(driver, tmp_path):
    d, view = driver
    link = d.wf.link
    masks = _masks(tmp_path / "Phasemasks", 2)
    link.runs = False                                   # not answered in time
    d.arm(masks, [1.0, 1.0])
    d.waiting.sent -= slm.PREPARE_WAIT_S
    d.poll()
    assert view.armed[-1] == (False, "Wavefront T did not answer within 5 s (switch its server on, then press Check)")
    assert d.protocol is None and d.runs_scripts is False
    link.runs, link.hold = True, (lambda js: js.startswith("prepare"))
    d.arm(masks, [1.0, 1.0])                            # its preparation failed
    link.answer(link.sids[-1], error="boom")
    d.poll()
    assert view.armed[-1] == (False, "Wavefront's preparation script failed: boom") and d.protocol is None
    link.down = True                                    # not reachable
    d.arm(masks, [1.0, 1.0])
    assert view.armed[-1][0] is False and "not reachable over TCP" in view.armed[-1][1] and d.protocol is None
    assert d.status() == ("Wavefront T: TCP server not reachable", "error")


def test_stopped_while_arming(driver, tmp_path):
    """STOP before the preparation answered: nothing sent until it does, and its answer then arms nothing."""
    d, view = driver
    link = d.wf.link
    link.hold = lambda js: js.startswith("prepare")
    d.arm(_masks(tmp_path / "Phasemasks", 2), [1.0, 1.0])
    d.cancel()
    assert d.busy() == "Wavefront has not answered the last script yet"
    link.answer(link.sids[-1])
    d.poll()
    assert view.armed == [] and d.protocol is None and d.busy() is None


def test_another_program_running_scripts(driver, tmp_path):
    """Oriole TCP's answers reach Plerion too: Plerion then sends nothing on its own for a moment, and says it during
    a protocol (once)."""
    d, view = driver
    d.wf.link.foreign.append("ORIOLE DONE 5")
    d.poll()
    assert d.busy() == "another program (Oriole TCP?) is running scripts in Wavefront" and d.not_ready() == d.busy()
    d.other_at -= slm.OTHER_CLIENT_S
    assert d.busy() is None
    _armed(d, view, _masks(tmp_path / "Phasemasks", 2))
    for n in (6, 7):
        d.wf.link.foreign.append(f"ORIOLE DONE {n}")
        d.poll()
    said = [text for level, text in view.lines if "Another program ran a script" in text]
    assert len(said) == 1 and "ORIOLE DONE 6" in said[0]
