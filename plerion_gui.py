"""
plerion_gui.py — Main Tkinter GUI for Plerion.

Two tabs:
  VDH — full experiment mode (DMD + NI-DAQ + SLM)
  DH  — digital holography simplified mode

Functional logic is not implemented yet; this module contains only the UI layout.
"""

import os
import re
import sys
import time
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from jsonc_parser.parser import JsoncParser

sys.path.insert(0, os.path.dirname(__file__))
from modules import dmd, sync

# ── constants ────────────────────────────────────────────────────────────────

COLOR_BG     = '#121212'
COLOR_CARD   = '#1E1E1E'
COLOR_TEXT   = '#E0E0E0'
COLOR_DIM    = '#555555'
COLOR_BTN    = '#2A2A2A'
COLOR_ACCENT = '#2D6A9F'

# ── Fallout phosphor palette (VisualTab timer panel) ─────────────────────────
FO_BG    = '#060A06'   # near-black terminal background
FO_OFF   = '#0D2A0D'   # idle — barely visible
FO_DIM   = '#1A5A1A'   # ready — dim phosphor
FO_MID   = '#3A8A3A'   # armed — medium glow
FO_ON    = '#4AFC4A'   # active — full phosphor brightness

PARAMS_FILE = os.path.join(os.path.dirname(__file__), 'plerion_params.jsonc')
CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'plerion_config.jsonc')

# ── helpers ──────────────────────────────────────────────────────────────────

def load_json(path: str, default: dict) -> dict:
    try:
        return JsoncParser.parse_file(path)
    except Exception:
        return default


def save_json(path: str, data: dict) -> None:
    import json
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


def _fmt_remaining(secs: float) -> str:
    """Format remaining seconds as 'Xh Ym' or 'Xm Ys' using floor."""
    s = int(secs)
    if s >= 3600:
        h = s // 3600
        m = (s % 3600) // 60
        return f'{h}h {m:02d}m'
    m = s // 60
    s = s % 60
    return f'{m}m {s:02d}s'


def _fmt_countdown(secs: float) -> str:
    """Format as H:MM:SS or MM:SS (floor, digital-clock style)."""
    s = int(secs)
    h = s // 3600
    m = (s % 3600) // 60
    ss = s % 60
    if h:
        return f'{h}:{m:02d}:{ss:02d}'
    return f'{m:02d}:{ss:02d}'


def apply_dark_style(root: tk.Tk) -> ttk.Style:
    style = ttk.Style(root)
    style.theme_use('clam')

    style.configure('.',
                    background=COLOR_BG,
                    foreground=COLOR_TEXT,
                    fieldbackground=COLOR_CARD,
                    troughcolor=COLOR_CARD,
                    bordercolor=COLOR_CARD,
                    darkcolor=COLOR_BG,
                    lightcolor=COLOR_CARD,
                    insertcolor=COLOR_TEXT,
                    selectbackground=COLOR_ACCENT,
                    selectforeground=COLOR_TEXT)

    style.configure('TFrame',  background=COLOR_BG)
    style.configure('TLabel',  background=COLOR_BG, foreground=COLOR_TEXT)
    style.configure('TEntry',  fieldbackground=COLOR_CARD, foreground=COLOR_TEXT,
                    insertcolor=COLOR_TEXT)
    style.configure('TButton', background=COLOR_BTN, foreground=COLOR_TEXT,
                    relief='flat', padding=4)
    style.map('TButton',
              background=[('active', COLOR_ACCENT), ('pressed', COLOR_ACCENT)])

    style.configure('TCheckbutton', background=COLOR_BG, foreground=COLOR_TEXT)
    style.configure('TRadiobutton', background=COLOR_BG, foreground=COLOR_TEXT)
    style.configure('TCombobox', fieldbackground=COLOR_CARD, foreground=COLOR_TEXT,
                    background=COLOR_BTN, arrowcolor=COLOR_TEXT,
                    selectbackground=COLOR_ACCENT, selectforeground=COLOR_TEXT)
    style.map('TCombobox',
              fieldbackground=[('readonly', COLOR_CARD), ('disabled', COLOR_BG)],
              foreground=[('readonly', COLOR_TEXT), ('disabled', COLOR_DIM)],
              selectbackground=[('readonly', COLOR_ACCENT)],
              selectforeground=[('readonly', COLOR_TEXT)])
    style.configure('TSpinbox',     fieldbackground=COLOR_CARD, foreground=COLOR_TEXT,
                    arrowcolor=COLOR_TEXT)
    style.configure('TNotebook',    background=COLOR_BG, tabmargins=[2, 2, 2, 0])
    style.configure('TNotebook.Tab', background=COLOR_CARD, foreground=COLOR_TEXT,
                    padding=[10, 4])
    style.map('TNotebook.Tab',
              background=[('selected', COLOR_ACCENT)],
              foreground=[('selected', '#FFFFFF')])
    style.configure('TProgressbar', troughcolor=COLOR_CARD, background=COLOR_ACCENT)
    style.configure('Card.TFrame',  background=COLOR_CARD, relief='flat')
    style.configure('Card.TLabel',  background=COLOR_CARD, foreground=COLOR_TEXT)

    # Combobox dropdown list (Listbox) doesn't inherit ttk theme
    root.option_add('*Listbox.background',       '#D6E4F0')
    root.option_add('*Listbox.foreground',       '#000000')
    root.option_add('*Listbox.selectBackground', COLOR_ACCENT)
    root.option_add('*Listbox.selectForeground', '#FFFFFF')

    return style


def make_status_dot(parent: tk.Widget, color: str = COLOR_DIM) -> tk.Canvas:
    """Small coloured circle used as a connection status indicator."""
    try:
        bg = parent.cget('background')
    except tk.TclError:
        bg = COLOR_CARD
    c = tk.Canvas(parent, width=14, height=14, bg=bg, highlightthickness=0)
    c.create_oval(2, 2, 12, 12, fill=color, outline='', tags='dot')
    return c



def make_folder_picker_row(parent: tk.Widget, label: str, var: tk.StringVar,
                            on_select=None, initialdir: str = None) -> ttk.Frame:
    """Label + Entry + Browse button for folder selection."""
    row = ttk.Frame(parent, style='Card.TFrame')
    ttk.Label(row, text=label, width=22, anchor='w',
              style='Card.TLabel').pack(side='left', padx=(6, 2))
    entry = ttk.Entry(row, textvariable=var)
    entry.pack(side='left', fill='x', expand=True, padx=2)

    def browse():
        path = filedialog.askdirectory(initialdir=initialdir)
        if path:
            var.set(path)
            if on_select:
                on_select(path)

    ttk.Button(row, text='…', width=3, command=browse).pack(side='left', padx=(2, 6))
    return row


