"""Tonality-free melodic reduction (foreground/middleground hierarchy, focal pitches)."""
from .analyze import analyze, load_weights, write_json, summary, choose_fundamental
from .voice import load_voice, VNote
from .mop import parse, RELATIONS
from .focal import focal_spans, dominant_spans, pitch_profile
from .features import find_modules

__version__ = '0.1.0'
