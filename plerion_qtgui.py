"""
plerion_qtgui.py — PySide6 GUI for Plerion.

Replaces the Tkinter GUI with Qt Widgets for reliable 100Hz trigger tracking.
Backend modules (dmd.py, sync.py) are unchanged.

Tabs:
  Visual — DMD-only stimulation
  DH     — digital holography simplified mode
  VDH    — full experiment mode (DMD + NI-DAQ + SLM)
"""

import atexit
import os
import signal
import sys
import json
import time
import threading

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget,
    QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout,
    QLabel, QLineEdit, QComboBox, QSpinBox, QPushButton,
    QRadioButton, QButtonGroup, QProgressBar, QGroupBox,
    QPlainTextEdit, QListWidget, QListWidgetItem, QFileDialog,
    QMessageBox, QSplitter, QScrollBar, QSizePolicy,
)
from PySide6.QtCore import (
    Qt, QObject, QThread, Signal, Slot, QTimer, QSize,
)
from PySide6.QtGui import (
    QColor, QPalette, QFont, QTextCharFormat, QPainter, QPen, QBrush,
)

from jsonc_parser.parser import JsoncParser

sys.path.insert(0, os.path.dirname(__file__))
from modules import dmd, sync, slm

# ── constants ────────────────────────────────────────────────────────────────

COLOR_BG     = '#121212'
COLOR_CARD   = '#1E1E1E'
COLOR_TEXT   = '#E0E0E0'
COLOR_DIM    = '#555555'
COLOR_BTN    = '#2A2A2A'
COLOR_ACCENT = '#2D6A9F'

FO_BG  = '#060A06'
FO_OFF = '#0D2A0D'
FO_DIM = '#1A5A1A'
FO_MID = '#3A8A3A'
FO_ON  = '#4AFC4A'

PARAMS_FILE = os.path.join(os.path.dirname(__file__), 'plerion_params.jsonc')
CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'plerion_config.jsonc')

# ── helpers ──────────────────────────────────────────────────────────────────

def load_json(path: str, default: dict) -> dict:
    try:
        return JsoncParser.parse_file(path)
    except Exception:
        return default


def save_json(path: str, data: dict) -> None:
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


def _fmt_remaining(secs: float) -> str:
    s = int(secs)
    if s >= 3600:
        h = s // 3600
        m = (s % 3600) // 60
        return f'{h}h {m:02d}m'
    m = s // 60
    s = s % 60
    return f'{m}m {s:02d}s'


def _fmt_countdown(secs: float) -> str:
    s = int(secs)
    h = s // 3600
    m = (s % 3600) // 60
    ss = s % 60
    if h:
        return f'{h}:{m:02d}:{ss:02d}'
    return f'{m:02d}:{ss:02d}'


def scan_binvec_folder(folder: str, params: dict = None):
    p = params or {}
    def list_dir(sub: str):
        path = os.path.normpath(os.path.join(folder, sub))
        if os.path.isdir(path):
            return sorted(f for f in os.listdir(path) if not f.startswith('.'))
        return []
    bin_files = list_dir(p.get('bin_subfolder',        'BIN'))
    vec_files = list_dir(p.get('vec_subfolder',        'VEC'))
    pm_files  = list_dir(p.get('phasemasks_subfolder', 'Phasemasks'))
    return bin_files, vec_files, pm_files


def open_folder(folder: str) -> None:
    if folder and os.path.isdir(folder):
        os.startfile(folder)


# ── dark theme ───────────────────────────────────────────────────────────────

def apply_dark_theme(app: QApplication):
    palette = QPalette()
    palette.setColor(QPalette.Window,          QColor(COLOR_BG))
    palette.setColor(QPalette.WindowText,      QColor(COLOR_TEXT))
    palette.setColor(QPalette.Base,            QColor(COLOR_CARD))
    palette.setColor(QPalette.AlternateBase,   QColor(COLOR_BG))
    palette.setColor(QPalette.ToolTipBase,     QColor(COLOR_CARD))
    palette.setColor(QPalette.ToolTipText,     QColor(COLOR_TEXT))
    palette.setColor(QPalette.Text,            QColor(COLOR_TEXT))
    palette.setColor(QPalette.Button,          QColor(COLOR_BTN))
    palette.setColor(QPalette.ButtonText,      QColor(COLOR_TEXT))
    palette.setColor(QPalette.BrightText,      QColor('#FF4444'))
    palette.setColor(QPalette.Link,            QColor(COLOR_ACCENT))
    palette.setColor(QPalette.Highlight,       QColor(COLOR_ACCENT))
    palette.setColor(QPalette.HighlightedText, QColor('#FFFFFF'))
    palette.setColor(QPalette.Disabled, QPalette.Text,       QColor(COLOR_DIM))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(COLOR_DIM))
    app.setPalette(palette)

    app.setStyleSheet("""
        QGroupBox {
            border: 1px solid #333; border-radius: 4px;
            margin-top: 10px; padding: 12px 6px 6px 6px;
            font: bold 9pt 'Segoe UI';
        }
        QGroupBox::title {
            subcontrol-origin: margin; left: 10px; padding: 0 4px;
            color: #E0E0E0;
        }
        QPushButton {
            border: none; border-radius: 3px; padding: 6px 14px;
            background: #2A2A2A; color: #E0E0E0;
        }
        QPushButton:hover { background: #3A3A3A; }
        QPushButton:pressed { background: #2D6A9F; }
        QPushButton:disabled { color: #555555; }
        QProgressBar {
            border: none; background: #1E1E1E; border-radius: 2px;
            text-align: center; color: transparent;
        }
        QProgressBar::chunk { background: #2D6A9F; border-radius: 2px; }
        QComboBox {
            border: 1px solid #333; border-radius: 3px; padding: 4px 8px;
            background: #1E1E1E; color: #E0E0E0;
        }
        QComboBox QAbstractItemView {
            background: #D6E4F0; color: #000000;
            selection-background-color: #2D6A9F; selection-color: #FFFFFF;
        }
        QComboBox::drop-down { border: none; }
        QComboBox::down-arrow { image: none; border: none; width: 12px; }
        QSpinBox {
            border: 1px solid #333; border-radius: 3px; padding: 4px;
            background: #1E1E1E; color: #E0E0E0;
        }
        QLineEdit {
            border: 1px solid #333; border-radius: 3px; padding: 4px;
            background: #1E1E1E; color: #E0E0E0;
        }
        QListWidget {
            border: none; background: #1E1E1E; color: #555555;
            font: 8pt 'Consolas';
        }
        QTabWidget::pane { border: 1px solid #333; }
        QTabBar::tab {
            background: #1E1E1E; color: #E0E0E0;
            padding: 6px 16px; margin-right: 2px;
        }
        QTabBar::tab:selected { background: #2D6A9F; color: #FFFFFF; }
        QTabBar::tab:hover { background: #3A3A3A; }
        QScrollBar:vertical {
            background: #121212; width: 10px; margin: 0;
        }
        QScrollBar::handle:vertical {
            background: #333; border-radius: 4px; min-height: 20px;
        }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
    """)


# ── TriggerWorker ────────────────────────────────────────────────────────────

class TriggerWorker(QObject):
    """Polls NI-DAQ TriggerCounter at 100Hz in a QThread, emits signals."""

    trigger_update = Signal(int)    # current cumulative count
    stim_started   = Signal()
    stim_complete  = Signal()
    stim_timeout   = Signal()
    finished       = Signal()

    def __init__(self, counter, total_triggers: int, timeout_s: float):
        super().__init__()
        self._counter        = counter
        self._total          = total_triggers
        self._timeout        = timeout_s
        self._active         = True
        self._started        = False
        self._last_count     = 0
        self._last_time      = 0.0

    @Slot()
    def run(self):
        while self._active:
            count = 0
            if self._counter:
                try:
                    count = self._counter.read()
                except Exception:
                    pass

            if count > 0 and not self._started:
                self._started   = True
                self._last_time = time.time()
                self.stim_started.emit()

            if count != self._last_count:
                self._last_count = count
                self._last_time  = time.time()
                self.trigger_update.emit(count)

            if self._started:
                if self._total > 0 and count >= self._total:
                    self.stim_complete.emit()
                    break
                if (time.time() - self._last_time) > self._timeout:
                    self.stim_timeout.emit()
                    break

            QThread.msleep(10)

        self.finished.emit()

    def stop(self):
        self._active = False


# ── ConsoleLog ───────────────────────────────────────────────────────────────