def scan_binvec_folder(folder: str, params: dict = None):
    """Return (bin_files, vec_files, pm_files) sorted lists using subfolder
    names from params (bin_subfolder, vec_subfolder, phasemasks_subfolder)."""
    p = params or {}
    def list_dir(sub: str):
        path = os.path.join(folder, sub)
        if os.path.isdir(path):
            return sorted(f for f in os.listdir(path) if not f.startswith('.'))
        return []

    bin_files = list_dir(p.get('bin_subfolder',       'BIN'))
    vec_files = list_dir(p.get('vec_subfolder',       'VEC'))
    pm_files  = list_dir(p.get('phasemasks_subfolder','Phasemasks'))
    return bin_files, vec_files, pm_files


def make_port_row(parent: tk.Widget, label: str, port_var: tk.StringVar,
                  btn_text: str, btn_cmd,
                  state: str = 'normal'):
    """COM port combobox + action button + status dot on one row.
    Returns (row_frame, combobox, button, dot_canvas).
    """
    row = ttk.Frame(parent, style='Card.TFrame')
    ttk.Label(row, text=label, width=14, anchor='w',
              style='Card.TLabel').pack(side='left', padx=(6, 2))
    combo = ttk.Combobox(row, textvariable=port_var, width=9, state=state)
    combo['values'] = [f'COM{i}' for i in range(1, 17)]
    combo.pack(side='left', padx=2)
    btn = ttk.Button(row, text=btn_text, command=btn_cmd, state=state)
    btn.pack(side='left', padx=(4, 4))
    dot = make_status_dot(row)
    dot.pack(side='left', padx=(4, 6))
    return row, combo, btn, dot


# ── console log widget ───────────────────────────────────────────────────────

class ConsoleLog(tk.Text):
    """Shared read-only console with coloured log levels."""

    TAGS = {
        'info':  {'foreground': '#00FF00'},
        'warn':  {'foreground': '#FFD700'},
        'error': {'foreground': '#FF4444'},
        'freq':  {'foreground': '#00CCFF'},
    }

    def __init__(self, parent, **kwargs):
        kwargs.setdefault('bg',          '#0A0A0A')
        kwargs.setdefault('fg',          '#00FF00')
        kwargs.setdefault('font',        ('Consolas', 9))
        kwargs.setdefault('state',       'disabled')
        kwargs.setdefault('relief',      'flat')
        kwargs.setdefault('borderwidth', 0)
        kwargs.setdefault('wrap',        'word')
        super().__init__(parent, **kwargs)
        for tag, cfg in self.TAGS.items():
            self.tag_configure(tag, **cfg)

    def log(self, message: str, level: str = 'info') -> None:
        self.config(state='normal')
        self.insert('end', message + '\n', level)
        self.see('end')
        self.config(state='disabled')

    def clear(self) -> None:
        self.config(state='normal')
        self.delete('1.0', 'end')
        self.config(state='disabled')


# ── VDH tab ──────────────────────────────────────────────────────────────────

