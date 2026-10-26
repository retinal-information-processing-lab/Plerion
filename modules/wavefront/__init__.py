"""The Wavefront programs Plerion drives over TCP, one package per version, side by side: wf4 (Wavefront IV) and wf5
(Wavefront V, not ready yet). Each implements base.Wavefront; tcp holds what every version's link shares, winproc and
qtini what their programs may share (processes and windows of this PC, QSettings files).

Vendored from Oriole TCP (E:\\Oriole-tcp, branch tcp, b6c5d60, oriole/wavefront), with the same layout, so that a fix
found in one is ported to the other. Plerion's changes: its scripts answer PLERION (wf4.link), other clients' answers
kept (tcp: foreign), the protocol scripts (base: prepare_script, load_script), and what only Oriole needs left out
(phase mask generation; starting, closing and switching Wavefront; its help pages).
"""
from __future__ import annotations

from .base import Process, Wavefront
from .tcp import Answer, LinkError
from .wf4 import WavefrontIV
from .wf5 import WavefrontV

VERSIONS: dict[str, type[Wavefront]] = {cls.KEY: cls for cls in (WavefrontIV, WavefrontV)}
DEFAULT = WavefrontIV.KEY


def version(key: str) -> type[Wavefront]:
    """The Wavefront of ``key`` ("IV", "V"); the default one for a key unknown or not ready yet."""
    cls = VERSIONS.get(key)
    return cls if cls is not None and cls.READY else VERSIONS[DEFAULT]


__all__ = ["Answer", "DEFAULT", "LinkError", "Process", "VERSIONS", "Wavefront", "WavefrontIV", "WavefrontV", "version"]
