import os


class SLMClient:
    """File-drop client for WaveFront IV phasemask switching.

    WaveFront IV watches script_dir for JS files. Writing test.js + zdone.js
    causes WaveFront to execute the script, load the profile, then delete both files.
    """

    def __init__(self, script_dir: str):
        self._script_dir = script_dir

    @property
    def is_connected(self) -> bool:
        return bool(self._script_dir) and os.path.isdir(self._script_dir)

    def send_mask(self, path: str) -> bool:
        """Write loadProfile JS + sentinel to script folder. Returns True on success."""
        if not self.is_connected:
            return False
        try:
            js_path   = os.path.join(self._script_dir, 'test.js')
            done_path = os.path.join(self._script_dir, 'zdone.js')
            escaped   = path.replace('\\', '\\\\')
            js_content = (
                'cleanAllBlob();\n'
                'deleteProfile(0);\n'
                f'loadProfile("{escaped}", 2);\n'
            )
            with open(js_path, 'w') as f:
                f.write(js_content)
            with open(done_path, 'w'):
                pass
            return True
        except OSError:
            return False