class VdhTab(ttk.Frame):
    def __init__(self, parent, console: ConsoleLog, params: dict, config: dict,
                 save_config=None, acquire_run=None, release_run=None):
        super().__init__(parent)
        self.console       = console
        self.params        = params
        self.config        = config
        self._save_config  = save_config  or (lambda: None)
        self._acquire_run  = acquire_run  or (lambda: True)
        self._release_run  = release_run  or (lambda: None)
        self._build()

    def _init_vars(self):
        cfg = self.config
        self.var_binvec_folder = tk.StringVar(
            value=cfg.get('vdh_binvec_folder',
                          self.params.get('vdh_default_binvec_folder', '')))
        self.var_bin_name      = tk.StringVar(value=cfg.get('vdh_bin_name', ''))
        self.var_vec_name      = tk.StringVar(value=cfg.get('vdh_vec_name', ''))
        self.var_pm_name       = tk.StringVar(value=cfg.get('vdh_pm_name', ''))
        self.var_freq          = tk.StringVar(value=str(cfg.get('vdh_freq', 20.0)))
        self.var_slm_port      = tk.StringVar(value=cfg.get('vdh_arduino_slm_port', ''))
        self.var_autopattern = tk.StringVar(
            value=cfg.get('vdh_autopattern',
                          self.params.get('vdh_autopattern', '_{n_spots}spots_')))

    def _build(self):
        self._init_vars()
        self.configure(style='TFrame')
        self.columnconfigure(0, weight=1, minsize=360)
        self.columnconfigure(1, weight=1, minsize=340)
        self.rowconfigure(0, weight=1)

        left  = ttk.Frame(self, padding=8)
        right = ttk.Frame(self, padding=8)
        left.grid( row=0, column=0, sticky='nsew')
        right.grid(row=0, column=1, sticky='nsew')

        self._build_left(left)
        self._build_right(right)

    # -- left column ----------------------------------------------------------

    def _build_left(self, parent):
        parent.columnconfigure(0, weight=1)

        files_card = ttk.LabelFrame(parent, text='Files', padding=6)
        files_card.grid(row=0, column=0, sticky='ew', pady=(0, 8))
        files_card.columnconfigure(0, weight=1)

        # Binvec folder picker
        folder_row = make_folder_picker_row(
            files_card, 'Binvec folder',
            self.var_binvec_folder,
            on_select=self._on_folder_selected,
            initialdir=self.params.get('binvecs_root', '/'))
        folder_row.grid(row=0, column=0, sticky='ew', pady=2)

        # BIN dropdown
        bin_row = ttk.Frame(files_card, style='Card.TFrame')
        bin_row.grid(row=1, column=0, sticky='ew', pady=2)
        bin_row.columnconfigure(1, weight=1)
        ttk.Label(bin_row, text='.bin file', width=22, anchor='w',
                  style='Card.TLabel').grid(row=0, column=0, padx=(6, 2))
        self._combo_bin = ttk.Combobox(bin_row, textvariable=self.var_bin_name,
                                       state='readonly')
        self._combo_bin.grid(row=0, column=1, sticky='ew', padx=(2, 6), pady=2)

        # VEC dropdown
        vec_row = ttk.Frame(files_card, style='Card.TFrame')
        vec_row.grid(row=2, column=0, sticky='ew', pady=2)
        vec_row.columnconfigure(1, weight=1)
        ttk.Label(vec_row, text='.vec file', width=22, anchor='w',
                  style='Card.TLabel').grid(row=0, column=0, padx=(6, 2))
        self._combo_vec = ttk.Combobox(vec_row, textvariable=self.var_vec_name,
                                       state='readonly')
        self._combo_vec.grid(row=0, column=1, sticky='ew', padx=(2, 6), pady=2)

        # Phase mask dropdown
        pm_row = ttk.Frame(files_card, style='Card.TFrame')
        pm_row.grid(row=3, column=0, sticky='ew', pady=2)
        pm_row.columnconfigure(1, weight=1)
        ttk.Label(pm_row, text='Phase mask', width=22, anchor='w',
                  style='Card.TLabel').grid(row=0, column=0, padx=(6, 2))
        self._combo_pm = ttk.Combobox(pm_row, textvariable=self.var_pm_name,
                                      state='readonly')
        self._combo_pm.grid(row=0, column=1, sticky='ew', padx=(2, 6), pady=2)

        # Populate dropdowns if folder already set (restored from config)
        if self.var_binvec_folder.get():
            self._on_folder_selected(self.var_binvec_folder.get())

        # Phasemask detection
        pm_card = ttk.LabelFrame(parent, text='Phasemask detection', padding=6)
        pm_card.grid(row=1, column=0, sticky='ew', pady=(0, 8))
        pm_card.columnconfigure(1, weight=1)

        ttk.Label(pm_card, text='Folder:').grid(row=0, column=0, sticky='nw', padx=6, pady=2)
        pm_folder_row = ttk.Frame(pm_card, style='Card.TFrame')
        pm_folder_row.grid(row=0, column=1, sticky='ew', padx=(2, 6), pady=2)
        pm_folder_row.columnconfigure(0, weight=1)
        self._lbl_pm_folder = ttk.Label(pm_folder_row,
            text=self.params.get('wavefront_folder', '—'),
            foreground=COLOR_DIM, wraplength=280, justify='left')
        self._lbl_pm_folder.grid(row=0, column=0, sticky='w')
        ttk.Button(pm_folder_row, text='Open', width=5,
                   command=self._open_pm_folder).grid(row=0, column=1, padx=(4, 0))

        det_row = ttk.Frame(pm_card, style='Card.TFrame')
        det_row.grid(row=1, column=0, columnspan=2, sticky='ew', padx=6, pady=(0, 4))
        self._lbl_pm_detected = ttk.Label(det_row, text='—', foreground=COLOR_DIM)
        self._lbl_pm_detected.pack(side='left')
        ttk.Button(det_row, text='Scan', width=5,
                   command=self._scan_pm_folder).pack(side='right')

        fmt_row = ttk.Frame(pm_card, style='Card.TFrame')
        fmt_row.grid(row=2, column=0, columnspan=2, sticky='ew', padx=6, pady=2)
        fmt_row.columnconfigure(1, weight=1)
        ttk.Label(fmt_row, text='Format:', style='Card.TLabel').grid(
            row=0, column=0, sticky='w', padx=(0, 6))
        ttk.Entry(fmt_row, textvariable=self.var_autopattern).grid(
            row=0, column=1, sticky='ew')
        ttk.Button(fmt_row, text='Auto-select', width=10,
                   command=self._auto_select).grid(row=0, column=2, padx=(4, 0))

        self._scan_pm_folder()

    # -- right column ---------------------------------------------------------

    def _build_right(self, parent):
        parent.columnconfigure(0, weight=1)

        # Frequency
        freq_card = ttk.LabelFrame(parent, text='Frequency', padding=6)
        freq_card.grid(row=0, column=0, sticky='ew', pady=(0, 8))
        freq_card.columnconfigure(1, weight=1)
        ttk.Label(freq_card, text='Rate (Hz):').grid(
            row=0, column=0, sticky='w', padx=6)
        ttk.Entry(freq_card, textvariable=self.var_freq, width=10).grid(
            row=0, column=1, sticky='w', padx=6, pady=4)

        # Hardware
        hw_card = ttk.LabelFrame(parent, text='Hardware', padding=6)
        hw_card.grid(row=1, column=0, sticky='ew', pady=(0, 8))
        hw_card.columnconfigure(0, weight=1)

        slm_row, self._combo_slm, self._btn_slm, self._dot_slm = make_port_row(
            hw_card, 'Arduino SLM',
            self.var_slm_port,
            'FLASH & CONNECT',
            self._on_flash_slm,
        )
        slm_row.grid(row=0, column=0, sticky='ew', pady=2)

        nidaq_row = ttk.Frame(hw_card, style='Card.TFrame')
        nidaq_row.grid(row=1, column=0, sticky='ew', pady=2)
        ttk.Label(nidaq_row, text='NI-DAQ', width=14, anchor='w',
                  style='Card.TLabel').pack(side='left', padx=(6, 4))
        self._dot_nidaq = make_status_dot(nidaq_row)
        self._dot_nidaq.pack(side='left')
        ttk.Label(nidaq_row, text='not armed', style='Card.TLabel',
                  foreground=COLOR_DIM).pack(side='left', padx=6)

        tcp_row = ttk.Frame(hw_card, style='Card.TFrame')
        tcp_row.grid(row=2, column=0, sticky='ew', pady=2)
        ttk.Label(tcp_row, text='TCP WaveFront', width=14, anchor='w',
                  style='Card.TLabel').pack(side='left', padx=(6, 4))
        self._dot_tcp = make_status_dot(tcp_row)
        self._dot_tcp.pack(side='left')
        ttk.Label(tcp_row, text='not connected', style='Card.TLabel',
                  foreground=COLOR_DIM).pack(side='left', padx=6)

        # Progress
        prog_card = ttk.Frame(parent, padding=4)
        prog_card.grid(row=2, column=0, sticky='ew', pady=(0, 4))
        prog_card.columnconfigure(0, weight=1)
        self._progressbar = ttk.Progressbar(prog_card, mode='determinate',
                                            maximum=100, value=0)
        self._progressbar.grid(row=0, column=0, sticky='ew', pady=(0, 2))
        self._lbl_progress = ttk.Label(prog_card, text='—', foreground=COLOR_DIM)
        self._lbl_progress.grid(row=1, column=0, sticky='w')

        # RUN / STOP buttons
        btn_frame = ttk.Frame(parent)
        btn_frame.grid(row=3, column=0, sticky='ew', pady=(4, 0))
        btn_frame.columnconfigure(0, weight=3)
        btn_frame.columnconfigure(1, weight=1)

        self._btn_run = tk.Button(
            btn_frame, text='RUN PROTOCOL', command=self._on_run,
            bg='#1A4A1A', fg='#00FF00',
            activebackground='#2A6A2A', activeforeground='#00FF00',
            font=('Consolas', 12, 'bold'), relief='flat', bd=0, pady=8,
        )
        self._btn_run.grid(row=0, column=0, sticky='ew', padx=(0, 4))

        self._btn_stop = tk.Button(
            btn_frame, text='STOP', command=self._on_stop,
            bg='#2A2A2A', fg='#666666', state='disabled',
            activebackground='#6A2A2A', activeforeground='#FF4444',
            font=('Consolas', 12, 'bold'), relief='flat', bd=0, pady=8,
        )
        self._btn_stop.grid(row=0, column=1, sticky='ew')

    # -- callbacks ------------------------------------------------------------

    def _open_pm_folder(self):
        folder = self.params.get('wavefront_folder', '')
        if folder and os.path.isdir(folder):
            os.startfile(folder)

    def _scan_pm_folder(self):
        folder  = self.params.get('wavefront_folder', '')
        pattern = self.params.get('wavefront_pattern', 'Pattern{n}_000.algoPhp.png')
        n = sync.count_spots_from_folder(folder, pattern)
        if n == 0:
            self._lbl_pm_detected.configure(text='0 spots found', foreground='#FF4444')
            return
        self._lbl_pm_detected.configure(
            text=f'{n} spot{"s" if n > 1 else ""} detected', foreground='#00FF00')
        self._auto_select(n)

    def _auto_select(self, n: int = None):
        if n is None:
            folder  = self.params.get('wavefront_folder', '')
            pattern = self.params.get('wavefront_pattern', 'Pattern{n}_000.algoPhp.png')
            n = sync.count_spots_from_folder(folder, pattern)
        if not n:
            return
        substr = self.var_autopattern.get().replace('{n_spots}', str(n))
        for fname in (self._combo_vec['values'] or []):
            if substr in fname:
                self.var_vec_name.set(fname)
                break
        for fname in (self._combo_pm['values'] or []):
            if substr in fname:
                self.var_pm_name.set(fname)
                break

    def _on_folder_selected(self, folder: str):
        bin_files, vec_files, pm_files = scan_binvec_folder(folder, self.params)
        self._combo_bin['values'] = bin_files
        self._combo_vec['values'] = vec_files
        self._combo_pm['values']  = pm_files
        # Keep current selection if still valid, else pick first
        if self.var_bin_name.get() not in bin_files:
            self.var_bin_name.set(bin_files[0] if bin_files else '')
        if self.var_vec_name.get() not in vec_files:
            self.var_vec_name.set(vec_files[0] if vec_files else '')
        if self.var_pm_name.get() not in pm_files:
            self.var_pm_name.set(pm_files[0] if pm_files else '')

    def _on_flash_slm(self):
        self.console.log('[VDH] Flash & Connect Arduino SLM — not yet implemented', 'warn')

    def _on_run(self):
        folder   = self.var_binvec_folder.get()
        bin_name = self.var_bin_name.get()
        vec_name = self.var_vec_name.get()
        freq_str = self.var_freq.get()

        if not folder or not bin_name or not vec_name:
            messagebox.showerror('Missing files', 'Select a binvec folder, a BIN and a VEC file.')
            return
        try:
            freq_hz = float(freq_str)
        except ValueError:
            messagebox.showerror('Invalid frequency', f'"{freq_str}" is not a valid number.')
            return
        if not self._acquire_run():
            self.console.log('[DMD] Film.exe already running.', 'warn')
            return

        self._save_config()
        self._btn_run.configure(text='RUNNING…', bg='#3A3A3A')
        self._btn_stop.configure(state='normal', bg='#4A1A1A', fg='#FF4444')

        def _run():
            try:
                self._proc = dmd.run_vdh(
                    folder, bin_name, vec_name, freq_hz,
                    self.params,
                    lambda msg, lvl='info': self.after(0, lambda m=msg, l=lvl: self.console.log(m, l)),
                )
                self._proc.wait()
                if self._proc.returncode not in (0, -1, 1):
                    self.after(0, lambda: self.console.log(
                        f'[DMD] film.exe unexpectedly terminated (code {self._proc.returncode})', 'warn'))
            except Exception as e:
                self.after(0, lambda: self.console.log(f'[DMD] ERROR: {e}', 'error'))
            finally:
                self.after(0, self._release_run)

        threading.Thread(target=_run, daemon=True).start()

    def _on_stop(self):
        dmd.stop(getattr(self, '_proc', None))
        self.console.log('[VDH] Protocol interrupted.', 'warn')


