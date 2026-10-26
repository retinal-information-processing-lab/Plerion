"""Programs on this PC (Windows): which run and from which folder, whether they show their window; starting one.

Through the Win32 API (ctypes). Elsewhere nothing is found running (SUPPORTED False): Wavefront is started by hand.

Vendored from Oriole TCP (oriole/wavefront/winproc.py), unchanged.
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

SUPPORTED = sys.platform == "win32"


@dataclass(frozen=True)
class Process:
    pid: int
    folder: Path | None             # the folder of its executable (None: not readable)


def running(names) -> dict[str, Process]:
    """The running processes of the executables ``names`` (as "wfdIVCore.dll"), by lower-case name."""
    if not SUPPORTED:
        return {}
    import ctypes
    from ctypes import wintypes as wt

    class Entry(ctypes.Structure):
        _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
                    ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD),
                    ("szExeFile", wt.WCHAR * 260)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
    k32.OpenProcess.restype = wt.HANDLE
    wanted = {name.lower() for name in names}
    found = {}
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)                 # TH32CS_SNAPPROCESS
    try:
        entry = Entry(dwSize=ctypes.sizeof(Entry))
        ok = k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            name = entry.szExeFile.lower()
            if name in wanted:
                found[name] = Process(entry.th32ProcessID, _process_folder(k32, entry.th32ProcessID))
            ok = k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)
    return found


def _process_folder(k32, pid: int) -> Path | None:
    import ctypes
    from ctypes import wintypes as wt
    handle = k32.OpenProcess(0x1000, False, pid)                # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        buf, size = ctypes.create_unicode_buffer(1024), wt.DWORD(1024)
        return Path(buf.value).parent if k32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)) else None
    finally:
        k32.CloseHandle(handle)


def _windows(pid: int) -> list[tuple[int, str]]:
    """The visible windows of the process ``pid``: (handle, title)."""
    if not SUPPORTED:
        return []
    import ctypes
    from ctypes import wintypes as wt
    user32 = ctypes.WinDLL("user32")
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def visit(hwnd, _):
        owner = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            text = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, text, 256)
            found.append((hwnd, text.value))
        return True

    user32.EnumWindows(visit, 0)
    return found


def _user32():
    """user32, with the signatures used here (64-bit window handles and message parameters)."""
    import ctypes
    from ctypes import wintypes as wt
    user32 = ctypes.WinDLL("user32")
    user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    user32.SetForegroundWindow.argtypes = [wt.HWND]
    user32.GetForegroundWindow.restype = wt.HWND
    return user32


def _window(pid: int, title: str) -> int | None:
    return next((hwnd for hwnd, text in _windows(pid) if text.startswith(title)), None)


def window_titles(pid: int) -> list[str]:
    """The titles of the visible windows of the process ``pid``."""
    return [text for _, text in _windows(pid)]


def window_open(pid: int, title: str) -> bool:
    """The process ``pid`` shows a window whose title starts with ``title``."""
    return _window(pid, title) is not None


def close_window(pid: int, title: str) -> bool:
    """Ask that window of ``pid`` to close, as its close box does (WM_CLOSE): False when it shows no such window."""
    hwnd = _window(pid, title)
    if hwnd is None:
        return False
    _user32().PostMessageW(hwnd, 0x0010, 0, 0)                          # WM_CLOSE
    return True


def confirm(pid: int, title: str, front: bool = False) -> bool:
    """Press Enter in that window of ``pid`` (a dialog: its default button), sent to that window only; ``front``:
    brought to the front and typed instead (for a program that ignores keys sent to it), never into another window.
    False when it shows no such window, or it could not be brought to the front."""
    hwnd = _window(pid, title)
    if hwnd is None:
        return False
    user32 = _user32()
    if not front:
        for message in (0x0100, 0x0101):                                # WM_KEYDOWN, WM_KEYUP: VK_RETURN
            user32.PostMessageW(hwnd, message, 0x0D, 0 if message == 0x0100 else 0xC0000001)
        return True
    user32.keybd_event(0x12, 0, 0, 0)                                   # Alt pressed: lets this process take the front
    user32.keybd_event(0x12, 0, 2, 0)
    user32.SetForegroundWindow(hwnd)
    if user32.GetForegroundWindow() != hwnd:
        return False
    user32.keybd_event(0x0D, 0, 0, 0)
    user32.keybd_event(0x0D, 0, 2, 0)
    return True


def launch(exe):
    """Start ``exe`` from its folder, detached: it outlives Oriole."""
    exe = Path(exe)
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP if SUPPORTED else 0
    subprocess.Popen([str(exe)], cwd=exe.parent, creationflags=flags, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
