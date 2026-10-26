"""The SLM triggers of a vec, and the time each leaves Wavefront before the shutter opens."""
import math
from pathlib import Path

import pytest

from modules import sync

DH_VEC = Path(r"E:\VisualStim_DMD\data\binvecs\00_DigitalHolography\VEC\DigitalHolography_20Hz_009HoloSpots_20rep.vec")


def test_rising_edges():
    assert sync.rising_edges([1, 0, 0, 1, 1, 0, 1]) == [0, 3, 6]
    assert sync.rising_edges([0, 0]) == [] and sync.rising_edges([]) == []


def test_slm_budgets():
    # as the DH vecs at 20 Hz: SLM triggers on frames 0, 115, 135, 155; the shutter opens on 105, 125, 145 (10 frames)
    n = 160
    slm_col = [1 if i in (0, 115, 135, 155) else 0 for i in range(n)]
    shutter_col = [1 if any(s <= i < s + 10 for s in (105, 125, 145)) else 0 for i in range(n)]
    assert sync.slm_budgets(slm_col, shutter_col, 20.0) == [5.25, 0.5, 0.5, math.inf]
    assert sync.slm_budgets([1, 0], [1, 0], 20.0) == [0.0]          # the shutter opening on the trigger's frame


@pytest.mark.skipif(not DH_VEC.is_file(), reason="the lab's DH vec is not on this PC")
def test_dh_vec():
    """9 spots, 20 repetitions: 180 shutter openings, 181 SLM triggers (the first on frame 0, 5.25 s before the first
    opening; then each as the shutter closes, 0.5 s before the next; the last after the last opening)."""
    slm_col, shutter_col = sync.read_vec_columns(str(DH_VEC))
    edges = sync.rising_edges(slm_col)
    budgets = sync.slm_budgets(slm_col, shutter_col, 20.0)
    assert len(slm_col) == 3700 and len(edges) == 181 and edges[0] == 0
    assert len(sync.rising_edges(shutter_col)) == 180
    assert budgets[0] == 5.25 and set(budgets[1:-1]) == {0.5} and budgets[-1] == math.inf