# ── Visual tab ───────────────────────────────────────────────────────────────

class VisualTab(ttk.Frame):
    """Visual-only tab: DMD stimulation with no SLM/NI-DAQ."""

    def __init__(self, parent, console: ConsoleLog, params: dict, config: dict,
                 save_config=None, acquire_run=None, release_run=None):
        super().__init__(parent)
        self.console      = console
        self.params       = params
        self.config       = config
        self._proc                = None
        self._counter             = None
        self._poll_id             = None
        self._polling             = False
        self._stim_started        = False
        self._total_triggers      = 0
        self._freq_hz             = 0.0
        self._last_trigger_count  = 0
        self._last_trigger_time   = 0.0
        self._save_config = save_config  or (lambda: None)
        self._acquire_run = acquire_run  or (lambda: True)
        self._release_run = release_run  or (lambda: None)
        self._build()

    def _init_vars(self):
        cfg = self.config
        self.var_binvec_folder = tk.StringVar(value=cfg.get('vis_binvec_folder', ''))
        self.var_bin_name      = tk.StringVar(value=cfg.get('vis_bin_name', ''))
        self.var_vec_name      = tk.StringVar(value=cfg.get('vis_vec_name', ''))
        self.var_freq          = tk.StringVar(value=str(cfg.get('vis_freq', 20.0)))

    def _build(self):
        self._init_vars()
        self.configure(style='TFrame')
        self.columnconfigure(0, weight=1, minsize=360)
        self.columnconfigure(1, weight=1, minsize=300)
        self.rowconfigure(0, weight=1)

        left  = ttk.Frame(self, padding=8)
        right = ttk.Frame(self, padding=8)
        left.grid( row=0, column=0, sticky='nsew')
        right.grid(row=0, column=1, sticky='nsew')

        self._build_left(left)
        self._build_right(right)
        self.var_vec_name.trace_add('write', self._update_duration_preview)
        self.var_freq.trace_add('write', self._update_duration_preview)
        self._update_duration_preview()

    def _build_left(self, parent):
        parent.columnconfigure(0, weight=1)

        files_card = ttk.LabelFrame(parent, text='Files', padding=6)
        files_card.grid(row=0, column=0, sticky='ew', pady=(0, 8))
        files_card.columnconfigure(0, weight=1)

        folder_row = make_folder_picker_row(
            files_card, 'Binvec folder',
            self.var_binvec_folder,
            on_select=self._on_folder_selected,
            initialdir=self.params.get('binvecs_root', '/'))
        folder_row.grid(row=0, column=0, sticky='ew', pady=2)

        bin_row = ttk.Frame(files_card, style='Card.TFrame')
        bin_row.grid(row=1, column=0, sticky='ew', pady=2)
        bin_row.columnconfigure(1, weight=1)
        ttk.Label(bin_row, text='.bin file', width=22, anchor='w',
                  style='Card.TLabel').grid(row=0, column=0, padx=(6, 2))
        self._combo_bin = ttk.Combobox(bin_row, textvariable=self.var_bin_name,
                                       state='readonly')
        self._combo_bin.grid(row=0, column=1, sticky='ew', padx=(2, 6), pady=2)

        vec_row = ttk.Frame(files_card, style='Card.TFrame')
        vec_row.grid(row=2, column=0, sticky='ew', pady=2)
        vec_row.columnconfigure(1, weight=1)
        ttk.Label(vec_row, text='.vec file', width=22, anchor='w',
                  style='Card.TLabel').grid(row=0, column=0, padx=(6, 2))
        self._combo_vec = ttk.Combobox(vec_row, textvariable=self.var_vec_name,
                                       state='readonly')
        self._combo_vec.grid(row=0, column=1, sticky='ew', padx=(2, 6), pady=2)

        if self.var_binvec_folder.get():
            self._on_folder_selected(self.var_binvec_folder.get())

    def _build_right(self, parent):
        parent.columnconfigure(0, weight=1)

        freq_card = ttk.LabelFrame(parent, text='Frequency', padding=6)
        freq_card.grid(row=0, column=0, sticky='ew', pady=(0, 8))
        freq_card.columnconfigure(1, weight=1)
        ttk.Label(freq_card, text='Rate (Hz):').grid(
            row=0, column=0, sticky='w', padx=6)
        ttk.Entry(freq_card, textvariable=self.var_freq, width=10).grid(
            row=0, column=1, sticky='w', padx=6, pady=4)

        sci = tk.Frame(parent, bg=FO_BG, padx=10, pady=8)
        sci.grid(row=1, column=0, sticky='ew', pady=(0, 8))
        sci.columnconfigure(0, weight=1)

        self._lbl_status = tk.Label(sci, text='[ IDLE ]',
            font=('Consolas', 8, 'bold'), fg=FO_OFF, bg=FO_BG, anchor='w')
        self._lbl_status.grid(row=0, column=0, sticky='ew')

        self._lbl_countdown = tk.Label(sci, text='--:--',
            font=('Consolas', 28, 'bold'), fg=FO_OFF, bg=FO_BG, anchor='center')
        self._lbl_countdown.grid(row=1, column=0, sticky='ew', pady=(2, 4))

        self._progressbar = ttk.Progressbar(sci, mode='determinate',
                                            maximum=100, value=0)
        self._progressbar.grid(row=2, column=0, sticky='ew', pady=(0, 4))

        self._lbl_triggers = tk.Label(sci, text='',
            font=('Consolas', 8), fg=FO_OFF, bg=FO_BG, anchor='w')
        self._lbl_triggers.grid(row=3, column=0, sticky='ew')

        btn_frame = ttk.Frame(parent)
        btn_frame.grid(row=2, column=0, sticky='ew', pady=(4, 0))
        btn_frame.columnconfigure(0, weight=3)
        btn_frame.columnconfigure(1, weight=1)

        self._btn_run = tk.Button(
            btn_frame, text='RUN PROTOCOL', command=self._on_run,
            bg='#1A4A1A', fg='#00FF00',
            activebackground='#2A6A2A', activeforeground='#00FF00',
            font=('Consolas', 12, 'bold'), relief='flat', bd=0, pady=8,
        )
        self._btn_run.grid(row=0, column=0, sticky='ew', padx=(0, 4))

        self._btn_stop = tk.Button(
            btn_frame, text='STOP', command=self._on_stop,
            bg='#2A2A2A', fg='#666666', state='disabled',
            activebackground='#6A2A2A', activeforeground='#FF4444',
            font=('Consolas', 12, 'bold'), relief='flat', bd=0, pady=8,
        )
        self._btn_stop.grid(row=0, column=1, sticky='ew')

    def _on_folder_selected(self, folder: str):
        bin_files, vec_files, _ = scan_binvec_folder(folder, self.params)
        self._combo_bin['values'] = bin_files
        self._combo_vec['values'] = vec_files
        if self.var_bin_name.get() not in bin_files:
            self.var_bin_name.set(bin_files[0] if bin_files else '')
        if self.var_vec_name.get() not in vec_files:
            self.var_vec_name.set(vec_files[0] if vec_files else '')
        self._update_duration_preview()

    def _on_run(self):
        folder   = self.var_binvec_folder.get()
        bin_name = self.var_bin_name.get()
        vec_name = self.var_vec_name.get()
        try:
            freq_hz = float(self.var_freq.get())
        except ValueError:
            messagebox.showerror('Invalid frequency', 'Enter a valid number.')
            return
        if not folder or not bin_name or not vec_name:
            messagebox.showerror('Missing files', 'Select a folder, BIN and VEC file.')
            return
        if not self._acquire_run():
            self.console.log('[DMD] Film.exe already running.', 'warn')
            return

        self._save_config()
        self._btn_run.configure(text='RUNNING…', bg='#3A3A3A')
        self._btn_stop.configure(state='normal', bg='#4A1A1A', fg='#FF4444')

        # Count total triggers from vec file
        vec_path = self._vec_path(folder, vec_name)
        total = 0
        if vec_path:
            try:
                total = sync.count_vec_triggers(vec_path)
            except Exception as e:
                self.console.log(f'[Visual] Cannot read vec: {e}', 'warn')

        # Arm NI-DAQ trigger counter
        nidaq   = self.params.get('nidaq', {})
        device  = nidaq.get('device', 'Dev1')
        pfi_idx = nidaq.get('pfi_clock', 0)
        try:
            self._counter = sync.TriggerCounter(device, pfi_idx)
            self.console.log(f'[Visual] NI-DAQ trigger counter armed ({device}/PFI{pfi_idx})')
        except Exception as e:
            self._counter = None
            self.console.log(f'[Visual] NI-DAQ counter unavailable: {e}', 'warn')

        # Start progress polling
        self._total_triggers     = total
        self._freq_hz            = freq_hz
        self._stim_started       = False
        self._last_trigger_count = 0
        self._last_trigger_time  = 0.0
        self._polling            = True
        self._poll_progress()

        def _run():
            try:
                self._proc = dmd.run_vdh(
                    folder, bin_name, vec_name, freq_hz,
                    self.params,
                    lambda msg, lvl='info': self.after(0, lambda m=msg, l=lvl: self.console.log(m, l)),
                )
                self._proc.wait()
                if self._proc.returncode not in (0, -1, 1):
                    self.after(0, lambda: self.console.log(
                        f'[DMD] film.exe unexpectedly closed (code {self._proc.returncode})', 'warn'))
            except Exception as e:
                self.after(0, lambda: self.console.log(f'[DMD] ERROR: {e}', 'error'))
            finally:
                if self._counter:
                    self._counter.close()
                    self._counter = None
                self.after(0, self._release_run)

        threading.Thread(target=_run, daemon=True).start()

    def _on_stop(self):
        dmd.stop(self._proc)
        self.console.log('[Visual] Protocol interrupted.', 'warn')

    def _vec_path(self, folder: str, vec_name: str) -> str:
        sub = self.params.get('vec_subfolder', 'VEC')
        p = os.path.join(folder, sub, vec_name)
        return p if os.path.isfile(p) else ''

    def _update_duration_preview(self, *_):
        """Show total duration in the countdown panel before a run starts."""
        if not hasattr(self, '_lbl_countdown') or self._polling:
            return
        folder   = self.var_binvec_folder.get()
        vec_name = self.var_vec_name.get()
        try:
            freq_hz = float(self.var_freq.get())
            if freq_hz <= 0:
                raise ValueError
        except (ValueError, tk.TclError):
            self._lbl_countdown.configure(text='--:--', fg=FO_OFF)
            self._lbl_triggers.configure(text='')
            self._lbl_status.configure(text='[ IDLE ]', fg=FO_OFF)
            return
        if not folder or not vec_name:
            self._lbl_countdown.configure(text='--:--', fg=FO_OFF)
            self._lbl_triggers.configure(text='')
            return
        vec_path = self._vec_path(folder, vec_name)
        if not vec_path:
            self._lbl_countdown.configure(text='--:--', fg=FO_OFF)
            self._lbl_triggers.configure(text='')
            return
        try:
            total = sync.count_vec_triggers(vec_path)
        except Exception:
            self._lbl_countdown.configure(text='--:--', fg=FO_OFF)
            self._lbl_triggers.configure(text='')
            return
        total_secs = total / freq_hz
        self._lbl_status.configure(text='[ READY ]', fg=FO_DIM)
        self._lbl_countdown.configure(text=_fmt_countdown(total_secs), fg=FO_DIM)
        self._lbl_triggers.configure(
            text=f'{total} triggers  ·  {_fmt_remaining(total_secs)}', fg=FO_DIM)

    def _poll_progress(self):
        if not self._polling:
            return
        count = 0
        if self._counter:
            try:
                count = self._counter.read()
            except Exception:
                pass

        # First trigger detection
        if count > 0 and not self._stim_started:
            self._stim_started       = True
            self._last_trigger_count = count
            self._last_trigger_time  = time.time()
            self.console.log('[Visual] >> STIM STARTED', 'info')

        total     = self._total_triggers
        remaining = max(0, total - count)
        secs_left = remaining / self._freq_hz if self._freq_hz > 0 else 0
        pct       = min(100.0, count / total * 100) if total > 0 else 0

        self._progressbar['value'] = pct

        if count > 0:
            self._lbl_status.configure(text='[ ACTIVE ]', fg=FO_ON)
            self._lbl_countdown.configure(text=_fmt_countdown(secs_left), fg=FO_ON)
            self._lbl_triggers.configure(text=f'{count:>6} / {total}', fg=FO_ON)
        else:
            total_secs = total / self._freq_hz if self._freq_hz > 0 else 0
            self._lbl_status.configure(text='[ ARMED ]', fg=FO_MID)
            self._lbl_countdown.configure(text=_fmt_countdown(total_secs), fg=FO_MID)
            self._lbl_triggers.configure(
                text=f'waiting  ·  {total} triggers', fg=FO_MID)

        # ── Auto-stop logic (only once stim has started) ─────────────────────
        if self._stim_started:
            # Update last-trigger tracking
            if count > self._last_trigger_count:
                self._last_trigger_count = count
                self._last_trigger_time  = time.time()

            # Stim complete — all triggers played
            if total > 0 and count >= total:
                self._lbl_status.configure(text='[ COMPLETE ]', fg=FO_ON)
                self._lbl_countdown.configure(text='00:00', fg=FO_ON)
                self.console.log('[Visual] ■ STIM COMPLETE', 'info')
                dmd.stop(getattr(self, '_proc', None))
                return  # _run thread finally → _release_run

            # Trigger timeout — no new edge for trigger_timeout_s
            timeout = self.params.get('trigger_timeout_s', 10)
            if (time.time() - self._last_trigger_time) > timeout:
                self.console.log(
                    f'[Visual] ■ No trigger for {timeout}s — stopping', 'warn')
                dmd.stop(getattr(self, '_proc', None))
                return  # _run thread finally → _release_run

        self._poll_id = self.after(1000, self._poll_progress)

    def _reset_progress(self):
        self._polling      = False
        self._stim_started = False
        if self._poll_id:
            self.after_cancel(self._poll_id)
            self._poll_id = None
        self._progressbar['value'] = 0
        self._update_duration_preview()


