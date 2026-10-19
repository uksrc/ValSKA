"""Unit tests for plotting delegated directly to BayesEoR."""

import tempfile
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import numpy
import pytest

from valska.external_tools.bayeseor import bayeseor_direct_plotting

from .constants import (
    # CHAINS_DIR,
    EOR_PS,
    NOISE_RATIO,
    MockDataContainer,
)


def test_create_beam_plotter_with_paths_file(path_manager):
    """Test creating beam plotter with paths in yaml file"""

    with tempfile.NamedTemporaryFile(mode="w+t") as yaml_file:
        yaml_file.writelines(
            "Test1: test/directory1/\nTest2: test/directory2/"
        )
        yaml_file.seek(0)

        beam_analysis_plotter = bayeseor_direct_plotting.BeamAnalysisPlotter(
            base_chains_dir=path_manager.chains_dir,
            paths_file=yaml_file.name,
        )

        yaml_file.close()

        assert beam_analysis_plotter.paths["Test1"] == "test/directory1/"
        assert beam_analysis_plotter.paths["Test2"] == "test/directory2/"


def test_create_beam_plotter_with_paths_dict(path_manager):
    """Test creating beam plotter with paths in dictionary"""

    paths = {
        "Test1": "test/directory1/",
        "Test2": "test/directory2/",
    }

    beam_analysis_plotter = bayeseor_direct_plotting.BeamAnalysisPlotter(
        base_chains_dir=path_manager.chains_dir,
        paths=paths,
    )

    assert beam_analysis_plotter.paths["Test1"] == "test/directory1/"
    assert beam_analysis_plotter.paths["Test2"] == "test/directory2/"


def test_add_analysis_path(beam_analysis):
    """Test adding an analysis path to BeamAnalysisPlotter"""

    key = "test3"
    value = "test/directory3/"

    beam_analysis.add_analysis_path(key, value)

    assert (key, value) in beam_analysis.paths.items()


@pytest.mark.parametrize(
    "analysis_keys, labels, expected_ps, expected_results",
    [
        (
            ["Test1"],
            None,
            None,
            {
                "dirnames": ["test/directory1/"],
                "dir_prefix": None,
                "exp_ps": EOR_PS * NOISE_RATIO,
                "labels": ["Test1"],
            },
        ),
        (
            ["Test1", "Test2"],
            None,
            None,
            {
                "dirnames": ["test/directory1/", "test/directory2/"],
                "dir_prefix": None,
                "exp_ps": EOR_PS * NOISE_RATIO,
                "labels": ["Test1", "Test2"],
            },
        ),
        (
            ["Test1"],
            ["Label1"],
            1.0,
            {
                "dirnames": ["test/directory1/"],
                "dir_prefix": None,
                "exp_ps": 1.0,
                "labels": ["Label1"],
            },
        ),
    ],
)
@patch(
    "valska.external_tools.bayeseor.bayeseor_direct_plotting.DataContainer",
    MockDataContainer,
)
def test_get_data_container(
    beam_analysis, analysis_keys, labels, expected_ps, expected_results
):
    """
    Test for get_data_container using the MockDataContainer to show that
    the inputs are correct - the real DataContainer class is within BayesEoR
    and so we only need to test that we are sending the correct inputs
    to it.
    """

    data_container = beam_analysis.get_data_container(
        analysis_keys,
        labels,
        expected_ps,
    )

    assert data_container.Ndirs == len(expected_results["dirnames"])
    assert data_container.dirnames == expected_results["dirnames"]
    # dir_prefix depends on the runtime beam_analysis base_chains_dir;
    # if expected_results["dir_prefix"] is None, use the beam_analysis value.
    expected_dir_prefix = (
        Path(expected_results["dir_prefix"])
        if expected_results["dir_prefix"] is not None
        else Path(beam_analysis.base_chains_dir)
    )
    assert data_container.dir_prefix == expected_dir_prefix
    assert data_container.expected_ps == expected_results["exp_ps"]
    assert data_container.labels == expected_results["labels"]


