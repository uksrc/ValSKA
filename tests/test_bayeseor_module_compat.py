"""Compatibility tests for relocated BayesEoR modules."""

import importlib
import warnings

from valska import evidence as compatibility_evidence
from valska import plotting as compatibility_plotting
from valska import utils as compatibility_utils
from valska.external_tools.bayeseor import (
    bayeseor_direct_plotting,
    chain_utils,
    evidence,
)


def test_top_level_evidence_imports_relocated_api() -> None:
    assert (
        compatibility_evidence.calculate_bayes_factor
        is evidence.calculate_bayes_factor
    )
    assert compatibility_evidence.ChainPair is evidence.ChainPair


def test_top_level_plotting_imports_relocated_api() -> None:
    assert (
        compatibility_plotting.BeamAnalysisPlotter
        is bayeseor_direct_plotting.BeamAnalysisPlotter
    )


def test_legacy_package_plotting_imports_relocated_api() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        legacy_plotting = importlib.import_module("valska_hera_beam.plotting")

    assert (
        legacy_plotting.BeamAnalysisPlotter
        is bayeseor_direct_plotting.BeamAnalysisPlotter
    )


def test_top_level_utils_delegate_to_chain_utils() -> None:
    pairs = {
        "GSM_FgEoR_-1e0pp": "outside",
        "GSM_FgEoR_1e-1pp": "inside",
    }

    assert compatibility_utils.filter_chain_pairs(pairs) == (
        chain_utils.filter_chain_pairs(pairs)
    )