# ── DH tab ───────────────────────────────────────────────────────────────────

class DhTab(ttk.Frame):
    def __init__(self, parent, console: ConsoleLog, params: dict, config: dict,
                 save_config=None, acquire_run=None, release_run=None):
        super().__init__(parent)
        self.console      = console
        self.params       = params
        self.config       = config
        self._save_config = save_config  or (lambda: None)
        self._acquire_run = acquire_run  or (lambda: True)
        self._release_run = release_run  or (lambda: None)
        self._build()

    def _init_vars(self):
        cfg = self.config
        self.var_freq       = tk.StringVar(value=str(cfg.get('dh_freq', 20.0)))
        self.var_n_spots    = tk.IntVar(   value=cfg.get('dh_n_spots', 1))
        self.var_bin_mode   = tk.StringVar(value=cfg.get('dh_bin_mode', 'dark'))
        self.var_slm_port   = tk.StringVar(value=cfg.get('dh_arduino_slm_port', ''))

    def _build(self):
        self._init_vars()
        self.configure(style='TFrame')
        self.columnconfigure(0, weight=1)

        content = ttk.Frame(self, padding=12)
        content.grid(row=0, column=0, sticky='nsew')
        content.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        row = 0

        # Frequency
        freq_card = ttk.LabelFrame(content, text='Frequency', padding=6)
        freq_card.grid(row=row, column=0, sticky='ew', pady=(0, 8))
        freq_card.columnconfigure(1, weight=1)
        ttk.Label(freq_card, text='Rate (Hz):').grid(
            row=0, column=0, sticky='w', padx=6)
        ttk.Entry(freq_card, textvariable=self.var_freq, width=10).grid(
            row=0, column=1, sticky='w', padx=6, pady=4)
        row += 1

        # Phasemask auto-detection
        pm_card = ttk.LabelFrame(content, text='Phasemask detection', padding=6)
        pm_card.grid(row=row, column=0, sticky='ew', pady=(0, 8))
        pm_card.columnconfigure(1, weight=1)

        pm_folder_row = ttk.Frame(pm_card, style='Card.TFrame')
        pm_folder_row.grid(row=0, column=0, columnspan=2, sticky='ew', padx=6, pady=2)
        pm_folder_row.columnconfigure(0, weight=1)
        self._lbl_pm_folder = ttk.Label(pm_folder_row,
            text=self.params.get('wavefront_folder', '—'),
            foreground=COLOR_DIM, wraplength=380, justify='left')
        self._lbl_pm_folder.grid(row=0, column=0, sticky='w')
        ttk.Button(pm_folder_row, text='Open', width=5,
                   command=self._open_pm_folder).grid(row=0, column=1, padx=(4, 0))

        det_row = ttk.Frame(pm_card, style='Card.TFrame')
        det_row.grid(row=1, column=0, columnspan=2, sticky='ew', padx=6, pady=(0, 4))
        self._lbl_pm_detected = ttk.Label(det_row, text='—', foreground=COLOR_DIM)
        self._lbl_pm_detected.pack(side='left')
        ttk.Button(det_row, text='Scan', width=5,
                   command=self._scan_pm_folder).pack(side='right')
        row += 1

        # Spots + auto-resolve preview
        spots_card = ttk.LabelFrame(content, text='Holography', padding=6)
        spots_card.grid(row=row, column=0, sticky='ew', pady=(0, 8))
        spots_card.columnconfigure(1, weight=1)

        ttk.Label(spots_card, text='Number of spots:').grid(
            row=0, column=0, sticky='w', padx=6)
        self._spinbox_spots = ttk.Spinbox(
            spots_card,
            textvariable=self.var_n_spots,
            from_=1, to=500, increment=1, width=6,
            command=self._on_spots_changed,
        )
        self._spinbox_spots.grid(row=0, column=1, sticky='w', padx=6, pady=4)

        ttk.Label(spots_card, text='VEC file:').grid(
            row=1, column=0, sticky='w', padx=6)
        self._lbl_vec = ttk.Label(spots_card, text='—', foreground=COLOR_DIM,
                                  wraplength=400, justify='left')
        self._lbl_vec.grid(row=1, column=1, sticky='w', padx=6, pady=2)

        ttk.Label(spots_card, text='Phase mask:').grid(
            row=2, column=0, sticky='w', padx=6)
        self._lbl_pm = ttk.Label(spots_card, text='—', foreground=COLOR_DIM,
                                 wraplength=400, justify='left')
        self._lbl_pm.grid(row=2, column=1, sticky='w', padx=6, pady=2)
        row += 1

        # BIN selection
        bin_card = ttk.LabelFrame(content, text='BIN file', padding=6)
        bin_card.grid(row=row, column=0, sticky='ew', pady=(0, 8))

        ttk.Radiobutton(bin_card, text='Bright',
                        variable=self.var_bin_mode, value='bright',
                        command=self._on_bin_mode_changed).pack(
            side='left', padx=(6, 12))
        ttk.Radiobutton(bin_card, text='Dark',
                        variable=self.var_bin_mode, value='dark',
                        command=self._on_bin_mode_changed).pack(
            side='left', padx=(0, 12))
        self._lbl_bin = ttk.Label(bin_card, text='—', foreground=COLOR_DIM)
        self._lbl_bin.pack(side='left', padx=6)
        row += 1

        # Hardware
        hw_card = ttk.LabelFrame(content, text='Hardware', padding=6)
        hw_card.grid(row=row, column=0, sticky='ew', pady=(0, 8))
        hw_card.columnconfigure(0, weight=1)

        slm_row, self._combo_slm, self._btn_slm, self._dot_slm = make_port_row(
            hw_card, 'Arduino SLM',
            self.var_slm_port,
            'FLASH & CONNECT',
            self._on_flash_slm,
        )
        slm_row.grid(row=0, column=0, sticky='ew', pady=2)

        nidaq_row = ttk.Frame(hw_card, style='Card.TFrame')
        nidaq_row.grid(row=1, column=0, sticky='ew', pady=2)
        ttk.Label(nidaq_row, text='NI-DAQ', width=14, anchor='w',
                  style='Card.TLabel').pack(side='left', padx=(6, 4))
        self._dot_nidaq = make_status_dot(nidaq_row)
        self._dot_nidaq.pack(side='left')

        tcp_row = ttk.Frame(hw_card, style='Card.TFrame')
        tcp_row.grid(row=2, column=0, sticky='ew', pady=2)
        ttk.Label(tcp_row, text='TCP WaveFront', width=14, anchor='w',
                  style='Card.TLabel').pack(side='left', padx=(6, 4))
        self._dot_tcp = make_status_dot(tcp_row)
        self._dot_tcp.pack(side='left')
        row += 1

        # Progress
        self._progressbar = ttk.Progressbar(content, mode='determinate',
                                            maximum=100, value=0)
        self._progressbar.grid(row=row, column=0, sticky='ew', pady=(0, 4))
        row += 1

        self._lbl_progress = ttk.Label(content, text='—', foreground=COLOR_DIM)
        self._lbl_progress.grid(row=row, column=0, sticky='w')
        row += 1

        # RUN / STOP buttons
        btn_frame = ttk.Frame(content)
        btn_frame.grid(row=row, column=0, sticky='ew', pady=(4, 0))
        btn_frame.columnconfigure(0, weight=3)
        btn_frame.columnconfigure(1, weight=1)

        self._btn_run = tk.Button(
            btn_frame, text='RUN PROTOCOL', command=self._on_run,
            bg='#1A4A1A', fg='#00FF00',
            activebackground='#2A6A2A', activeforeground='#00FF00',
            font=('Consolas', 12, 'bold'), relief='flat', bd=0, pady=8,
        )
        self._btn_run.grid(row=0, column=0, sticky='ew', padx=(0, 4))

        self._btn_stop = tk.Button(
            btn_frame, text='STOP', command=self._on_stop,
            bg='#2A2A2A', fg='#666666', state='disabled',
            activebackground='#6A2A2A', activeforeground='#FF4444',
            font=('Consolas', 12, 'bold'), relief='flat', bd=0, pady=8,
        )
        self._btn_stop.grid(row=0, column=1, sticky='ew')

        self._on_spots_changed()
        self._on_bin_mode_changed()
        self._scan_pm_folder()

    # -- callbacks ------------------------------------------------------------

    def _open_pm_folder(self):
        folder = self.params.get('wavefront_folder', '')
        if folder and os.path.isdir(folder):
            os.startfile(folder)

    def _scan_pm_folder(self):
        folder  = self.params.get('wavefront_folder', '')
        pattern = self.params.get('wavefront_pattern', 'Pattern{n}_000.algoPhp.png')
        n = sync.count_spots_from_folder(folder, pattern)
        if n == 0:
            self._lbl_pm_detected.configure(text='0 spots found', foreground='#FF4444')
        else:
            self._lbl_pm_detected.configure(
                text=f'{n} spot{"s" if n > 1 else ""} detected',
                foreground='#00FF00')
            self.var_n_spots.set(n)
            self._on_spots_changed()

    def _on_spots_changed(self):
        n            = self.var_n_spots.get()
        stim_folder  = self.params.get('dh_stim_folder', '')
        vec_sub      = self.params.get('vec_subfolder', 'VEC')
        vec_pattern  = self.params.get('dh_vec_pattern', '')
        pm_sub       = self.params.get('phasemasks_subfolder', 'Phasemasks')
        pm_pattern   = self.params.get('dh_phasemask_pattern', '')
        self._lbl_vec.configure(text=os.path.join(stim_folder, vec_sub, vec_pattern.replace('{n_spots}', str(n))))
        self._lbl_pm.configure( text=os.path.join(stim_folder, pm_sub, pm_pattern.replace('{n_spots}', str(n))))

    def _on_bin_mode_changed(self):
        mode        = self.var_bin_mode.get()
        stim_folder = self.params.get('dh_stim_folder', '')
        bin_sub     = self.params.get('bin_subfolder', 'BIN')
        self._lbl_bin.configure(text=f'{os.path.join(stim_folder, bin_sub)}  [{mode}]')

    def _on_flash_slm(self):
        self.console.log('[DH] Flash & Connect Arduino SLM — not yet implemented', 'warn')

    def _on_run(self):
        try:
            freq_hz = float(self.var_freq.get())
        except ValueError:
            messagebox.showerror('Invalid frequency', 'Enter a valid number.')
            return

        n_spots  = self.var_n_spots.get()
        bin_mode = self.var_bin_mode.get()

        if not self._acquire_run():
            self.console.log('[DMD] Film.exe already running.', 'warn')
            return

        self._save_config()
        self._btn_run.configure(text='RUNNING…', bg='#3A3A3A')
        self._btn_stop.configure(state='normal', bg='#4A1A1A', fg='#FF4444')

        def _run():
            try:
                self._proc = dmd.run_dh(
                    n_spots, bin_mode, freq_hz,
                    self.params,
                    lambda msg, lvl='info': self.after(0, lambda m=msg, l=lvl: self.console.log(m, l)),
                )
                self._proc.wait()
                if self._proc.returncode not in (0, -1, 1):
                    self.after(0, lambda: self.console.log(
                        f'[DMD] film.exe unexpectedly closed (code {self._proc.returncode})', 'warn'))
            except Exception as e:
                self.after(0, lambda: self.console.log(f'[DH] ERROR: {e}', 'error'))
            finally:
                self.after(0, self._release_run)

        threading.Thread(target=_run, daemon=True).start()

    def _on_stop(self):
        dmd.stop(getattr(self, '_proc', None))
        self.console.log('[DH] Protocol interrupted.', 'warn')


