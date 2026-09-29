"""Integration test on the Dominus benchmark; runs only when the data are available:
LR_CANDR_DIR (CANDR setting_*.mei) and LR_EDITIONS (DominusN.xml)."""
import os
from pathlib import Path

import pytest

from ligature_rhythm.evaluate import Benchmark

SPEC = Path(__file__).parent.parent / 'benchmarks' / 'dominus.json'
pytestmark = pytest.mark.skipif(not (os.environ.get('LR_CANDR_DIR') and os.environ.get('LR_EDITIONS')),
                                reason='Dominus data not available')


def test_dominus_in_sample_accuracy():
    b = Benchmark.load(SPEC, os.environ['LR_CANDR_DIR'], os.environ['LR_EDITIONS'])
    df = b.evaluate(pieces=['3', '12', '13'])
    assert df['dup_dur'].mean() > 0.95 and df['ten_dur'].mean() > 0.95
