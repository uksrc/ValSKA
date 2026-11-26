"""Mock classes used in tests"""


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
