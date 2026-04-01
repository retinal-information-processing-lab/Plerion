# Branch 1 — DMD control
# Resolves the folder/bin/vec indices inside the binvecs tree, then launches
# film.exe with those indices piped to stdin.  No symlinks needed.

import ctypes
import os
import subprocess
import threading


def _readdir_index(folder: str, name: str) -> int:
    """Return the readdir index of *name* inside *folder*.
    Uses os.listdir() without sorting to match film.exe's readdir traversal order.
    Skips '.' and '..' as film.cpp does."""
    entries = [e for e in os.listdir(folder) if e not in ('.', '..')]
    return entries.index(name)


def resolve_indices(binvecs_root: str, folder_name: str,
                    bin_name: str, vec_name: str, params: dict = None) -> tuple:
    """Return (user_idx, bin_idx, vec_idx) matching film.exe's readdir order."""
    p        = params or {}
    bin_sub  = p.get('bin_subfolder', 'BIN')
    vec_sub  = p.get('vec_subfolder', 'VEC')
    user_idx = _readdir_index(binvecs_root, folder_name)
    folder   = os.path.join(binvecs_root, folder_name)
    bin_idx  = _readdir_index(os.path.join(folder, bin_sub), bin_name)
    vec_idx  = _readdir_index(os.path.join(folder, vec_sub), vec_name)
    return user_idx, bin_idx, vec_idx


def launch_film(freq_hz: float, user_idx: int, bin_idx: int, vec_idx: int,
                params: dict, log_callback) -> subprocess.Popen:
    """
    Launch film.exe with stdin piped.
    Answers in order: user_idx, bin_idx, vec_idx, freq, 'n' (no advanced).

    IMPORTANT — termination rules:
      film.cpp checks _kbhit() in its main loop — any console input during
      projection triggers an early break.  Call stop() only after trigger
      cessation has been confirmed by the SLM/NI-DAQ layer.
    """
    freq_str   = str(int(freq_hz)) if freq_hz == int(freq_hz) else f'{freq_hz:.4f}'
    stdin_data = f'{user_idx}\n{bin_idx}\n{vec_idx}\n{freq_str}\nn\n'

    exe = params['film_exe']
    proc = subprocess.Popen(
        [exe],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=os.path.dirname(exe),
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
    )

    # Read stdout in background — only surface error lines to the GUI log
    def _watch_stdout():
        for line in proc.stdout:
            stripped = line.rstrip()
            if stripped and ('error' in stripped.lower() or 'press any key' in stripped.lower()):
                log_callback(f'[film.exe] {stripped}', 'error')
                proc.terminate()
        proc.stdout.close()

    threading.Thread(target=_watch_stdout, daemon=True).start()

    # Write all prompts at once then close — no further writes during projection
    proc.stdin.write(stdin_data)
    proc.stdin.flush()
    proc.stdin.close()

    return proc


def run_vdh(folder_path: str, bin_name: str, vec_name: str, freq_hz: float,
            params: dict, log_callback) -> subprocess.Popen:
    """VDH: resolve indices from the selected binvec folder and launch film.exe."""
    binvecs_root = params['binvecs_root']
    folder_name  = os.path.basename(folder_path.rstrip('/\\'))
    user_idx, bin_idx, vec_idx = resolve_indices(
        binvecs_root, folder_name, bin_name, vec_name, params)
    log_callback(f'[DMD] {folder_name} | {bin_name} (idx {bin_idx}) '
                 f'| {vec_name} (idx {vec_idx}) | {freq_hz} Hz')
    proc = launch_film(freq_hz, user_idx, bin_idx, vec_idx, params, log_callback)
    log_callback(f'[DMD] film.exe launched (PID {proc.pid})')
    return proc


def run_dh(n_spots: int, bin_mode: str, freq_hz: float,
           params: dict, log_callback) -> subprocess.Popen:
    """DH: auto-resolve files from params patterns and launch film.exe."""
    binvecs_root   = params['binvecs_root']
    dh_stim_folder = params['dh_stim_folder']
    dh_folder_name = os.path.basename(dh_stim_folder.rstrip('/\\'))

    bin_sub    = params.get('bin_subfolder', 'BIN')
    vec_name   = params['dh_vec_pattern'].replace('{n_spots}', f'{n_spots:03d}')
    bin_folder = os.path.join(dh_stim_folder, bin_sub)
    bin_files  = [f for f in os.listdir(bin_folder) if f not in ('.', '..')]
    bin_name   = next((f for f in bin_files if bin_mode.lower() in f.lower()), bin_files[0])
    user_idx, bin_idx, vec_idx = resolve_indices(
        binvecs_root, dh_folder_name, bin_name, vec_name, params)
    log_callback(f'[DMD] DH {n_spots} spots | {bin_name} | {vec_name} | {freq_hz} Hz')
    proc = launch_film(freq_hz, user_idx, bin_idx, vec_idx, params, log_callback)
    log_callback(f'[DMD] film.exe launched (PID {proc.pid})')
    return proc


def _alp_halt(film_exe: str) -> bool:
    """Load alpD41.dll from the same directory as film.exe, allocate the ALP
    device, halt it and free it.  Returns True on success.

    This is needed because TerminateProcess kills film.exe before it can call
    AlpDevHalt/AlpDevFree itself, leaving the DMD in its last ON state.
    """
    try:
        dll_path = os.path.join(os.path.dirname(film_exe), 'alpD41.dll')
        alp = ctypes.WinDLL(dll_path)

        alp.AlpDevAlloc.restype  = ctypes.c_long
        alp.AlpDevAlloc.argtypes = [ctypes.c_long, ctypes.c_long,
                                     ctypes.POINTER(ctypes.c_ulong)]
        alp.AlpDevHalt.restype   = ctypes.c_long
        alp.AlpDevHalt.argtypes  = [ctypes.c_ulong]
        alp.AlpDevFree.restype   = ctypes.c_long
        alp.AlpDevFree.argtypes  = [ctypes.c_ulong]

        dev_id = ctypes.c_ulong(0)
        if alp.AlpDevAlloc(0, 0, ctypes.byref(dev_id)) != 0:   # != ALP_OK
            return False
        alp.AlpDevHalt(dev_id)
        alp.AlpDevFree(dev_id)
        return True
    except Exception:
        return False


def stop(proc: subprocess.Popen, film_exe: str = '') -> None:
    """Terminate film.exe and ensure the DMD is switched off.

    film.exe only calls AlpDevHalt/AlpDevFree after an interactive _getch(),
    which never fires when launched without a console.  So after killing the
    process we re-open the ALP device ourselves and halt it.
    """
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()

    # Re-open ALP device and halt it so the DMD turns off.
    if film_exe:
        _alp_halt(film_exe)