@pytest.mark.parametrize(
    "input_args, expected_results",
    [
        (  # Case with MINIMUM number of arguments (i.e. testing defaults)
            {
                "analysis_keys": ["Test1", "Test2", "Test3"],
            },
            {
                "suptitle": "UKSRC validation: Burba et al. 2023",
                "plot_fracdiff": True,
                "uplim_inds": numpy.array(
                    [
                        [True, False, False, False],
                        [True, False, False, False],
                        [True, False, False, False],
                    ]
                ),
                "plot_priors": True,
                "ls_expected": ":",
                "labels": None,
                "texts": ["Test1", "Test2", "Noise level"],
                "ncol": 3,
            },
        ),
        (  # Case with NO uplims set AND fracdiff and priors set to False
            {
                "analysis_keys": ["Test1", "Test2"],
                "ignore_uplims": True,
                "plot_fracdiff": False,
                "plot_priors": False,
            },
            {
                "suptitle": "UKSRC validation: Burba et al. 2023",
                "plot_fracdiff": False,
                "uplim_inds": numpy.array([None]),
                "plot_priors": False,
                "ls_expected": ":",
                "labels": None,
                "texts": ["Test1", "Test2", "Noise level"],
                "ncol": 3,
            },
        ),
        (  # Case to exercise the options to set upper limits and titles/labels
            {
                "analysis_keys": ["Test1", "Test2"],
                "labels": ["Label1", "Label2"],
                "suptitle": "My Title",
                "expected_label": "My Plot Label",
                # sets this idx to True for all analysis keys
                "upper_limit_indices": [1],
                # sets back to False for specified key
                "detection_indices": {"Test1": [1]},
                "ignore_uplims": False,
                "ls_expected": ".",  # modifies from default ":"
                "figsize": [10, 20],  # sets plot width
                "plot_kwargs": {"test_arg": "Test Value"},
            },
            {
                "suptitle": "My Title",
                "plot_fracdiff": True,
                "uplim_inds": numpy.array(
                    [[False, False, False, False], [False, True, False, False]]
                ),
                "plot_priors": True,
                "ls_expected": ".",
                "labels": ["Label1", "Label2"],
                "texts": ["Label1", "Label2", "My Plot Label"],
                "ncol": 3,
                "plot_width": 5,  # ["figsize"][0] / 2
                "test_arg": "Test Value",
            },
        ),
    ],
)
@patch(
    "valska.external_tools.bayeseor.bayeseor_direct_plotting.DataContainer",
    MockDataContainer,
)
def test_plot_analysis_results(beam_analysis, input_args, expected_results):
    """
    Test analysis plot method

    This method is basically a wrapper for the
    "plot_power_spectra_and_posteriors" method in the BayesEoR DataContainer
    class.

    Assume that the BayesEoR method has already been tested in BayesEoR and
    does not need testing again. It returns the fig object.

    We need to test that the labels and legend are set up correctly in the
    fig object according to the parameters in ValSKA. Therefore override the
    BayesEoR method (in the MockDataContainer) to return a MockFig object
    which takes the plot_args from ValSKA "plot_analysis_results". Then
    we can check the plot_args sent to BayesEoR are set up as expected. This
    tests the code in ValSKA but not BayesEoR (or matplotlib).

    Note: the mock legend is set up with only 3 entries no matter how many
    inputs there are.
    """

    fig = beam_analysis.plot_analysis_results(**input_args)

    assert fig.suptitle == expected_results["suptitle"]

    assert fig.plot_fracdiff == expected_results["plot_fracdiff"]
    assert fig.plot_priors == expected_results["plot_priors"]

    numpy.testing.assert_array_equal(
        fig.uplim_inds, expected_results["uplim_inds"]
    )

    assert fig.ls_expected == expected_results["ls_expected"]
    assert fig.labels == expected_results["labels"]

    # This is set by default and cannot be changed at the moment
    assert fig.legend_ncols == 6  # noqa: PLR2004

    if "figsize" in input_args.keys():
        assert fig.plot_width == int(input_args["figsize"][0] / 2)

    # Checks that additional plot_kwargs are passed on
    if "plot_kwargs" in input_args.keys():
        for kwarg in input_args["plot_kwargs"].keys():
            assert getattr(fig, kwarg) == expected_results[kwarg]

    # Legend labels
    assert fig.axes[0].leg.ncol == expected_results["ncol"]
    assert fig.axes[0].leg.texts[0].text == expected_results["texts"][0]
    assert fig.axes[0].leg.texts[1].text == expected_results["texts"][1]
    assert fig.axes[0].leg.texts[2].text == expected_results["texts"][2]


