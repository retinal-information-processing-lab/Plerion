# Branch 3 — SLM phase masks
# Wavefront (modules/wavefront) shows the phase masks on the SLM. Plerion drives it over its TCP server, as Oriole TCP
# does: one connection, one script at a time, every script answering once it ran (two scripts running at once, sent
# on two connections, crashed Wavefront IV).
# read_order_file / resolve_masks: the masks of a protocol, found by file name in the session's phase masks folder.
# SlmDriver: Wavefront watched, a protocol armed, the next mask loaded at each SLM trigger (arduinoReader's old job).

from __future__ import annotations

import math
import ntpath
import os
import time
from dataclasses import dataclass
from pathlib import Path

from .wavefront import LinkError, Wavefront

FIRST_CHECK_S  = 2.0   # Wavefront ready (its window open): pinged this long after
PING_WAIT_S    = 2.0   # a ping not answered this long: Wavefront does not run scripts (its server not on)
TICK_WAIT_S    = 5.0   # the tick of its server not answered this long: not taken
PREPARE_WAIT_S = 5.0   # the script arming a protocol not answered this long: not armed
OTHER_CLIENT_S = 3.0   # another program's script answered this recently: Wavefront is busy for it


# ── order files ──────────────────────────────────────────────────────────────

def read_order_file(path) -> list:
    """Return the phase masks of an order file, in order: its lines naming a .png.

    The header line ('---- This line will not be read ----', '### This row is not read ###') and blank lines are
    left out.
    """
    with open(path, 'r', errors='replace') as f:
        lines = [line.strip() for line in f]
    return [line for line in lines if line.lower().endswith('.png')]


def resolve_masks(lines: list, folder: str) -> tuple:
    """Return (paths, missing): where each mask of an order file is, and the file names found nowhere.

    Order files keep the paths of the PC and the Wavefront install that wrote them, so each mask is looked for by
    file name in ``folder`` first (the session's phase masks, where Oriole TCP stores them), then at the path as
    written. A mask found nowhere is None in ``paths``.
    """
    paths, missing = [], []
    for line in lines:
        name = ntpath.basename(line)                    # either slash
        candidates = ([Path(folder) / name] if folder else []) + [Path(line)]
        found = next((p for p in candidates if p.is_file()), None)
        paths.append(found)
        if found is None:
            missing.append(name)
    return paths, missing


def default_mask_folder(wf: Wavefront) -> str:
    """Return where Wavefront saves the masks it computes: the folder its settings name (wfdIV.ini rootPath), else
    its install's own (GeneratedPhasemasks); '' when neither is known."""
    saved = wf.saves_in()
    if saved and os.path.isdir(saved):
        return os.path.normpath(saved)
    return str(wf.output_dir) if wf.output_dir else ''


# ── SlmDriver ────────────────────────────────────────────────────────────────

@dataclass
class Waiting:
    """A ping, the tick of Wavefront's server or the script arming a protocol, not answered yet."""
    kind: str                       # 'ping', 'tick' or 'prepare'
    sid: int
    sent: float
    say: bool = False               # ping: its answer logged
    folder: Path | None = None      # tick: the install whose script folder holds it


@dataclass
class Load:
    """The mask of an SLM trigger, sent, not answered yet."""
    event: int                      # the SLM trigger: 1, 2, ...
    k: int                          # the mask: its index in the protocol's list
    sid: int
    sent: float


@dataclass
class Protocol:
    """A protocol showing ``masks``, one per SLM trigger (the list wraps); ``budgets``: for each trigger, the seconds
    until the shutter opens."""
    masks: list
    budgets: list
    armed: bool = False
    in_flight: Load | None = None
    pending: int | None = None      # the latest trigger come while a load was in flight
    events: int = 0                 # SLM triggers so far
    loaded: int = 0
    failed: int = 0
    late: int = 0
    skipped: int = 0
    slowest_ms: float = 0.0
    other_said: bool = False        # another program's scripts during it, said once


