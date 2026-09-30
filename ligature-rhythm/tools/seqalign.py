"""Semi-global alignment of pitch sequences (used to match editions with CANDR)."""
import numpy as np


def semiglobal(a, b) -> float:
    """Score of aligning all of `a` inside `b` (free leading/trailing gaps in b), per note of a:
    +1 match, -1 mismatch, -1 gap. Vectorised over b; gaps in a use a running maximum."""
    a, b = np.asarray(a), np.asarray(b)
    if len(a) == 0 or len(b) == 0:
        return -1.0
    m = len(b)
    idx = np.arange(m + 1)
    H = np.zeros(m + 1)
    for i in range(1, len(a) + 1):
        diag = H[:-1] + np.where(b == a[i - 1], 1.0, -1.0)
        new = np.empty(m + 1)
        new[0] = -i
        new[1:] = np.maximum(diag, H[1:] - 1)
        H = np.maximum.accumulate(new + idx) - idx
    return float(H.max() / len(a))
