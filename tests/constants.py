"""
Constant variables for testing
"""

import tempfile
from pathlib import Path

from valska.constants import (
    DEFAULT_EOR_POWER_MK2_MPC3,
    DEFAULT_NOISE_TO_EOR_POWER_RATIO,
)

# Use an ephemeral, writable temp directory for tests (not checked into VCS)
BASE_DIR = Path(tempfile.mkdtemp(prefix="valska_tests_")).resolve()
CHAINS_DIR = BASE_DIR / "chains"
DATA_DIR = BASE_DIR / "data"
RESULTS_DIR = BASE_DIR / "results"

# Ensure required subdirs exist
for d in (CHAINS_DIR, DATA_DIR, RESULTS_DIR):
    d.mkdir(parents=True, exist_ok=True)

EOR_PS = DEFAULT_EOR_POWER_MK2_MPC3
NOISE_RATIO = DEFAULT_NOISE_TO_EOR_POWER_RATIO
