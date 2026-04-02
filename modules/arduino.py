# Arduino flashing helper for Plerion.
# Uses arduino-cli to compile and upload the sendPeriodOnTrig sketch.

import os
import subprocess

ARDUINO_CLI = r'C:\Program Files\ArduinoCLI\arduino-cli.exe'
SKETCH_DIR  = os.path.normpath(os.path.join(os.path.dirname(__file__),
                                             '..', 'sendPeriodOnTrig'))
FQBN        = 'arduino:avr:uno'   # Arduino Uno — change if different board


def list_ports() -> list[str]:
    """Return list of available COM port names."""
    try:
        result = subprocess.run(
            [ARDUINO_CLI, 'board', 'list', '--format', 'text'],
            capture_output=True, text=True, timeout=10)
        ports = []
        for line in result.stdout.splitlines()[1:]:  # skip header
            parts = line.split()
            if parts:
                ports.append(parts[0])
        return [p for p in ports if p.startswith('COM') or p.startswith('/dev/')]
    except Exception:
        return []


def flash(port: str) -> tuple[bool, str]:
    """Compile and upload the sendPeriodOnTrig sketch to *port*.

    Returns (success: bool, log: str).
    """
    log_lines = []

    # Compile
    try:
        r = subprocess.run(
            [ARDUINO_CLI, 'compile', '--fqbn', FQBN, SKETCH_DIR],
            capture_output=True, text=True, timeout=60)
        log_lines.append(r.stdout.strip())
        if r.stderr.strip():
            log_lines.append(r.stderr.strip())
        if r.returncode != 0:
            return False, '\n'.join(filter(None, log_lines))
    except Exception as e:
        return False, f'Compile error: {e}'

    # Upload
    try:
        r = subprocess.run(
            [ARDUINO_CLI, 'upload', '--fqbn', FQBN, '--port', port, SKETCH_DIR],
            capture_output=True, text=True, timeout=60)
        log_lines.append(r.stdout.strip())
        if r.stderr.strip():
            log_lines.append(r.stderr.strip())
        if r.returncode != 0:
            return False, '\n'.join(filter(None, log_lines))
    except Exception as e:
        return False, f'Upload error: {e}'

    return True, '\n'.join(filter(None, log_lines))


def probe(port: str, baud: int = 128000) -> bool:
    """Try opening the serial port to confirm the Arduino is present."""
    try:
        import serial
        s = serial.Serial(port, baud, timeout=1)
        s.close()
        return True
    except Exception:
        return False