@pytest.mark.parametrize(
    "input_args, expected_results",
    [
        (  # Second group only has one analysis key
            {
                "groups": {"Group1": ["Test1", "Test2"], "Group2": ["Test1"]},
            },
            {
                "suptitle": "HERA FWHM Sensitivity Analysis",
                "labels": ["Group1 - Test1", "Group1 - Test2", "Group2"],
                "texts": ["Group1 - Test1", "Group1 - Test2", "Noise level"],
                "ncol": 3,
            },
        ),
        (  # Groups have same analysis keys
            {
                "groups": {
                    "Group1": ["Test1", "Test2"],
                    "Group2": ["Test1", "Test2"],
                },
            },
            {
                "suptitle": "HERA FWHM Sensitivity Analysis",
                "labels": [
                    "Group1 - Test1",
                    "Group1 - Test2",
                    "Group2 - Test1",
                    "Group2 - Test2",
                ],
                "texts": ["Group1 - Test1", "Group1 - Test2", "Noise level"],
                "ncol": 3,
            },
        ),
        (  # Groups have different analysis keys
            {
                "groups": {
                    "Group1": ["Test1", "Test2"],
                    "Group2": ["Test3", "Test4"],
                },
            },
            {
                "suptitle": "HERA FWHM Sensitivity Analysis",
                "labels": [
                    "Group1 - Test1",
                    "Group1 - Test2",
                    "Group2 - Test3",
                    "Group2 - Test4",
                ],
                "texts": [
                    "Group1 - Test1",
                    "Group1 - Test2",
                    "Noise level",
                ],  # I've only defined 3 labels in the mock legend!
                "ncol": 3,
            },
        ),
        (  # Input labels and title
            {
                "groups": {
                    "Group1": ["Test1", "Test2"],
                    "Group2": ["Test1", "Test2"],
                },
                "group_labels": {"Group1": "Label1", "Group2": "Label2"},
                "suptitle": "My Title",
            },
            {
                "suptitle": "My Title",
                "labels": [
                    "Label1 - Test1",
                    "Label1 - Test2",
                    "Label2 - Test1",
                    "Label2 - Test2",
                ],
                "texts": [
                    "Label1 - Test1",
                    "Label1 - Test2",
                    "Noise level",
                ],  # I've only defined 3 labels in the mock legend!
                "ncol": 3,
            },
        ),
    ],
)
@patch(
    "valska.external_tools.bayeseor.bayeseor_direct_plotting.DataContainer",
    MockDataContainer,
)
def test_create_comparison_plot(beam_analysis, input_args, expected_results):
    """
    Test create_comparison_plot

    This method calls plot_analysis_results with a group of labels
    for comparison plots.

    Note: the mock legend is set up with only 3 entries no matter how many
    inputs there are
    """

    fig = beam_analysis.create_comparison_plot(**input_args)

    assert fig.suptitle == expected_results["suptitle"]

    assert fig.labels == expected_results["labels"]

    # Legend labels
    assert fig.axes[0].leg.ncol == expected_results["ncol"]
    assert fig.axes[0].leg.texts[0].text == expected_results["texts"][0]
    assert fig.axes[0].leg.texts[1].text == expected_results["texts"][1]
    assert fig.axes[0].leg.texts[2].text == expected_results["texts"][2]


@patch(
    "valska.external_tools.bayeseor.bayeseor_direct_plotting.DataContainer",
    MockDataContainer,
)
def test_plot_gleam_analysis(path_manager):
    """
    Test plot_gleam_analysis

    It creates a Plotter and calls plot_analysis_results with titles for
    GLEAM analysis
    """

    fig = cast(
        Any,
        bayeseor_direct_plotting.plot_gleam_analysis(path_manager.chains_dir),
    )

    expected_title = (
        "UKSRC validation: Burba et al. 2023, Case 1. \n"
        "12.9 deg. GLEAM Analysis."
    )
    assert fig.suptitle == expected_title

    assert fig.labels == ["GLEAM"]
    # I've defined 3 labels in the mock legend so second one
    # has not been updated (should still be "B").
    assert fig.axes[0].leg.texts[0].text == "GLEAM"
    assert fig.axes[0].leg.texts[1].text == "B"
    assert fig.axes[0].leg.texts[2].text == "Noise level"


@patch(
    "valska.external_tools.bayeseor.bayeseor_direct_plotting.DataContainer",
    MockDataContainer,
)
def test_plot_gsm_comparison(path_manager):
    """
    Test plot_gsm_comparison

    It creates a Plotter and calls plot_analysis_results with titles for
    GSM foreground analysis
    """

    fig = cast(
        Any,
        bayeseor_direct_plotting.plot_gsm_comparison(path_manager.chains_dir),
    )

    assert (
        fig.suptitle
        == "Impact of FWHM Perturbations on GSM Foreground Analysis"
    )
    assert fig.labels == ["-0.1% FWHM", "-1% FWHM", "-5% FWHM"]
    # I've only defined 3 labels in the mock legend!
    assert fig.axes[0].leg.texts[0].text == "-0.1% FWHM"
    assert fig.axes[0].leg.texts[1].text == "-1% FWHM"
    assert fig.axes[0].leg.texts[2].text == "Noise level"
