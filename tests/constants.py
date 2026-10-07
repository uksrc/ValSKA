"""
Variables and util functions for testing
"""

import tempfile
from pathlib import Path

import numpy
from scipy.constants import c as speed_of_light
from scipy.special import j1

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


class MockDataContainer:
    """
    Mock class for reading and analyzing files output by BayesEoR.
    """

    def __init__(
        self,
        dirnames,
        dir_prefix=None,
        expected_ps=None,
        labels=None,
        additional_args=None,
    ):
        self.Ndirs = len(dirnames)
        self.dirnames = dirnames
        self.dir_prefix = dir_prefix
        self.labels = labels
        self.expected_ps = expected_ps
        self.additional_args = additional_args
        self.k_vals = [
            [0.1, 0.2, 0.3, 0.4],
            [0.5, 0.6, 0.7, 0.8],
        ]

    def plot_power_spectra_and_posteriors(self, **plot_args):
        """Return mock figure"""

        fig = MockFig(**plot_args)

        return fig


class MockFig:
    """Mock class for plot figure"""

    def __init__(self, **plot_args):
        self.axes = [MockAx()]
        for key, value in plot_args.items():
            setattr(self, key, value)


class MockAx:
    """Mock class for plot axes"""

    def __init__(self):
        self.leg = MockLegend()

    def get_legend(self):
        """Get legend"""
        return self.leg

    def legend(  # noqa: PLR0913
        self,
        handles,
        labels,
        loc,
        fontsize,
        ncol,
        frameon,
        framealpha,
    ):
        """Set legend parameters"""
        self.leg.legendHandles = handles
        self.leg.texts = [MockText(label) for label in labels]
        self.leg.set_loc(loc)
        self.leg.set_fontsize(fontsize)
        self.leg.ncol = ncol
        self.leg.frameon = frameon
        self.leg.framealpha = framealpha


class MockLegend:
    """Mock class for plot legend"""

    def __init__(self):
        # Legend with 3 default labels
        self.legendHandles = [1, 2, 3]
        self._loc = 1
        self._fontsize = 1
        self.texts = [MockText("A"), MockText("B"), MockText("Expected")]
        self.ncol = None
        self.frameon = True
        self.framealpha = 1.0

    def get_texts(self):
        """Return texts"""
        return self.texts

    def set_loc(self, loc):
        """Set loc"""
        self._loc = loc

    def set_fontsize(self, fontsize):
        """Set fontsize"""
        self._fontsize = fontsize


class MockText:
    """Mock class for legend text"""

    def __init__(self, text):
        self.text = text

    def get_text(self):
        """Get text"""
        return self.text

    def set_text(self, text):
        """Set text"""
        self.text = text


class MockChain:
    """
    Mock class for chain
    (to mock output of anesthetic.read_chains)
    """

    def __init__(self, chain_path):
        self.read_chain(chain_path)

    def read_chain(self, chain_path):
        """Read chain path and fill logZ"""
        with open(chain_path, encoding="utf-8") as file:
            self.logZ_value = file.read()

    def logZ(self):
        """Return logZ"""
        return self.logZ_value


def mock_read_chains(*args, **kwargs):
    """
    Mock method to replace anesthetic read_chains()
    """
    return MockChain(args[0])


def make_gaussian_data(
    theta,
    sigma=2.0,
    amplitude=1.0,
    centre=0.0,
):
    """Make Gaussian data"""
    return amplitude * numpy.exp(-((theta - centre) ** 2) / (2 * sigma**2))


def make_airy_data(
    freq_hz,
    theta,
    amplitude=1.0,
    centre=0.0,
    diameter=5.0,
):
    """Make Airy data"""

    lam = speed_of_light / freq_hz

    x = numpy.pi * diameter * numpy.sin(theta - centre) / lam
    beam = numpy.ones_like(x)
    mask = numpy.abs(x) > 1e-12

    beam[mask] = (2 * j1(x[mask]) / x[mask]) ** 2

    return amplitude * beam


def write_pyuvsim_config(tmp_path, config_text):
    """Write pyuvsim config file"""
    path = tmp_path / "config.yaml"
    path.write_text(config_text)
    return path