class ConsoleLog(QPlainTextEdit):
    """Read-only console with coloured log levels."""

    _LOG_COLORS = {
        'info':  QColor('#00FF00'),
        'warn':  QColor('#FFD700'),
        'error': QColor('#FF4444'),
        'freq':  QColor('#00CCFF'),
    }

    # Thread-safe: emit signal from any thread, slot appends in main thread
    _append_signal = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(QFont('Consolas', 9))
        self.setStyleSheet(
            'background: #0A0A0A; color: #00FF00; border: none;')
        self.setMaximumBlockCount(2000)
        self._append_signal.connect(self._do_append)

    def log(self, message: str, level: str = 'info') -> None:
        self._append_signal.emit(message, level)

    @Slot(str, str)
    def _do_append(self, message: str, level: str):
        fmt = QTextCharFormat()
        fmt.setForeground(self._LOG_COLORS.get(level, QColor('#00FF00')))
        cursor = self.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(message + '\n', fmt)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def clear_log(self) -> None:
        self.clear()


# ── SciTimerPanel ────────────────────────────────────────────────────────────

class SciTimerPanel(QWidget):
    """Fallout phosphor timer display — pure view, no logic."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f'background: {FO_BG};')
        self._cur_color = FO_OFF

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)

        self._lbl_status = QLabel('[ IDLE ]')
        self._lbl_status.setFont(QFont('Consolas', 8, QFont.Bold))
        self._lbl_status.setStyleSheet(f'color: {FO_OFF}; background: transparent;')
        layout.addWidget(self._lbl_status)

        self._lbl_countdown = QLabel('--:--')
        self._lbl_countdown.setFont(QFont('Consolas', 28, QFont.Bold))
        self._lbl_countdown.setAlignment(Qt.AlignCenter)
        self._lbl_countdown.setStyleSheet(f'color: {FO_OFF}; background: transparent;')
        layout.addWidget(self._lbl_countdown)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(8)
        self._progress.setStyleSheet(f"""
            QProgressBar {{ background: {FO_OFF}; border: none; border-radius: 3px; }}
            QProgressBar::chunk {{ background: {FO_ON}; border-radius: 3px; }}
        """)
        layout.addWidget(self._progress)

        self._lbl_triggers = QLabel('')
        self._lbl_triggers.setFont(QFont('Consolas', 8))
        self._lbl_triggers.setStyleSheet(f'color: {FO_OFF}; background: transparent;')
        layout.addWidget(self._lbl_triggers)

    def set_idle(self):
        self._set(FO_OFF, '[ IDLE ]', '--:--', '', 0)

    def set_ready(self, total: int, freq: float):
        secs = total / freq if freq > 0 else 0
        self._set(FO_DIM, '[ READY ]',
                  _fmt_countdown(secs),
                  f'{total} triggers  ·  {_fmt_remaining(secs)}', 0)

    def set_armed(self, total: int, freq: float):
        secs = total / freq if freq > 0 else 0
        self._set(FO_MID, '[ ARMED ]',
                  _fmt_countdown(secs),
                  f'waiting  ·  {total} triggers', 0)

    def update_progress(self, count: int, total: int, freq: float):
        remaining = max(0, total - count)
        secs_left = remaining / freq if freq > 0 else 0
        pct = min(100, int(count / total * 100)) if total > 0 else 0
        self._set(FO_ON, '[ ACTIVE ]',
                  _fmt_countdown(secs_left),
                  f'{count:>6} / {total}', pct)

    def set_complete(self):
        self._set(FO_ON, '[ COMPLETE ]', '00:00', '', 100)

    def _set(self, color: str, status: str, countdown: str,
             triggers: str, pct: int):
        # Only update stylesheets when the color actually changes
        if color != self._cur_color:
            self._cur_color = color
            ss = f'color: {color}; background: transparent;'
            self._lbl_status.setStyleSheet(ss)
            self._lbl_countdown.setStyleSheet(ss)
            self._lbl_triggers.setStyleSheet(ss)
        self._lbl_status.setText(status)
        self._lbl_countdown.setText(countdown)
        self._lbl_triggers.setText(triggers)
        self._progress.setValue(pct)


# ── IndicatorDot ─────────────────────────────────────────────────────────────

class IndicatorDot(QWidget):
    """Custom-painted circular indicator (phasemask or shutter)."""

    def __init__(self, mode: str = 'phasemask', parent=None):
        super().__init__(parent)
        self._mode   = mode
        self._active = False
        self.setFixedSize(40, 40)
        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self._dim)

    def flash(self, duration_ms: int = 200):
        self._active = True
        self.update()
        self._flash_timer.start(duration_ms)

    def set_active(self, active: bool):
        self._active = active
        self.update()

    def _dim(self):
        self._active = False
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self._mode == 'phasemask':
            self._draw_phasemask(p)
        else:
            self._draw_shutter(p)
        p.end()

    def _draw_phasemask(self, p: QPainter):
        color = QColor(FO_ON) if self._active else QColor(FO_OFF)
        # outer ring
        p.setPen(QPen(color, 2))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(4, 4, 32, 32)
        # inner dot
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(color))
        p.drawEllipse(14, 14, 12, 12)

    def _draw_shutter(self, p: QPainter):
        color = QColor('#FF4400') if self._active else QColor('#1A0000')
        # center dot
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(color))
        p.drawEllipse(15, 15, 10, 10)
        # rays
        pen = QPen(color, 2)
        p.setPen(pen)
        rays = [(20,3,20,12),(20,28,20,37),(3,20,12,20),(28,20,37,20),
                (7,7,13,13),(27,7,33,13),(7,33,13,27),(27,33,33,27)]
        for x1, y1, x2, y2 in rays:
            p.drawLine(x1, y1, x2, y2)


# ── status dot helper ────────────────────────────────────────────────────────

class StatusDot(QWidget):
    """Small coloured circle for hardware connection status."""

    def __init__(self, color: str = COLOR_DIM, parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self.setFixedSize(14, 14)

    def set_color(self, color: str):
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(self._color))
        p.drawEllipse(2, 2, 10, 10)
        p.end()


class ElidedLabel(QLabel):
    """Single-line label that elides long text on the left (…/folder/file.txt).

    Use this for file/folder path display so the filename end stays visible.
    Call setText() normally; elision is applied automatically on resize.
    """

    def __init__(self, text: str = '—', parent=None):
        super().__init__(parent)
        self._full_text = text
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumWidth(10)
        super().setText(self._elided())

    def setText(self, text: str):
        self._full_text = text
        super().setText(self._elided())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        super().setText(self._elided())

    def _elided(self) -> str:
        fm = self.fontMetrics()
        return fm.elidedText(self._full_text, Qt.ElideLeft, max(self.width(), 10))


# ── shared run/stop button factory ───────────────────────────────────────────

def _make_run_btn(parent) -> QPushButton:
    btn = QPushButton('RUN PROTOCOL', parent)
    btn.setFont(QFont('Consolas', 12, QFont.Bold))
    btn.setMinimumHeight(40)
    btn.setStyleSheet("""
        QPushButton { background: #1A4A1A; color: #00FF00; border: none; border-radius: 4px; }
        QPushButton:hover { background: #2A6A2A; }
        QPushButton:disabled { background: #3A3A3A; color: #666666; }
    """)
    return btn


def _make_stop_btn(parent) -> QPushButton:
    btn = QPushButton('STOP', parent)
    btn.setFont(QFont('Consolas', 12, QFont.Bold))
    btn.setMinimumHeight(40)
    btn.setEnabled(False)
    btn.setStyleSheet("""
        QPushButton { background: #2A2A2A; color: #666666; border: none; border-radius: 4px; }
        QPushButton:hover { background: #6A2A2A; color: #FF4444; }
        QPushButton:enabled { background: #4A1A1A; color: #FF4444; }
        QPushButton:disabled { background: #2A2A2A; color: #666666; }
    """)
    return btn


# ── folder picker row helper ─────────────────────────────────────────────────

def _make_folder_row(parent, label_text: str, initial: str,
                     on_select=None, initialdir: str = '') -> tuple:
    """Returns (row_widget, line_edit)."""
    row = QWidget(parent)
    h = QHBoxLayout(row)
    h.setContentsMargins(0, 0, 0, 0)
    lbl = QLabel(label_text)
    lbl.setFixedWidth(120)
    h.addWidget(lbl)
    le = QLineEdit(initial)
    le.setReadOnly(True)
    h.addWidget(le, 1)
    btn = QPushButton('…')
    btn.setFixedWidth(30)
    h.addWidget(btn)

    def browse():
        path = QFileDialog.getExistingDirectory(parent, label_text,
                                                initialdir or initial)
        if path:
            le.setText(path)
            if on_select:
                on_select(path)

    btn.clicked.connect(browse)
    return row, le



# ═════════════════════════════════════════════════════════════════════════════
# ── Visual tab ───────────────────────────────────────────────────────────────
# ═════════════════════════════════════════════════════════════════════════════

class VisualTab(QWidget):

    _tab_prefix = '[Visual]'
    _request_cleanup = Signal()

    def __init__(self, console: ConsoleLog, params: dict, config: dict,
                 save_config, acquire_run, release_run):
        super().__init__()
        self.console      = console
        self.params       = params
        self.config       = config
        self._save_config = save_config
        self._acquire_run = acquire_run
        self._release_run = release_run
        self._proc        = None
        self._worker      = None
        self._thread      = None
        self._total_triggers = 0
        self._freq_hz        = 0.0
        self._counter        = None
        self._request_cleanup.connect(self._do_cleanup)
        self._build()

    def _build(self):
        cfg = self.config
        main = QHBoxLayout(self)
        main.setContentsMargins(8, 8, 8, 8)
        main.setSpacing(12)

        # ── left column ──
        left = QWidget()
        left.setMinimumWidth(360)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)

        files_grp = QGroupBox('DMD')
        fl = QVBoxLayout(files_grp)

        self._folder_row, self._le_folder = _make_folder_row(
            files_grp, 'Binvec folder',
            cfg.get('vis_binvec_folder', ''),
            on_select=self._on_folder_selected,
            initialdir=self.params.get('binvecs_root', ''))
        fl.addWidget(self._folder_row)

        bin_row = QWidget()
        bh = QHBoxLayout(bin_row)
        bh.setContentsMargins(0, 0, 0, 0)
        bh.addWidget(QLabel('.bin file'))
        self._combo_bin = QComboBox()
        bh.addWidget(self._combo_bin, 1)
        fl.addWidget(bin_row)

        vec_row = QWidget()
        vh = QHBoxLayout(vec_row)
        vh.setContentsMargins(0, 0, 0, 0)
        vh.addWidget(QLabel('.vec file'))
        self._combo_vec = QComboBox()
        vh.addWidget(self._combo_vec, 1)
        fl.addWidget(vec_row)

        freq_row = QWidget()
        fh = QHBoxLayout(freq_row)
        fh.setContentsMargins(0, 0, 0, 0)
        fh.addWidget(QLabel('Rate (Hz):'))
        self._le_freq = QLineEdit(str(cfg.get('vis_freq', 20.0)))
        self._le_freq.setFixedWidth(80)
        fh.addWidget(self._le_freq)
        fh.addStretch()
        fl.addWidget(freq_row)

        lv.addWidget(files_grp)
        lv.addStretch()

        # ── right column ──
        right = QWidget()
        right.setMinimumWidth(300)
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)

        self._timer_panel = SciTimerPanel()
        rv.addWidget(self._timer_panel)

        btn_row = QWidget()
        br = QHBoxLayout(btn_row)
        br.setContentsMargins(0, 0, 0, 0)
        self._btn_run = _make_run_btn(self)
        self._btn_stop = _make_stop_btn(self)
        br.addWidget(self._btn_run, 3)
        br.addWidget(self._btn_stop, 1)
        rv.addWidget(btn_row)
        rv.addStretch()

        main.addWidget(left, 1)
        main.addWidget(right, 1)

        # signals
        self._btn_run.clicked.connect(self._on_run)
        self._btn_stop.clicked.connect(self._on_stop)
        self._le_freq.textChanged.connect(self._update_preview)
        self._combo_vec.currentTextChanged.connect(self._update_preview)

        # populate from config
        if cfg.get('vis_binvec_folder'):
            self._on_folder_selected(cfg['vis_binvec_folder'])
        if cfg.get('vis_bin_name'):
            self._combo_bin.setCurrentText(cfg['vis_bin_name'])
        if cfg.get('vis_vec_name'):
            self._combo_vec.setCurrentText(cfg['vis_vec_name'])
        self._update_preview()

    def _vec_path(self) -> str:
        folder   = self._le_folder.text()
        vec_name = self._combo_vec.currentText()
        if not folder or not vec_name:
            return ''
        sub = self.params.get('vec_subfolder', 'VEC')
        p = os.path.normpath(os.path.join(folder, sub, vec_name))
        return p if os.path.isfile(p) else ''

    def _update_preview(self):
        if self._worker:
            return
        try:
            freq = float(self._le_freq.text())
            if freq <= 0:
                raise ValueError
        except ValueError:
            self._timer_panel.set_idle()
            return
        vec_p = self._vec_path()
        if not vec_p:
            self._timer_panel.set_idle()
            return
        try:
            total = sync.count_vec_triggers(vec_p)
        except Exception:
            self._timer_panel.set_idle()
            return
        self._timer_panel.set_ready(total, freq)

    def _on_folder_selected(self, folder: str):
        self._le_folder.setText(folder)
        bin_files, vec_files, _ = scan_binvec_folder(folder, self.params)
        self._combo_bin.clear()
        self._combo_bin.addItems(bin_files)
        self._combo_vec.clear()
        self._combo_vec.addItems(vec_files)

    def _on_run(self):
        folder   = self._le_folder.text()
        bin_name = self._combo_bin.currentText()
        vec_name = self._combo_vec.currentText()
        try:
            freq_hz = float(self._le_freq.text())
        except ValueError:
            QMessageBox.critical(self, 'Error', 'Invalid frequency.')
            return
        if not folder or not bin_name or not vec_name:
            QMessageBox.critical(self, 'Error', 'Select a folder, BIN and VEC.')
            return
        if not self._acquire_run():
            self.console.log('[Visual] Film.exe already running.', 'warn')
            return

        self._save_config()
        self._freq_hz = freq_hz
        self._btn_run.setEnabled(False)
        self._btn_run.setText('RUNNING…')
        self._btn_stop.setEnabled(True)

        # arm counter + worker
        self._arm_worker(freq_hz)

        def _run():
            try:
                self._proc = dmd.run_vdh(
                    folder, bin_name, vec_name, freq_hz,
                    self.params, self.console.log)
                _active_procs.append(self._proc)
                self._proc.wait()
                if self._proc.returncode not in (0, -1, 1):
                    self.console.log(
                        f'[DMD] film.exe unexpectedly closed (code {self._proc.returncode})', 'warn')
            except Exception as e:
                self.console.log(f'[Visual] ERROR: {e}', 'error')
            finally:
                if self._proc in _active_procs:
                    _active_procs.remove(self._proc)
                self._request_cleanup.emit()

        threading.Thread(target=_run, daemon=True).start()

    def _on_stop(self):
        dmd.stop(self._proc, self.params.get('film_exe', ''))
        self.console.log('[Visual] Protocol interrupted.', 'warn')

    def _arm_worker(self, freq_hz: float):
        total = 0
        vec_p = self._vec_path()
        if vec_p:
            try:
                total = sync.count_vec_triggers(vec_p)
            except Exception as e:
                self.console.log(f'[Visual] Cannot read vec: {e}', 'warn')

        self._total_triggers = total
        nidaq   = self.params.get('nidaq', {})
        device  = nidaq.get('device', 'Dev1')
        pfi_idx = nidaq.get('pfi_clock', 0)
        try:
            self._counter = sync.TriggerCounter(device, pfi_idx)
            self.console.log(f'[Visual] NI-DAQ counter armed ({device}/PFI{pfi_idx})')
        except Exception as e:
            self._counter = None
            self.console.log(f'[Visual] NI-DAQ counter unavailable: {e}', 'warn')

        timeout = self.params.get('trigger_timeout_s', 10)
        self._timer_panel.set_armed(total, freq_hz)

        self._worker = TriggerWorker(self._counter, total, timeout)
        self._thread = QThread()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.trigger_update.connect(self._on_trigger_update)
        self._worker.stim_started.connect(self._on_stim_started)
        self._worker.stim_complete.connect(self._on_complete)
        self._worker.stim_timeout.connect(self._on_timeout)
        self._worker.finished.connect(self._thread.quit)
        self._thread.start()

    @Slot(int)
    def _on_trigger_update(self, count: int):
        self._timer_panel.update_progress(count, self._total_triggers, self._freq_hz)

    @Slot()
    def _on_stim_started(self):
        self.console.log('[Visual] >> STIM STARTED')

    @Slot()
    def _on_complete(self):
        self._timer_panel.set_complete()
        self.console.log('[Visual] ■ STIM COMPLETE')
        dmd.stop(self._proc, self.params.get('film_exe', ''))

    @Slot()
    def _on_timeout(self):
        timeout = self.params.get('trigger_timeout_s', 10)
        self.console.log(f'[Visual] ■ No trigger for {timeout}s — stopping', 'warn')
        dmd.stop(self._proc, self.params.get('film_exe', ''))

    @Slot()
    def _do_cleanup(self):
        """Runs in main thread via signal — safe to touch Qt widgets."""
        if self._worker:
            self._worker.stop()
            self._worker = None
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(2000)
            self._thread = None
        if self._counter:
            self._counter.close()
            self._counter = None
        self._release_run()

    def reset_ui(self):
        self._btn_run.setEnabled(True)
        self._btn_run.setText('RUN PROTOCOL')
        self._btn_stop.setEnabled(False)
        self._update_preview()


# ═════════════════════════════════════════════════════════════════════════════
# ── DH tab ───────────────────────────────────────────────────────────────────
# ═════════════════════════════════════════════════════════════════════════════

class DhTab(QWidget):

    _tab_prefix = '[DH]'
    _request_cleanup = Signal()

    def __init__(self, console: ConsoleLog, params: dict, config: dict,
                 save_config, acquire_run, release_run):
        super().__init__()
        self.console      = console
        self.params       = params
        self.config       = config
        self._save_config = save_config
        self._acquire_run = acquire_run
        self._release_run = release_run
        self._proc        = None
        self._worker      = None
        self._thread      = None
        self._counter     = None
        self._waveform    = None
        self._total_triggers  = 0
        self._freq_hz         = 0.0
        self._last_processed  = 0
        # DH tracking state
        self._vec_col_slm     = []
        self._vec_col_shutter = []
        self._pm_lines        = []
        self._pm_index        = 0
        self._shutter_open    = False
        tcp = params.get('tcp_slm', {})
        self._slm = slm.SLMClient(tcp.get('host', ''), tcp.get('port', 55160))
        self._request_cleanup.connect(self._do_cleanup)
        self._build()

    def _build(self):
        cfg = self.config
        main = QHBoxLayout(self)
        main.setContentsMargins(8, 8, 8, 8)
        main.setSpacing(12)

        # ── left column ──
        left = QWidget()
        left.setMinimumWidth(360)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)

        # DMD group: n_spots, VEC, phasemask order file, BIN mode, Rate
        bin_grp = QGroupBox('DMD')
        bgl_outer = QVBoxLayout(bin_grp)

        spots_row = QWidget()
        sr = QHBoxLayout(spots_row)
        sr.setContentsMargins(0, 0, 0, 0)
        sr.addWidget(QLabel('Number of spots:'))
        self._spin_spots = QSpinBox()
        self._spin_spots.setRange(1, 500)
        self._spin_spots.setValue(cfg.get('dh_n_spots', 1))
        self._spin_spots.setFixedWidth(70)
        self._spin_spots.valueChanged.connect(self._on_spots_changed)
        sr.addWidget(self._spin_spots)
        sr.addStretch()
        bgl_outer.addWidget(spots_row)

        vec_row = QWidget()
        vr = QHBoxLayout(vec_row)
        vr.setContentsMargins(0, 0, 0, 0)
        vr.addWidget(QLabel('VEC file:'))
        self._lbl_vec = ElidedLabel('—')
        self._lbl_vec.setStyleSheet(f'color: {COLOR_DIM};')
        vr.addWidget(self._lbl_vec, 1)
        bgl_outer.addWidget(vec_row)

        bin_mode_row = QWidget()
        bgl = QHBoxLayout(bin_mode_row)
        bgl.setContentsMargins(0, 0, 0, 0)
        self._rb_bright = QRadioButton('Bright')
        self._rb_dark   = QRadioButton('Dark')
        self._bin_group = QButtonGroup(self)
        self._bin_group.addButton(self._rb_bright)
        self._bin_group.addButton(self._rb_dark)
        if cfg.get('dh_bin_mode', 'dark') == 'bright':
            self._rb_bright.setChecked(True)
        else:
            self._rb_dark.setChecked(True)
        bgl.addWidget(self._rb_bright)
        bgl.addWidget(self._rb_dark)
        self._lbl_bin = ElidedLabel('—')
        self._lbl_bin.setStyleSheet(f'color: {COLOR_DIM};')
        bgl.addWidget(self._lbl_bin, 1)
        self._rb_bright.toggled.connect(self._on_bin_mode_changed)
        bgl_outer.addWidget(bin_mode_row)

        freq_row = QWidget()
        fh = QHBoxLayout(freq_row)
        fh.setContentsMargins(0, 0, 0, 0)
        fh.addWidget(QLabel('Rate (Hz):'))
        self._le_freq = QLineEdit(str(cfg.get('dh_freq', 20.0)))
        self._le_freq.setFixedWidth(80)
        fh.addWidget(self._le_freq)
        fh.addStretch()
        bgl_outer.addWidget(freq_row)

        lv.addWidget(bin_grp)

        # Holography group: phasemask file path, folder, detected count, order list
        holo_grp = QGroupBox('Holography')
        pml = QVBoxLayout(holo_grp)

        # TCP WaveFront IV status row
        tcp_row = QWidget()
        tr_ = QHBoxLayout(tcp_row)
        tr_.setContentsMargins(0, 0, 0, 0)
        tr_.setSpacing(6)
        self._dot_tcp = StatusDot(COLOR_DIM)
        tr_.addWidget(self._dot_tcp)
        tr_.addWidget(QLabel('TCP WaveFront IV'))
        tr_.addStretch()
        self._btn_reconnect = QPushButton('Reconnect')
        self._btn_reconnect.setFixedWidth(90)
        self._btn_reconnect.clicked.connect(self._reconnect_slm)
        tr_.addWidget(self._btn_reconnect)
        pml.addWidget(tcp_row)

        pm_folder_row = QWidget()
        pfh = QHBoxLayout(pm_folder_row)
        pfh.setContentsMargins(0, 0, 0, 0)
        self._lbl_pm_folder = ElidedLabel(self.params.get('wavefront_folder', '—'))
        self._lbl_pm_folder.setStyleSheet(f'color: {COLOR_DIM};')
        pfh.addWidget(self._lbl_pm_folder, 1)
        btn_open_pm = QPushButton('Open')
        btn_open_pm.setMinimumWidth(60)
        btn_open_pm.setContentsMargins(6, 0, 6, 0)
        btn_open_pm.clicked.connect(
            lambda: open_folder(self.params.get('wavefront_folder', '')))
        pfh.addWidget(btn_open_pm)
        pml.addWidget(pm_folder_row)

        det_row = QWidget()
        dh = QHBoxLayout(det_row)
        dh.setContentsMargins(0, 0, 0, 0)
        self._lbl_pm_detected = QLabel('—')
        self._lbl_pm_detected.setStyleSheet(f'color: {COLOR_DIM};')
        dh.addWidget(self._lbl_pm_detected, 1)
        btn_scan = QPushButton('Scan')
        btn_scan.setMinimumWidth(60)
        btn_scan.setContentsMargins(6, 0, 6, 0)
        btn_scan.clicked.connect(self._scan_pm_folder)
        dh.addWidget(btn_scan)
        pml.addWidget(det_row)

        pm_file_row = QWidget()
        pfr = QHBoxLayout(pm_file_row)
        pfr.setContentsMargins(0, 0, 0, 0)
        pfr.addWidget(QLabel('PM order file:'))
        self._lbl_pm = ElidedLabel('—')
        self._lbl_pm.setStyleSheet(f'color: {COLOR_DIM};')
        pfr.addWidget(self._lbl_pm, 1)
        pml.addWidget(pm_file_row)

        self._pm_listbox = QListWidget()
        self._pm_listbox.setFont(QFont('Consolas', 7))
        self._pm_listbox.setSelectionMode(QListWidget.NoSelection)
        self._pm_listbox.setFocusPolicy(Qt.NoFocus)
        self._pm_listbox.setMinimumHeight(8 * 20)  # at least 5 rows visible
        pml.addWidget(self._pm_listbox, 1)

        lv.addWidget(holo_grp, 1)

        # ── right column ──
        right = QWidget()
        right.setMinimumWidth(300)
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)

        # Timer
        self._timer_panel = SciTimerPanel()
        rv.addWidget(self._timer_panel)

        # Signal indicators
        ind_frame = QWidget()
        ind_frame.setStyleSheet(f'background: {FO_BG};')
        ih = QHBoxLayout(ind_frame)
        ih.setContentsMargins(10, 6, 10, 6)

        pm_ind = QWidget()
        piv = QVBoxLayout(pm_ind)
        piv.setAlignment(Qt.AlignCenter)
        piv.setContentsMargins(0, 0, 0, 0)
        self._ind_pm = IndicatorDot('phasemask')
        piv.addWidget(self._ind_pm, 0, Qt.AlignCenter)
        lbl_pm_ind = QLabel('PHASEMASK')
        lbl_pm_ind.setFont(QFont('Consolas', 7, QFont.Bold))
        lbl_pm_ind.setStyleSheet(f'color: {FO_OFF}; background: transparent;')
        lbl_pm_ind.setAlignment(Qt.AlignCenter)
        piv.addWidget(lbl_pm_ind)
        ih.addWidget(pm_ind, 1)

        sh_ind = QWidget()
        siv = QVBoxLayout(sh_ind)
        siv.setAlignment(Qt.AlignCenter)
        siv.setContentsMargins(0, 0, 0, 0)
        self._ind_laser = IndicatorDot('shutter')
        siv.addWidget(self._ind_laser, 0, Qt.AlignCenter)
        lbl_sh_ind = QLabel('SHUTTER')
        lbl_sh_ind.setFont(QFont('Consolas', 7, QFont.Bold))
        lbl_sh_ind.setStyleSheet(f'color: {FO_OFF}; background: transparent;')
        lbl_sh_ind.setAlignment(Qt.AlignCenter)
        siv.addWidget(lbl_sh_ind)
        ih.addWidget(sh_ind, 1)

        rv.addWidget(ind_frame)

        # RUN / STOP
        btn_row = QWidget()
        br = QHBoxLayout(btn_row)
        br.setContentsMargins(0, 0, 0, 0)
        self._btn_run = _make_run_btn(self)
        self._btn_stop = _make_stop_btn(self)
        br.addWidget(self._btn_run, 3)
        br.addWidget(self._btn_stop, 1)
        rv.addWidget(btn_row)
        rv.addStretch()

        main.addWidget(left, 1)
        main.addWidget(right, 1)

        # signals
        self._btn_run.clicked.connect(self._on_run)
        self._btn_stop.clicked.connect(self._on_stop)
        self._le_freq.textChanged.connect(self._update_preview)
        self._spin_spots.valueChanged.connect(self._update_preview)

        # initial state
        self._on_spots_changed()
        self._on_bin_mode_changed()
        self._scan_pm_folder()
        self._update_preview()

    # -- path resolution ------------------------------------------------------

    def _vec_path(self) -> str:
        n = self._spin_spots.value()
        stim_folder = self.params.get('dh_stim_folder', '')
        vec_sub     = self.params.get('vec_subfolder', 'VEC')
        vec_pattern = self.params.get('dh_vec_pattern', '')
        if not stim_folder or not vec_pattern:
            return ''
        fname = vec_pattern.replace('{n_spots}', f'{n:03d}')
        p = os.path.normpath(os.path.join(stim_folder, vec_sub, fname))
        return p if os.path.isfile(p) else ''

    def _pm_path(self) -> str:
        n = self._spin_spots.value()
        stim_folder = self.params.get('dh_stim_folder', '')
        pm_sub      = self.params.get('phasemasks_subfolder', 'Phasemasks')
        pm_pattern  = self.params.get('dh_phasemask_pattern', '')
        if not stim_folder or not pm_pattern:
            return ''
        fname = pm_pattern.replace('{n_spots}', f'{n:03d}')
        return os.path.normpath(os.path.join(stim_folder, pm_sub, fname))

    # -- callbacks ------------------------------------------------------------

    def _update_preview(self):
        if self._worker:
            return
        try:
            freq = float(self._le_freq.text())
            if freq <= 0:
                raise ValueError
        except ValueError:
            self._timer_panel.set_idle()
            return
        vec_p = self._vec_path()
        if not vec_p:
            self._timer_panel.set_idle()
            return
        try:
            total = sync.count_vec_triggers(vec_p)
        except Exception:
            self._timer_panel.set_idle()
            return
        self._timer_panel.set_ready(total, freq)

    def _reconnect_slm(self):
        ok = self._slm.connect()
        self._dot_tcp.set_color(FO_ON if ok else COLOR_DIM)
        status = 'connected' if ok else 'failed'
        self.console.log(
            f'[SLM] TCP {status} ({self._slm._host}:{self._slm._port})',
            'info' if ok else 'warn')

    def _scan_pm_folder(self):
        folder  = self.params.get('wavefront_folder', '')
        pattern = self.params.get('wavefront_pattern', 'Pattern{n}_000.algoPhp.png')
        n = sync.count_spots_from_folder(folder, pattern)
        if n == 0:
            self._lbl_pm_detected.setText('0 spots found')
            self._lbl_pm_detected.setStyleSheet('color: #FF4444;')
        else:
            self._lbl_pm_detected.setText(
                f'{n} spot{"s" if n > 1 else ""} detected')
            self._lbl_pm_detected.setStyleSheet('color: #00FF00;')
            self._spin_spots.setValue(n)

    def _on_spots_changed(self):
        n       = self._spin_spots.value()
        n_str   = f'{n:03d}'
        stim    = self.params.get('dh_stim_folder', '')
        vec_sub = self.params.get('vec_subfolder', 'VEC')
        vec_pat = self.params.get('dh_vec_pattern', '')
        pm_sub  = self.params.get('phasemasks_subfolder', 'Phasemasks')
        pm_pat  = self.params.get('dh_phasemask_pattern', '')
        self._lbl_vec.setText(
            os.path.normpath(os.path.join(stim, vec_sub, vec_pat.replace('{n_spots}', n_str))))
        self._lbl_pm.setText(
            os.path.normpath(os.path.join(stim, pm_sub, pm_pat.replace('{n_spots}', n_str))))
        self._load_pm_lines()

    def _on_bin_mode_changed(self):
        mode = 'bright' if self._rb_bright.isChecked() else 'dark'
        stim    = self.params.get('dh_stim_folder', '')
        bin_sub = self.params.get('bin_subfolder', 'BIN')
        self._lbl_bin.setText(f'{os.path.normpath(os.path.join(stim, bin_sub))}  [{mode}]')

    # -- phasemask order list -------------------------------------------------

    def _load_pm_lines(self):
        pm_path = self._pm_path()
        self._pm_listbox.clear()
        self._pm_lines = []
        if not os.path.isfile(pm_path):
            return
        with open(pm_path, 'r') as f:
            lines = f.read().splitlines()
        self._pm_lines = lines  # keep all lines including repos (line 0)
        for line in self._pm_lines:
            self._pm_listbox.addItem(os.path.basename(line))
        self._pm_index = 0
        self._update_pm_highlight()

    def _update_pm_highlight(self):
        for i in range(self._pm_listbox.count()):
            item = self._pm_listbox.item(i)
            if i == self._pm_index:
                item.setBackground(QColor(FO_MID))
                item.setForeground(QColor(FO_BG))
            else:
                item.setBackground(QColor(COLOR_CARD))
                item.setForeground(QColor(COLOR_DIM))
        if 0 <= self._pm_index < self._pm_listbox.count():
            self._pm_listbox.scrollToItem(
                self._pm_listbox.item(self._pm_index))

    # -- trigger tracking slot ------------------------------------------------

    def _on_trigger_update(self, count: int):
        self._timer_panel.update_progress(
            count, self._total_triggers, self._freq_hz)

        slm = self._vec_col_slm
        sht = self._vec_col_shutter
        old = self._last_processed

        new_pm = 0
        last_shutter = self._shutter_open

        for i in range(old, min(count, len(slm))):
            if slm[i] == 1:
                new_pm += 1
            if i < len(sht):
                last_shutter = bool(sht[i])

        if new_pm > 0:
            self._pm_index = min(self._pm_index + new_pm,
                                 len(self._pm_lines) - 1)
            self._ind_pm.flash()
            self._update_pm_highlight()
            if 0 <= self._pm_index < len(self._pm_lines):
                path = self._pm_lines[self._pm_index]
                if not self._slm.send_mask(path):
                    self.console.log('[SLM] send failed — TCP disconnected', 'warn')
                    self._dot_tcp.set_color(COLOR_DIM)

        if last_shutter != self._shutter_open:
            self._shutter_open = last_shutter
            self._ind_laser.set_active(last_shutter)

        self._last_processed = count

    # -- run / stop -----------------------------------------------------------

    def _on_run(self):
        try:
            freq_hz = float(self._le_freq.text())
        except ValueError:
            QMessageBox.critical(self, 'Error', 'Invalid frequency.')
            return

        n_spots  = self._spin_spots.value()
        bin_mode = 'bright' if self._rb_bright.isChecked() else 'dark'

        if not self._acquire_run():
            self.console.log('[DH] Film.exe already running.', 'warn')
            return

        self._save_config()
        self._freq_hz = freq_hz
        self._last_processed = 0
        self._pm_index       = 0
        self._shutter_open   = False
        self._btn_run.setEnabled(False)
        self._btn_run.setText('RUNNING…')
        self._btn_stop.setEnabled(True)

        # load vec columns (swapped — see plan note)
        vec_p = self._vec_path()
        if vec_p:
            self._vec_col_slm, self._vec_col_shutter = sync.read_vec_columns(vec_p)
            n_pm  = sum(self._vec_col_slm)
            n_sht = sum(self._vec_col_shutter)
            self.console.log(
                f'[DH] Vec loaded: {len(self._vec_col_slm)} triggers, '
                f'{n_pm} phasemask events, {n_sht} shutter-open events')

        # load phasemask order
        self._load_pm_lines()

        # arm waveform output (hardware-timed shutter + SLM)
        nidaq   = self.params.get('nidaq', {})
        device  = nidaq.get('device', 'Dev1')
        pfi_clk = nidaq.get('pfi_clock', 0)
        ao_sht  = nidaq.get('ao_shutter', 0)
        ao_slm  = nidaq.get('ao_slm', 1)
        if self._vec_col_shutter and self._vec_col_slm:
            try:
                self._waveform = sync.WaveformOutput(
                    device, pfi_clk, ao_sht, ao_slm,
                    self._vec_col_shutter, self._vec_col_slm)
                self._waveform.start()
                self.console.log(
                    f'[DH] Waveform output armed ({device}/ao{ao_sht}+ao{ao_slm}, '
                    f'clocked on PFI{pfi_clk})')
            except Exception as e:
                self._waveform = None
                self.console.log(f'[DH] Waveform output unavailable: {e}', 'warn')

        # arm counter + worker
        self._arm_worker(freq_hz)

        def _run():
            try:
                self._proc = dmd.run_dh(
                    n_spots, bin_mode, freq_hz,
                    self.params, self.console.log)
                _active_procs.append(self._proc)
                self._proc.wait()
                if self._proc.returncode not in (0, -1, 1):
                    self.console.log(
                        f'[DMD] film.exe unexpectedly closed (code {self._proc.returncode})', 'warn')
            except Exception as e:
                self.console.log(f'[DH] ERROR: {e}', 'error')
            finally:
                if self._proc in _active_procs:
                    _active_procs.remove(self._proc)
                self._request_cleanup.emit()

        threading.Thread(target=_run, daemon=True).start()

    def _on_stop(self):
        dmd.stop(getattr(self, '_proc', None), self.params.get('film_exe', ''))
        self.console.log('[DH] Protocol interrupted.', 'warn')

    def _arm_worker(self, freq_hz: float):
        total = 0
        vec_p = self._vec_path()
        if vec_p:
            try:
                total = sync.count_vec_triggers(vec_p)
            except Exception as e:
                self.console.log(f'[DH] Cannot read vec: {e}', 'warn')

        self._total_triggers = total
        nidaq   = self.params.get('nidaq', {})
        device  = nidaq.get('device', 'Dev1')
        pfi_idx = nidaq.get('pfi_clock', 0)
        try:
            self._counter = sync.TriggerCounter(device, pfi_idx)
            self.console.log(
                f'[DH] NI-DAQ trigger counter armed ({device}/PFI{pfi_idx})')
        except Exception as e:
            self._counter = None
            self.console.log(f'[DH] NI-DAQ counter unavailable: {e}', 'warn')

        timeout = self.params.get('trigger_timeout_s', 10)
        self._timer_panel.set_armed(total, freq_hz)

        ok = self._slm.connect()
        self._dot_tcp.set_color(FO_ON if ok else COLOR_DIM)
        if not ok:
            self.console.log('[SLM] TCP connection failed — phasemask sending disabled', 'warn')

        self._worker = TriggerWorker(self._counter, total, timeout)
        self._thread = QThread()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.trigger_update.connect(self._on_trigger_update)
        self._worker.stim_started.connect(self._on_stim_started)
        self._worker.stim_complete.connect(self._on_complete)
        self._worker.stim_timeout.connect(self._on_timeout)
        self._worker.finished.connect(self._thread.quit)
        self._thread.start()

    @Slot()
    def _on_stim_started(self):
        self.console.log('[DH] >> STIM STARTED')

    @Slot()
    def _on_complete(self):
        self._timer_panel.set_complete()
        self.console.log('[DH] ■ STIM COMPLETE')
        dmd.stop(self._proc, self.params.get('film_exe', ''))

    @Slot()
    def _on_timeout(self):
        timeout = self.params.get('trigger_timeout_s', 10)
        self.console.log(f'[DH] ■ No trigger for {timeout}s — stopping', 'warn')
        dmd.stop(self._proc, self.params.get('film_exe', ''))

    @Slot()
    def _do_cleanup(self):
        """Runs in main thread via signal — safe to touch Qt widgets."""
        if self._worker:
            self._worker.stop()
            self._worker = None
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(2000)
            self._thread = None
        if self._counter:
            self._counter.close()
            self._counter = None
        if self._waveform:
            self._waveform.close()
            self._waveform = None
        self._ind_laser.set_active(False)
        self._shutter_open = False
        self._slm.disconnect()
        self._dot_tcp.set_color(COLOR_DIM)
        self._release_run()

    def reset_ui(self):
        self._btn_run.setEnabled(True)
        self._btn_run.setText('RUN PROTOCOL')
        self._btn_stop.setEnabled(False)
        self._pm_index     = 0
        self._shutter_open = False
        self._ind_laser.set_active(False)
        self._update_pm_highlight()
        self._update_preview()


# ═════════════════════════════════════════════════════════════════════════════
# ── VDH tab ──────────────────────────────────────────────────────────────────
# ═════════════════════════════════════════════════════════════════════════════

class VdhTab(QWidget):

    _tab_prefix = '[VDH]'
    _request_cleanup = Signal()

    def __init__(self, console: ConsoleLog, params: dict, config: dict,
                 save_config, acquire_run, release_run):
        super().__init__()
        self.console      = console
        self.params       = params
        self.config       = config
        self._save_config = save_config
        self._acquire_run = acquire_run
        self._release_run = release_run
        self._proc        = None
        self._worker      = None
        self._thread      = None
        self._counter     = None
        self._total_triggers = 0
        self._freq_hz        = 0.0
        self._request_cleanup.connect(self._do_cleanup)
        self._build()

    def _build(self):
        cfg = self.config
        main = QHBoxLayout(self)
        main.setContentsMargins(8, 8, 8, 8)
        main.setSpacing(12)

        # ── left column ──
        left = QWidget()
        left.setMinimumWidth(360)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)

        # DMD
        files_grp = QGroupBox('DMD')
        fl = QVBoxLayout(files_grp)

        self._folder_row, self._le_folder = _make_folder_row(
            files_grp, 'Binvec folder',
            cfg.get('vdh_binvec_folder', ''),
            on_select=self._on_folder_selected,
            initialdir=self.params.get('binvecs_root', ''))
        fl.addWidget(self._folder_row)

        bin_row = QWidget()
        bh = QHBoxLayout(bin_row)
        bh.setContentsMargins(0, 0, 0, 0)
        bh.addWidget(QLabel('.bin file'))
        self._combo_bin = QComboBox()
        bh.addWidget(self._combo_bin, 1)
        fl.addWidget(bin_row)

        vec_row = QWidget()
        vch = QHBoxLayout(vec_row)
        vch.setContentsMargins(0, 0, 0, 0)
        vch.addWidget(QLabel('.vec file'))
        self._combo_vec = QComboBox()
        vch.addWidget(self._combo_vec, 1)
        fl.addWidget(vec_row)

        pm_row = QWidget()
        pmh = QHBoxLayout(pm_row)
        pmh.setContentsMargins(0, 0, 0, 0)
        pmh.addWidget(QLabel('Phase mask'))
        self._combo_pm = QComboBox()
        pmh.addWidget(self._combo_pm, 1)
        fl.addWidget(pm_row)

        freq_row = QWidget()
        fh = QHBoxLayout(freq_row)
        fh.setContentsMargins(0, 0, 0, 0)
        fh.addWidget(QLabel('Rate (Hz):'))
        self._le_freq = QLineEdit(str(cfg.get('vdh_freq', 20.0)))
        self._le_freq.setFixedWidth(80)
        fh.addWidget(self._le_freq)
        fh.addStretch()
        fl.addWidget(freq_row)

        lv.addWidget(files_grp)

        # Phasemask detection
        pm_grp = QGroupBox('Phasemask detection')
        pml = QVBoxLayout(pm_grp)

        pm_folder_row = QWidget()
        pfh = QHBoxLayout(pm_folder_row)
        pfh.setContentsMargins(0, 0, 0, 0)
        self._lbl_pm_folder = ElidedLabel(self.params.get('wavefront_folder', '—'))
        self._lbl_pm_folder.setStyleSheet(f'color: {COLOR_DIM};')
        pfh.addWidget(self._lbl_pm_folder, 1)
        btn_open = QPushButton('Open')
        btn_open.setFixedWidth(50)
        btn_open.clicked.connect(
            lambda: open_folder(self.params.get('wavefront_folder', '')))
        pfh.addWidget(btn_open)
        pml.addWidget(pm_folder_row)

        det_row = QWidget()
        drh = QHBoxLayout(det_row)
        drh.setContentsMargins(0, 0, 0, 0)
        self._lbl_pm_detected = QLabel('—')
        self._lbl_pm_detected.setStyleSheet(f'color: {COLOR_DIM};')
        drh.addWidget(self._lbl_pm_detected, 1)
        btn_scan = QPushButton('Scan')
        btn_scan.setFixedWidth(50)
        btn_scan.clicked.connect(self._scan_pm_folder)
        drh.addWidget(btn_scan)
        pml.addWidget(det_row)

        fmt_row = QWidget()
        fmh = QHBoxLayout(fmt_row)
        fmh.setContentsMargins(0, 0, 0, 0)
        fmh.addWidget(QLabel('Format:'))
        self._le_autopattern = QLineEdit(
            cfg.get('vdh_autopattern',
                     self.params.get('vdh_autopattern', '_{n_spots}spots')))
        fmh.addWidget(self._le_autopattern, 1)
        btn_auto = QPushButton('Auto-select')
        btn_auto.clicked.connect(lambda: self._auto_select())
        fmh.addWidget(btn_auto)
        pml.addWidget(fmt_row)

        lv.addWidget(pm_grp)
        lv.addStretch()

        # ── right column ──
        right = QWidget()
        right.setMinimumWidth(340)
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)

        # Timer
        self._timer_panel = SciTimerPanel()
        rv.addWidget(self._timer_panel)

        # RUN / STOP
        btn_row = QWidget()
        br = QHBoxLayout(btn_row)
        br.setContentsMargins(0, 0, 0, 0)
        self._btn_run = _make_run_btn(self)
        self._btn_stop = _make_stop_btn(self)
        br.addWidget(self._btn_run, 3)
        br.addWidget(self._btn_stop, 1)
        rv.addWidget(btn_row)
        rv.addStretch()

        main.addWidget(left, 1)
        main.addWidget(right, 1)

        # signals
        self._btn_run.clicked.connect(self._on_run)
        self._btn_stop.clicked.connect(self._on_stop)
        self._le_freq.textChanged.connect(self._update_preview)
        self._combo_vec.currentTextChanged.connect(self._update_preview)

        # populate from config
        if cfg.get('vdh_binvec_folder'):
            self._on_folder_selected(cfg['vdh_binvec_folder'])
        if cfg.get('vdh_bin_name'):
            self._combo_bin.setCurrentText(cfg['vdh_bin_name'])
        if cfg.get('vdh_vec_name'):
            self._combo_vec.setCurrentText(cfg['vdh_vec_name'])
        if cfg.get('vdh_pm_name'):
            self._combo_pm.setCurrentText(cfg['vdh_pm_name'])
        self._scan_pm_folder()
        self._update_preview()

    # -- paths ----------------------------------------------------------------

    def _vec_path(self) -> str:
        folder   = self._le_folder.text()
        vec_name = self._combo_vec.currentText()
        if not folder or not vec_name:
            return ''
        sub = self.params.get('vec_subfolder', 'VEC')
        p = os.path.normpath(os.path.join(folder, sub, vec_name))
        return p if os.path.isfile(p) else ''

    # -- callbacks ------------------------------------------------------------

    def _update_preview(self):
        if self._worker:
            return
        try:
            freq = float(self._le_freq.text())
            if freq <= 0:
                raise ValueError
        except ValueError:
            self._timer_panel.set_idle()
            return
        vec_p = self._vec_path()
        if not vec_p:
            self._timer_panel.set_idle()
            return
        try:
            total = sync.count_vec_triggers(vec_p)
        except Exception:
            self._timer_panel.set_idle()
            return
        self._timer_panel.set_ready(total, freq)

    def _on_folder_selected(self, folder: str):
        self._le_folder.setText(folder)
        bin_files, vec_files, pm_files = scan_binvec_folder(folder, self.params)
        self._combo_bin.clear()
        self._combo_bin.addItems(bin_files)
        self._combo_vec.clear()
        self._combo_vec.addItems(vec_files)
        self._combo_pm.clear()
        self._combo_pm.addItems(pm_files)

    def _open_pm_folder(self):
        open_folder(self.params.get('wavefront_folder', ''))

    def _scan_pm_folder(self):
        folder  = self.params.get('wavefront_folder', '')
        pattern = self.params.get('wavefront_pattern', 'Pattern{n}_000.algoPhp.png')
        n = sync.count_spots_from_folder(folder, pattern)
        if n == 0:
            self._lbl_pm_detected.setText('0 spots found')
            self._lbl_pm_detected.setStyleSheet('color: #FF4444;')
            return
        self._lbl_pm_detected.setText(
            f'{n} spot{"s" if n > 1 else ""} detected')
        self._lbl_pm_detected.setStyleSheet('color: #00FF00;')
        self._auto_select(n)

    def _auto_select(self, n: int = None):
        if n is None:
            folder  = self.params.get('wavefront_folder', '')
            pattern = self.params.get('wavefront_pattern', 'Pattern{n}_000.algoPhp.png')
            n = sync.count_spots_from_folder(folder, pattern)
        if not n:
            return
        substr = self._le_autopattern.text().replace('{n_spots}', str(n))
        for i in range(self._combo_vec.count()):
            if substr in self._combo_vec.itemText(i):
                self._combo_vec.setCurrentIndex(i)
                break
        for i in range(self._combo_pm.count()):
            if substr in self._combo_pm.itemText(i):
                self._combo_pm.setCurrentIndex(i)
                break

    # -- run / stop -----------------------------------------------------------

    def _on_run(self):
        folder   = self._le_folder.text()
        bin_name = self._combo_bin.currentText()
        vec_name = self._combo_vec.currentText()
        if not folder or not bin_name or not vec_name:
            QMessageBox.critical(self, 'Error',
                                 'Select a folder, BIN and VEC file.')
            return
        try:
            freq_hz = float(self._le_freq.text())
        except ValueError:
            QMessageBox.critical(self, 'Error', 'Invalid frequency.')
            return
        if not self._acquire_run():
            self.console.log('[VDH] Film.exe already running.', 'warn')
            return

        self._save_config()
        self._freq_hz = freq_hz
        self._btn_run.setEnabled(False)
        self._btn_run.setText('RUNNING…')
        self._btn_stop.setEnabled(True)

        self._arm_worker(freq_hz)

        def _run():
            try:
                self._proc = dmd.run_vdh(
                    folder, bin_name, vec_name, freq_hz,
                    self.params, self.console.log)
                _active_procs.append(self._proc)
                self._proc.wait()
                if self._proc.returncode not in (0, -1, 1):
                    self.console.log(
                        f'[DMD] film.exe unexpectedly closed (code {self._proc.returncode})', 'warn')
            except Exception as e:
                self.console.log(f'[VDH] ERROR: {e}', 'error')
            finally:
                if self._proc in _active_procs:
                    _active_procs.remove(self._proc)
                self._request_cleanup.emit()

        threading.Thread(target=_run, daemon=True).start()

    def _on_stop(self):
        dmd.stop(getattr(self, '_proc', None), self.params.get('film_exe', ''))
        self.console.log('[VDH] Protocol interrupted.', 'warn')

    def _arm_worker(self, freq_hz: float):
        total = 0
        vec_p = self._vec_path()
        if vec_p:
            try:
                total = sync.count_vec_triggers(vec_p)
            except Exception as e:
                self.console.log(f'[VDH] Cannot read vec: {e}', 'warn')

        self._total_triggers = total
        nidaq   = self.params.get('nidaq', {})
        device  = nidaq.get('device', 'Dev1')
        pfi_idx = nidaq.get('pfi_clock', 0)
        try:
            self._counter = sync.TriggerCounter(device, pfi_idx)
            self.console.log(
                f'[VDH] NI-DAQ counter armed ({device}/PFI{pfi_idx})')
        except Exception as e:
            self._counter = None
            self.console.log(f'[VDH] NI-DAQ counter unavailable: {e}', 'warn')

        timeout = self.params.get('trigger_timeout_s', 10)
        self._timer_panel.set_armed(total, freq_hz)

        self._worker = TriggerWorker(self._counter, total, timeout)
        self._thread = QThread()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.trigger_update.connect(self._on_trigger_update)
        self._worker.stim_started.connect(self._on_stim_started)
        self._worker.stim_complete.connect(self._on_complete)
        self._worker.stim_timeout.connect(self._on_timeout)
        self._worker.finished.connect(self._thread.quit)
        self._thread.start()

    @Slot(int)
    def _on_trigger_update(self, count: int):
        self._timer_panel.update_progress(count, self._total_triggers, self._freq_hz)

    @Slot()
    def _on_stim_started(self):
        self.console.log('[VDH] >> STIM STARTED')

    @Slot()
    def _on_complete(self):
        self._timer_panel.set_complete()
        self.console.log('[VDH] ■ STIM COMPLETE')
        dmd.stop(self._proc, self.params.get('film_exe', ''))

    @Slot()
    def _on_timeout(self):
        timeout = self.params.get('trigger_timeout_s', 10)
        self.console.log(f'[VDH] ■ No trigger for {timeout}s — stopping', 'warn')
        dmd.stop(self._proc, self.params.get('film_exe', ''))

    @Slot()
    def _do_cleanup(self):
        """Runs in main thread via signal — safe to touch Qt widgets."""
        if self._worker:
            self._worker.stop()
            self._worker = None
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(2000)
            self._thread = None
        if self._counter:
            self._counter.close()
            self._counter = None
        self._release_run()

    def reset_ui(self):
        self._btn_run.setEnabled(True)
        self._btn_run.setText('RUN PROTOCOL')
        self._btn_stop.setEnabled(False)
        self._update_preview()


# ═════════════════════════════════════════════════════════════════════════════
# ── main application window ──────────────────────────────────────────────────
# ═════════════════════════════════════════════════════════════════════════════

class PlerionApp(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle('Plerion')
        self.setMinimumSize(1100, 680)

        self.params  = load_json(PARAMS_FILE, {})
        self.config  = load_json(CONFIG_FILE, {})
        self._running = False

        self._build()

    def _build(self):
        central = QWidget()
        self.setCentralWidget(central)
        vbox = QVBoxLayout(central)
        vbox.setContentsMargins(8, 8, 8, 8)
        vbox.setSpacing(4)

        self._tabs = QTabWidget()
        vbox.addWidget(self._tabs, 1)

        console_hdr = QWidget()
        chr_ = QHBoxLayout(console_hdr)
        chr_.setContentsMargins(0, 0, 0, 0)
        lbl_console = QLabel('Console')
        lbl_console.setStyleSheet('font-weight: bold;')
        chr_.addWidget(lbl_console)
        chr_.addStretch()
        btn_export = QPushButton('Export log')
        btn_export.setFixedWidth(90)
        btn_export.clicked.connect(self._export_log)
        chr_.addWidget(btn_export)
        vbox.addWidget(console_hdr)
        self.console = ConsoleLog()
        self.console.setMaximumHeight(260)
        vbox.addWidget(self.console)

        self.vis_tab = VisualTab(self.console, self.params, self.config,
                                  self._save_config, self._acquire_run,
                                  self._release_run)
        self.dh_tab  = DhTab(self.console, self.params, self.config,
                              self._save_config, self._acquire_run,
                              self._release_run)
        self.vdh_tab = VdhTab(self.console, self.params, self.config,
                               self._save_config, self._acquire_run,
                               self._release_run)

        self._tabs.addTab(self.vis_tab, '  Visual  ')
        self._tabs.addTab(self.dh_tab,  '  DH      ')
        self._tabs.addTab(self.vdh_tab, '  VDH     ')

        # NI-DAQ probe
        device = self.params.get('nidaq', {}).get('device', 'Dev1')
        nidaq_ok = sync.probe_nidaq(device)
        sb = self.statusBar()
        sb.setStyleSheet(f'background: {COLOR_BG}; color: {COLOR_TEXT};')
        dot = StatusDot(FO_ON if nidaq_ok else COLOR_DIM)
        sb.addPermanentWidget(dot)
        lbl_daq = QLabel(f'NI-DAQ {device}')
        lbl_daq.setStyleSheet(f'color: {FO_ON if nidaq_ok else COLOR_DIM}; padding-right: 6px;')
        sb.addPermanentWidget(lbl_daq)

        if nidaq_ok:
            self.console.log(f'NI-DAQ {device} detected.')
        else:
            self.console.log(f'NI-DAQ {device} not found — hardware features disabled.', 'warn')
        self.console.log('Plerion ready.')

    def _acquire_run(self) -> bool:
        if self._running:
            return False
        self._running = True
        return True

    def _release_run(self):
        self._running = False
        for tab in (self.vis_tab, self.dh_tab, self.vdh_tab):
            tab.reset_ui()

    def _export_log(self):
        path, _ = QFileDialog.getSaveFileName(
            self, 'Export log', 'plerion_log.txt', 'Text files (*.txt);;All files (*)')
        if not path:
            return
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(self.console.toPlainText())
        except Exception as e:
            self.console.log(f'Export failed: {e}', 'error')

    def _save_config(self):
        save_json(CONFIG_FILE, self._collect_config())

    def _collect_config(self) -> dict:
        vi = self.vis_tab
        d  = self.dh_tab
        v  = self.vdh_tab
        try:
            vis_freq = float(vi._le_freq.text() or 20)
        except ValueError:
            vis_freq = 20.0
        try:
            dh_freq = float(d._le_freq.text() or 20)
        except ValueError:
            dh_freq = 20.0
        try:
            vdh_freq = float(v._le_freq.text() or 20)
        except ValueError:
            vdh_freq = 20.0
        return {
            'vis_binvec_folder':    vi._le_folder.text(),
            'vis_bin_name':         vi._combo_bin.currentText(),
            'vis_vec_name':         vi._combo_vec.currentText(),
            'vis_freq':             vis_freq,
            'dh_freq':              dh_freq,
            'dh_n_spots':           d._spin_spots.value(),
            'dh_bin_mode':          'bright' if d._rb_bright.isChecked() else 'dark',
            'vdh_binvec_folder':    v._le_folder.text(),
            'vdh_bin_name':         v._combo_bin.currentText(),
            'vdh_vec_name':         v._combo_vec.currentText(),
            'vdh_pm_name':          v._combo_pm.currentText(),
            'vdh_freq':             vdh_freq,
            'vdh_autopattern':      v._le_autopattern.text(),
        }

    def closeEvent(self, event):
        self._save_config()
        for tab in (self.vis_tab, self.dh_tab, self.vdh_tab):
            # Stop worker thread first
            if getattr(tab, '_worker', None):
                tab._worker.stop()
            if getattr(tab, '_thread', None) and tab._thread.isRunning():
                tab._thread.quit()
                tab._thread.wait(1000)
            # Kill film.exe
            dmd.stop(getattr(tab, '_proc', None), self.params.get('film_exe', ''))
            # Release hardware
            if getattr(tab, '_counter', None):
                tab._counter.close()
            if getattr(tab, '_waveform', None):
                tab._waveform.close()
        event.accept()


# ── entry point ──────────────────────────────────────────────────────────────

# Global registry of active film.exe procs — killed on exit/crash
_active_procs: list = []


def _kill_all_procs():
    for proc in _active_procs:
        try:
            if proc and proc.poll() is None:
                proc.terminate()
        except Exception:
            pass


atexit.register(_kill_all_procs)

# Handle SIGTERM / Ctrl-C
def _signal_handler(sig, frame):
    _kill_all_procs()
    sys.exit(0)

signal.signal(signal.SIGTERM, _signal_handler)
signal.signal(signal.SIGINT,  _signal_handler)


def main():
    app = QApplication(sys.argv)
    app.setFont(QFont('Segoe UI', 9))
    apply_dark_theme(app)
    window = PlerionApp()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
