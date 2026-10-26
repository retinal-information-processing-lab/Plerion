"""The JavaScript Plerion has Wavefront IV run: a protocol prepared, a phase mask shown at an SLM trigger, the tick of
its Tcp server. Its script commands are the <scriptEngine> entries of invoke.xml in wfdIV.cfg, and the helpers of its
script engine's own wfdIV.js (a resource of plugins/toolBox/scriptEnginePlug.dll): loadProfile(file, srcMode) there
calls loadSingleProfile(file, srcMode) of its profile controller.

Wavefront's pattern (profile) list, as tried on the rig (by Oriole TCP): a computed or loaded pattern takes the lowest
free ID (the number shown in the list), and deleteProfile(n) deletes the pattern of ID n (not the n-th one; an ID not
there does nothing). There is no script command to empty the list: every ID is deleted.

Vendored from Oriole TCP (oriole/wavefront/wf4/scripts.py): LIST_IDS, EMPTY_LIST and TICK_JS unchanged; the protocol
scripts are Plerion's.
"""
from __future__ import annotations

LIST_IDS = 500                       # pattern IDs 0..LIST_IDS deleted to empty Wavefront's list (0.7 ms each)
EMPTY_LIST = f"for (var id = 0; id <= {LIST_IDS}; id++) {{ deleteProfile(id); }}"
# Ticks Tcp server in Wavefront's Script engine dialog, as a click would (the three sources are exclusive): a script
# run from the script folder while Wavefront is in auto-load mode, as it starts with [scriptEngine] autoload=true
TICK_JS = ('var k = scriptEngine.getUi().findChildren(); for (var i = 0; i < k.length; i++) '
           '{ if (k[i].objectName == "tcpServerQckx" && !k[i].checked) { k[i].click(); } }')
LOAD_MODE = 2                        # loadProfile's srcMode, as DHgui's RunStim, Plerion's script folder and Oriole
                                     # TCP's Load send it (arduinoReader sent 3)


def prepare_script() -> str:
    """Before a protocol: Wavefront's pattern list emptied, once (about 0.35 s, too long for every trigger), so that
    the pattern of every mask loaded then is ID 0, the one load_script deletes before loading the next."""
    return f"{EMPTY_LIST}\ncleanAllBlob();\n"


def load_script(png_path) -> str:
    """Show a saved phase mask on the SLM, at an SLM trigger (DHgui's RunStim, Plerion's script folder): the pattern
    of ID 0 (the mask shown before) deleted, then the mask loaded, taking ID 0."""
    escaped = str(png_path).replace("\\", "\\\\")
    return f'cleanAllBlob();\ndeleteProfile(0);\nloadProfile("{escaped}", {LOAD_MODE});\n'