class SlmDriver:
    """Wavefront on the SLM, one script at a time.

    The window (``view``) calls watch() every second and poll() every 100 ms (10 ms during a protocol), and is told:
      view.log(text, level)
      view.wavefront_changed()                  — status() to show again
      view.slm_armed(ok, why)                   — arm() answered
      view.slm_loaded(event, k, ok, ms, late)   — the mask of an SLM trigger loaded, or not
    """

    def __init__(self, wf: Wavefront, view, load_timeout_s: float = 2.0):
        self.wf = wf
        self.view = view
        self.log = view.log
        self.load_timeout_s = load_timeout_s
        self.pid = None             # Wavefront's process: another one, another server and tick
        self.folder = None          # the install it runs from
        self.ready = False          # its window is open
        self.check_at = None        # its first ping, due then
        self.port = None            # the port it was last reached on
        self.reachable = None       # its server reached (None: not tried yet)
        self.runs_scripts = None    # it runs Plerion's scripts: they answer (None: not tried yet)
        self.waiting = None         # a ping, tick or preparation, not answered yet
        self.tick_tried = False     # Plerion tried to switch this Wavefront's server on
        self.other_at = 0.0         # time.time() another program's script last answered
        self.protocol = None        # the protocol armed, or being armed

    # ── state ──

    @property
    def active(self) -> bool:
        """A protocol is armed or being armed: poll() wanted often."""
        return self.protocol is not None

    def status(self) -> tuple:
        """The Wavefront line of the status bar: (text, tone), tone 'dim', 'warn', 'error' or 'ok'."""
        name = self.wf.NAME
        if not self.wf.supported:
            return f'{name}: not watched (not Windows)', 'dim'
        if self.folder is None:
            return f'{name}: not running', 'dim'
        if not self.ready:
            return f'{name}: starting…', 'warn'
        if self.reachable is False:
            return f'{name}: TCP server not reachable', 'error'
        if self.waiting is not None and self.waiting.kind == 'tick':
            return f'{name}: ticking its {self.wf.SERVER}…', 'warn'
        if self.runs_scripts:
            return f'{name}: TCP ✓ (port {self.port})', 'ok'
        if self.runs_scripts is False:
            return f'{name}: no answer (tick {self.wf.SERVER}, then Check)', 'error'
        return f'{name}: running', 'warn'

    def busy(self) -> str | None:
        """Why no script can be sent now (None: one can)."""
        if self.protocol is not None:
            return 'a protocol is running'
        if self.waiting is not None:
            return 'Wavefront has not answered the last script yet'
        if time.time() - self.other_at < OTHER_CLIENT_S:
            return 'another program (Oriole TCP?) is running scripts in Wavefront'
        return None

    def not_ready(self) -> str | None:
        """Why a protocol cannot be armed now (None: it can)."""
        wf = self.wf
        if wf.supported and wf.running() is None:
            return f'{wf.NAME} is not running: start it (Oriole TCP does), then RUN again'
        return self.busy()

    # ── Wavefront watched ──

    def watch(self):
        """Every second: is Wavefront running, from which install, its window open (ready). Once ready it is pinged,
        FIRST_CHECK_S later, and then no more on its own: Oriole TCP pings every few seconds while Wavefront does not
        answer, but a ping landing while Oriole's script runs could crash Wavefront. Check pings it again."""
        wf = self.wf
        if not wf.supported:
            return
        proc = wf.running()
        pid = proc.pid if proc else None
        if pid != self.pid:                         # closed, or another one started: a new port, a new tick
            if self.waiting is not None and self.waiting.kind != 'prepare':
                self._drop_waiting()
            self.pid, self.port, self.reachable, self.runs_scripts, self.tick_tried = pid, None, None, None, False
            self.ready, self.check_at = False, None
            wf.link.close()
        ready = proc is not None and wf.window_open(proc.pid)
        if ready and not self.ready and self.runs_scripts is None:
            self.check_at = time.time() + FIRST_CHECK_S
        self.folder = (proc.folder or wf.root) if proc else None
        self.ready = ready
        self.view.wavefront_changed()

    def check(self):
        """Ping Wavefront (Check): answered, it runs Plerion's scripts; not, its server ticked (once more)."""
        wf = self.wf
        if wf.supported and wf.running() is None:
            self.log(f'[SLM] {wf.NAME} is not running', 'warn')
            return
        why = self.busy()
        if why:
            self.log(f'[SLM] Not now: {why}', 'warn')
            return
        self.tick_tried = False
        self.ping(say=True)

    def ping(self, say: bool = False):
        """A script doing nothing, to know whether Wavefront runs Plerion's scripts; ``say``: its answer logged."""
        sid, error = self._send(self.wf.PING)
        if error:
            self.log(f'[SLM] {error}', 'error')
            return
        self.waiting = Waiting('ping', sid, time.time(), say=say)

    def poll(self):
        """The first ping when due; Wavefront's answers, and other programs'; what waits for an answer too long."""
        now = time.time()
        if self.check_at is not None and now >= self.check_at:
            self.check_at = None
            if self.ready and self.runs_scripts is None:
                if self.busy():
                    self.check_at = now + FIRST_CHECK_S     # later: nothing sent while another script may run
                else:
                    self.ping(say=True)
        link = self.wf.link
        for kind, sid, error in link.answers():
            self._on_answer(kind, sid, error)
        if link.foreign:
            texts, link.foreign = link.foreign, []
            self._on_foreign(texts)
        if self.waiting is not None:
            self._waiting_too_long()
        p = self.protocol
        if p is not None and p.in_flight is not None and time.time() - p.in_flight.sent >= self.load_timeout_s:
            self._answering(False)
            self._load_failed(f'no answer within {self.load_timeout_s:g} s')

    def close(self):
        """Plerion closes: a tick not taken undone, the connection closed."""
        self.protocol = None
        self._drop_waiting()
        self.wf.link.close()

    # ── a protocol ──

    def arm(self, masks: list, budgets: list):
        """Arm a protocol showing ``masks`` (one per SLM trigger; ``budgets``: for each trigger, the seconds until the
        shutter opens): Wavefront prepared (wf.prepare_script), armed once that script answered. The view is told
        slm_armed(True, '') then, or slm_armed(False, why)."""
        self.protocol = Protocol(list(masks), list(budgets))
        sid, error = self._send(self.wf.prepare_script(self.protocol.masks))
        if error:
            self.protocol = None
            self.view.slm_armed(False, error)
            return
        self.waiting = Waiting('prepare', sid, time.time())

    def cancel(self):
        """The protocol given up while being armed (STOP): its preparation, still awaited, then does nothing."""
        self.protocol = None

    def show(self, event: int):
        """SLM trigger ``event`` (1, 2, ...): its mask loaded, masks[(event - 1) % n] (the list wraps, as arduinoReader's
        did). One load at a time: a trigger coming while one is in flight waits for its answer (pending), the latest
        one only."""
        p = self.protocol
        if p is None or not p.armed or not p.masks:
            return
        p.events = max(p.events, event)
        if p.in_flight is None:
            self._send_load(event)
            return
        if p.pending is not None:
            p.skipped += 1
            self.log(f'[SLM] Trigger {p.pending}: skipped, trigger {event} came before the mask of trigger '
                     f'{p.in_flight.event} answered', 'error')
        p.pending = event

    def finish(self):
        """The protocol ended: its summary logged (a load still in flight is not counted); Plerion free again."""
        p, self.protocol = self.protocol, None
        if p is None or not p.armed:
            return
        trouble = p.failed or p.late or p.skipped
        self.log(f'[SLM] {p.events} SLM triggers: {p.loaded} loaded, {p.failed} failed, {p.late} late, '
                 f'{p.skipped} skipped (slowest {p.slowest_ms:.0f} ms)', 'warn' if trouble else 'info')

    def _send_load(self, event: int):
        p = self.protocol
        k = (event - 1) % len(p.masks)
        png = p.masks[k]
        if png is None or not png.is_file():        # it would load nothing, and might still answer DONE
            self._failed(event, k, 'the file is gone, deleted or moved since RUN; nothing sent')
            return
        sid, error = self._send(self.wf.load_script(png, k))
        if error:
            self._failed(event, k, error)
            return
        p.in_flight = Load(event, k, sid, time.time())

    def _loaded(self):
        p = self.protocol
        load, p.in_flight = p.in_flight, None
        ms = (time.time() - load.sent) * 1000
        budget = p.budgets[load.event - 1] if load.event <= len(p.budgets) else math.inf
        late = ms > budget * 1000
        p.loaded += 1
        p.slowest_ms = max(p.slowest_ms, ms)
        name = self._mask_name(load.k)
        if late:
            p.late += 1
            self.log(f'[SLM] Trigger {load.event}: {name} loaded LATE ({ms:.0f} ms; the shutter opened after '
                     f'{budget * 1000:.0f} ms)', 'warn')
        else:
            self.log(f'[SLM] Trigger {load.event}: {name} loaded ({load.k + 1}/{len(p.masks)}, {ms:.0f} ms)')
        self.view.slm_loaded(load.event, load.k, True, ms, late)
        self._send_pending()

    def _load_failed(self, why: str):
        p = self.protocol
        load, p.in_flight = p.in_flight, None
        self._failed(load.event, load.k, why)

    def _failed(self, event: int, k: int, why: str):
        p = self.protocol
        p.failed += 1
        self.log(f'[SLM] Trigger {event}: {self._mask_name(k)} NOT loaded ({why}): the SLM still shows the '
                 f'previous mask', 'error')
        self.view.slm_loaded(event, k, False, None, False)
        self._send_pending()

    def _send_pending(self):
        p = self.protocol
        if p is not None and p.in_flight is None and p.pending is not None:
            event, p.pending = p.pending, None
            self._send_load(event)

    def _mask_name(self, k: int) -> str:
        png = self.protocol.masks[k]
        return png.name if png is not None else f'mask {k + 1}'

    # ── scripts and answers ──

    def _send(self, js: str) -> tuple:
        """Send a script over TCP: (its id, None), or (None, why it could not be). Its answer is read by poll()."""
        link = self.wf.link
        made = link.connections
        try:
            sid, error = link.send(js), None
        except LinkError as e:
            sid, error = None, str(e)
        if link.connections != made:
            self.log(f"[SLM] Connected to {self.wf.NAME}'s TCP server (port {link.port})")
        reachable = sid is not None
        port = link.port if reachable else self.port
        if (reachable, port) != (self.reachable, self.port):
            self.reachable, self.port = reachable, port
            self.view.wavefront_changed()
        return sid, error

    def _answering(self, yes: bool):
        """Wavefront answered a script (it runs them), or did not in time."""
        if yes != self.runs_scripts:
            self.runs_scripts = yes
            self.view.wavefront_changed()

    def _on_answer(self, kind: str, sid: int, error: str):
        """An answer from Wavefront: to the ping, tick or preparation waiting, or to the mask in flight. Any other is
        late (a load given up after its timeout, a protocol stopped): nothing to do."""
        w = self.waiting
        if w is not None and w.sid == sid:
            self.waiting = None
            self._answering(True)
            if w.kind == 'prepare':
                self._prepared(kind, error)
            elif w.kind == 'tick':
                self.log(f"[SLM] {self.wf.SERVER} ticked by Plerion: {self.wf.NAME} runs Plerion's scripts "
                         f"(port {self.port})")
            elif w.say:
                self.log(f"[SLM] {self.wf.NAME} runs Plerion's scripts (port {self.port})")
            self.view.wavefront_changed()
            return
        p = self.protocol
        if p is not None and p.in_flight is not None and p.in_flight.sid == sid:
            self._answering(True)
            if kind == 'ERROR':
                self._load_failed(f"Wavefront's script failed: {error}")
            else:
                self._loaded()

    def _prepared(self, kind: str, error: str):
        p = self.protocol
        if p is None:                               # given up meanwhile (STOP)
            return
        if kind == 'ERROR':
            self.protocol = None
            self.view.slm_armed(False, f"Wavefront's preparation script failed: {error}")
            return
        p.armed = True
        self.view.slm_armed(True, '')

    def _on_foreign(self, texts: list):
        """Another program's scripts answered (Wavefront answers every client): it is running scripts in Wavefront, so
        Plerion sends nothing on its own for OTHER_CLIENT_S (busy); during a protocol, said once."""
        self.other_at = time.time()
        p = self.protocol
        if p is not None and not p.other_said:
            p.other_said = True
            self.log(f'[SLM] Another program ran a script in Wavefront during the protocol ("{texts[-1][:60]}"): '
                     f'Oriole TCP? Two scripts running at once can crash Wavefront', 'warn')

    def _waiting_too_long(self):
        """The ping, tick or preparation waiting got no answer in time."""
        w, wf = self.waiting, self.wf
        limit = {'ping': PING_WAIT_S, 'tick': TICK_WAIT_S, 'prepare': PREPARE_WAIT_S}[w.kind]
        if time.time() - w.sent < limit:
            return
        taken = w.kind != 'tick' or not wf.tick_waiting(w.folder)
        self._drop_waiting()
        self._answering(False)
        if w.kind == 'prepare':
            if self.protocol is not None:           # not given up meanwhile (STOP)
                self.protocol = None
                self.view.slm_armed(False, f'{wf.NAME} did not answer within {PREPARE_WAIT_S:.0f} s '
                                           f'({wf.SCRIPTS_HINT}, then press Check)')
        elif w.kind == 'tick':
            why = (f'it did not take the {wf.TICK_VIA} ({wf.TICK_NOT_TAKEN})' if not taken
                   else f'it took the {wf.TICK_VIA}, but did not answer')
            self.log(f"[SLM] Plerion could not tick {wf.NAME}'s {wf.SERVER}: {why}. {wf.SCRIPTS_HINT}, then press "
                     f"Check", 'error')
        elif not self.tick_tried and wf.CAN_TICK and wf.supported:
            self._tick()
        elif w.say:
            self.log(f"[SLM] {wf.NAME} does not run Plerion's scripts: {wf.SCRIPTS_HINT}, then press Check", 'error')
        self.view.wavefront_changed()

    def _tick(self):
        """Have Wavefront switch its server on (wf.tick); its answer comes over TCP like any other."""
        wf = self.wf
        self.tick_tried = True
        folder = self.folder or wf.root
        try:
            sid = wf.tick(folder)
        except OSError as e:
            self.log(f"[SLM] {wf.NAME} does not run Plerion's scripts, and Plerion cannot tick its {wf.SERVER} ({e}): "
                     f"{wf.SCRIPTS_HINT}, then press Check", 'error')
            return
        self.log(f"[SLM] {wf.NAME} does not run Plerion's scripts yet: Plerion ticks its {wf.SERVER} "
                 f"(a {wf.TICK_VIA})")
        self.waiting = Waiting('tick', sid, time.time(), folder=folder)

    def _drop_waiting(self):
        """Forget the script waiting for its answer; a tick not taken undone."""
        w, self.waiting = self.waiting, None
        if w is not None and w.kind == 'tick':
            try:
                self.wf.take_back_tick(w.folder)
            except OSError:
                pass