# ── main application window ──────────────────────────────────────────────────

class PlerionApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Plerion')
        self.configure(bg=COLOR_BG)
        self.minsize(800, 600)

        self.params   = load_json(PARAMS_FILE, {})
        self.config   = load_json(CONFIG_FILE, {})
        self._running = False

        apply_dark_style(self)
        self._build()
        self.protocol('WM_DELETE_WINDOW', self._on_close)

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=0)

        nb = ttk.Notebook(self)
        nb.grid(row=0, column=0, sticky='nsew', padx=8, pady=(8, 0))

        console_frame = ttk.LabelFrame(self, text='Console', padding=4)
        console_frame.grid(row=1, column=0, sticky='ew', padx=8, pady=(4, 8))
        console_frame.columnconfigure(0, weight=1)

        self.console = ConsoleLog(console_frame, height=8)
        scroll = ttk.Scrollbar(console_frame, orient='vertical',
                               command=self.console.yview)
        self.console.configure(yscrollcommand=scroll.set)
        self.console.grid(row=0, column=0, sticky='ew')
        scroll.grid(row=0, column=1, sticky='ns')

        self.vis_tab = VisualTab(nb, self.console, self.params, self.config,
                                 save_config=self._save_config,
                                 acquire_run=self._acquire_run,
                                 release_run=self._release_run)
        self.dh_tab  = DhTab(   nb, self.console, self.params, self.config,
                                 save_config=self._save_config,
                                 acquire_run=self._acquire_run,
                                 release_run=self._release_run)
        self.vdh_tab = VdhTab(  nb, self.console, self.params, self.config,
                                 save_config=self._save_config,
                                 acquire_run=self._acquire_run,
                                 release_run=self._release_run)
        nb.add(self.vis_tab, text='  Visual  ')
        nb.add(self.dh_tab,  text='  DH      ')
        nb.add(self.vdh_tab, text='  VDH     ')

        self.console.log('Plerion ready.', 'info')

    def _acquire_run(self) -> bool:
        if self._running:
            return False
        self._running = True
        return True

    def _release_run(self):
        self._running = False
        self.vis_tab._reset_progress()
        for tab in (self.vis_tab, self.dh_tab, self.vdh_tab):
            tab._btn_run.configure(state='normal', text='RUN PROTOCOL', bg='#1A4A1A')
            tab._btn_stop.configure(state='disabled', bg='#2A2A2A', fg='#666666')

    def _save_config(self):
        save_json(CONFIG_FILE, self._collect_config())

    def _on_close(self):
        self._save_config()
        for tab in (self.vis_tab, self.dh_tab, self.vdh_tab):
            dmd.stop(getattr(tab, '_proc', None))
        self.destroy()

    def _collect_config(self) -> dict:
        vi = self.vis_tab
        d  = self.dh_tab
        v  = self.vdh_tab
        return {
            'vis_binvec_folder':    vi.var_binvec_folder.get(),
            'vis_bin_name':         vi.var_bin_name.get(),
            'vis_vec_name':         vi.var_vec_name.get(),
            'vis_freq':             float(vi.var_freq.get() or 20),
            'dh_freq':              float(d.var_freq.get() or 20),
            'dh_n_spots':           d.var_n_spots.get(),
            'dh_bin_mode':          d.var_bin_mode.get(),
            'dh_arduino_slm_port':  d.var_slm_port.get(),
            'vdh_binvec_folder':    v.var_binvec_folder.get(),
            'vdh_bin_name':         v.var_bin_name.get(),
            'vdh_vec_name':         v.var_vec_name.get(),
            'vdh_pm_name':          v.var_pm_name.get(),
            'vdh_freq':             float(v.var_freq.get() or 20),
            'vdh_arduino_slm_port': v.var_slm_port.get(),
            'vdh_autopattern':      v.var_autopattern.get(),
        }


# ── entry point ──────────────────────────────────────────────────────────────

if __name__ == '__main__':
    app = PlerionApp()
    app.mainloop()
