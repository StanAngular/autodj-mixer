"""autodj.compose: toolkit for hand-written track scores (one short score file per track).

A score builds a Track (grid, sections, layers) with the helpers here; `python -m autodj.compose run score.py`
renders it, checks it, masters it and optionally sends it. Shared by every agent (cclaw, Hermes).
Each track is its own story: the kit gives mechanics, never fixed patterns. Lakh (lakh.py) is the one source of
learned musical habits (progressions, bass lines, drums per style), always drawn per seed, never hard-coded."""
from .core import Track, pb, mono2, fade, load_sample, sat, sweep, rms
from .lakh import Lakh
