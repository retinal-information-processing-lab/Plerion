"""Settings files as Qt's QSettings writes them in ini format (latin-1, backslashes doubled): a key read, keys set,
every other line left as it is.

Vendored from Oriole TCP (oriole/wavefront/qtini.py), unchanged.
"""
from __future__ import annotations

from pathlib import Path


def _to_ini(value: str) -> str:
    """A string as QSettings writes it (backslashes doubled; quoted when it holds , ; or =)."""
    text = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"' if any(c in value for c in ",;=") or value != value.strip() else text


def _from_ini(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] == '"':
        text = text[1:-1]
    return text.replace('\\"', '"').replace("\\\\", "\\")


def read(path, section: str, key: str) -> str | None:
    try:
        lines = Path(path).read_bytes().decode("latin-1").splitlines()
    except OSError:
        return None
    current = None
    for line in lines:
        if line.startswith("["):
            current = line.strip()[1:-1]
        elif current == section and line.split("=", 1)[0] == key:
            return _from_ini(line.split("=", 1)[1])
    return None


def write(path, values: dict[tuple[str, str], str]) -> list[str]:
    """Set ``{(section, key): value}`` in the file (made if missing), every other line left as it is; the
    ``section/key`` changed."""
    path = Path(path)
    try:
        text = path.read_bytes().decode("latin-1")
    except FileNotFoundError:
        text = ""
    nl = "\n" if text and "\r\n" not in text else "\r\n"
    lines = text.split(nl) if text else []
    changed = []
    for (section, key), value in values.items():
        line = f"{key}={_to_ini(value)}"
        start = next((i for i, l in enumerate(lines) if l.strip() == f"[{section}]"), None)
        if start is None:                                       # a new section at the end
            while lines and lines[-1] == "":
                lines.pop()
            lines += ([""] if lines else []) + [f"[{section}]", line, ""]
            changed.append(f"{section}/{key}")
            continue
        end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("[")), len(lines))
        k = next((i for i in range(start + 1, end) if lines[i].split("=", 1)[0] == key), None)
        if k is None:
            last = max((i for i in range(start + 1, end) if lines[i].strip()), default=start)
            lines.insert(last + 1, line)
        elif lines[k] == line:
            continue
        else:
            lines[k] = line
        changed.append(f"{section}/{key}")
    if changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(nl.join(lines).encode("latin-1"))
    return changed
