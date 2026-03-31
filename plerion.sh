#!/usr/bin/env bash
# Launch Plerion in its conda environment.
# Run from Git Bash:  bash plerion.sh   or   ./plerion.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_NAME="plerion"

# Locate conda
if command -v conda &>/dev/null; then
    CONDA_BASE="$(conda info --base)"
else
    # Common Windows install paths
    for candidate in \
        "$USERPROFILE/miniconda3" \
        "$USERPROFILE/anaconda3" \
        "C:/ProgramData/miniconda3" \
        "C:/ProgramData/anaconda3"
    do
        if [ -f "$candidate/Scripts/conda.exe" ]; then
            CONDA_BASE="$candidate"
            break
        fi
    done
fi

if [ -z "$CONDA_BASE" ]; then
    echo "ERROR: conda not found. Install Miniconda or Anaconda and retry." >&2
    exit 1
fi

# Source conda init so 'conda activate' works in this shell
source "$CONDA_BASE/etc/profile.d/conda.sh"

conda activate "$ENV_NAME"

echo "Python: $(which python)  ($(python --version))"
echo "Working dir: $SCRIPT_DIR"
cd "$SCRIPT_DIR"
exec python plerion_gui.py "$@"
