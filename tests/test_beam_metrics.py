"""Unit tests for beam metrics"""

from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import numpy
import pytest
from astropy.coordinates import Angle

from tests.utils import make_airy_data, make_gaussian_data
from valska import beam_metrics

CONFIG_TEXT = (
    "beam_paths:\n"
    "  0: !AnalyticBeam\n"
    "{beam_spec}\n"
    "    reference_frequency: 150000000.0\n"
    "telescope_location: (-26.7, 20.0, 1073.0)\n"
    "telescope_name: Dummy"
)
BEAM_SPEC = "    class: GaussianBeam\n    sigma: 0.2"


def test_beam_width_gaussian_fit_recovers_fwhm():
    """
    Test beam_width_vs_frequency to verify gaussian returns FWHM
    """

    theta = numpy.linspace(-10, 10, 200)
    sigma = 2.0

    y = make_gaussian_data(theta, sigma=sigma)

    # shape: (angle, frequency)
    v_auto = y[:, numpy.newaxis]
    freq = numpy.array([1.0])

    fwhm, chi2, gauss_result, airy_result = (
        beam_metrics.fit_beam_width_vs_frequency(
            freq=freq,
            theta_deg=theta,
            v_auto=v_auto,
            shape="GaussianBeam",
        )
    )

    expected_fwhm = 2 * numpy.sqrt(2 * numpy.log(2)) * sigma

    assert numpy.isclose(
        fwhm[0],
        expected_fwhm,
        rtol=0.05,
    )

    assert gauss_result is not None
    assert airy_result is None


def test_beam_width_gaussian_fit_multiple_frequencies():
    """Test beam_width_vs_frequency with multiple freqs"""

    theta = numpy.linspace(-10, 10, 200)
    sigmas = [1.0, 2.0, 3.0]

    data = numpy.column_stack(
        [make_gaussian_data(theta, sigma=s) for s in sigmas]
    )
    freq = numpy.array([1.0, 2.0, 3.0])

    fwhm, _, _, _ = beam_metrics.fit_beam_width_vs_frequency(
        freq=freq,
        theta_deg=theta,
        v_auto=data,
        shape="GaussianBeam",
    )

    expected = [2 * numpy.sqrt(2 * numpy.log(2)) * s for s in sigmas]

    assert numpy.allclose(fwhm, expected, rtol=0.05)


def test_beam_width_airy_fit_returns_parameters():
    """Test beam_width_vs_frequency with Airy"""

    theta = numpy.linspace(-20, 20, 500)
    freqs = numpy.array([150000000.0])

    y = make_airy_data(freqs[0], numpy.radians(theta), diameter=14.0)

    v_auto = y[:, numpy.newaxis]

    fwhm, chi2, gauss_result, airy_result = (
        beam_metrics.fit_beam_width_vs_frequency(
            freq=freqs,
            theta_deg=theta,
            v_auto=v_auto,
            shape="AiryBeam",
        )
    )

    # Airy branch should not populate Gaussian params
    assert gauss_result is None

    # Airy fit should succeed
    assert airy_result is not None

    # Diameter should be approximately recovered
    assert numpy.isclose(
        airy_result.params["diam"].value,
        14.0,
        rtol=0.1,
    )


def test_beam_width_invalid_shape_raises_value_error():
    """Test beam_width_vs_frequency error handling"""

    theta = numpy.linspace(-10, 10, 100)
    v_auto = numpy.ones((100, 1))
    freq = numpy.array([1.0])

    with pytest.raises(ValueError):
        beam_metrics.fit_beam_width_vs_frequency(
            freq=freq,
            theta_deg=theta,
            v_auto=v_auto,
            shape="NotARealShape",
        )


def test_beam_width_empty_mask_returns_nan():
    """Test beam_width_vs_frequency returns nan"""

    theta = numpy.linspace(-10, 10, 100)

    # Everything below mask threshold (0.2)
    v_auto = numpy.zeros((100, 1))
    freq = numpy.array([1.0])

    fwhm, _, _, _ = beam_metrics.fit_beam_width_vs_frequency(
        freq=freq,
        theta_deg=theta,
        v_auto=v_auto,
        shape="GaussianBeam",
    )

    assert numpy.isnan(fwhm[0])


def test_beam_width_gaussian_fit_with_noise():
    """Test beam_width_vs_frequency Gaussian with noise"""

    rng = numpy.random.default_rng(12345)

    theta = numpy.linspace(-10, 10, 300)

    sigma = 2.5

    clean = make_gaussian_data(theta, sigma=sigma)

    noisy = clean + rng.normal(0, 0.02, size=theta.size)

    v_auto = noisy[:, numpy.newaxis]
    freq = numpy.array([1.0])

    fwhm, _, _, _ = beam_metrics.fit_beam_width_vs_frequency(
        freq=freq,
        theta_deg=theta,
        v_auto=v_auto,
        shape="GaussianBeam",
    )

    expected = 2 * numpy.sqrt(2 * numpy.log(2)) * sigma

    assert numpy.isclose(
        fwhm[0],
        expected,
        rtol=0.1,
    )


def test_chromaticity_returns_expected_correlation(capsys):
    """
    Test that the function returns the expected correlation
    for a simple monotonic relationship.
    """
    freq = numpy.array([1, 1.2, 1.5, 2, 3, 6], dtype=float)
    param = numpy.array([6, 5, 4, 3, 2, 1], dtype=float)

    result = beam_metrics.chromaticity_test(freq, param)

    expected = 1.0

    assert numpy.isclose(result["correlation"], expected)


def test_chromaticity_ignores_nan_values():
    """
    Test that NaN values are excluded from the correlation calculation.
    """
    freq = numpy.array(
        [0.091, 0.1, 0.111, 0.125, 0.143, 0.167, 0.2, 0.25, 0.333, 0.5, 1.0],
        dtype=float,
    )
    param = numpy.array(
        [
            11,
            numpy.nan,
            9,
            numpy.nan,
            7,
            numpy.nan,
            5,
            numpy.nan,
            3,
            numpy.nan,
            1,
        ],
        dtype=float,
    )

    result = beam_metrics.chromaticity_test(freq, param)

    expected = 1.0

    assert numpy.isclose(result["correlation"], expected, equal_nan=True)


def test_chromaticity_returns_nan_when_not_enough_samples():
    """
    If the number of valid samples is <= CORR_SAMPLES,
    the function should return NaN.
    """
    freq = numpy.array([1, 2], dtype=float)
    param = numpy.array([1, 2], dtype=float)

    result = beam_metrics.chromaticity_test(freq, param)

    assert numpy.isclose(result["correlation"], numpy.nan, equal_nan=True)
    assert numpy.isclose(result["freq_std"], 0.5 / 1.5)
    assert numpy.isclose(result["freq_grad"], 1.0 / 1.5)
    assert numpy.isclose(result["frac_resid"], 0.0)


def test_chromaticity_all_nan_input():
    """
    Test behavior when all parameter values are NaN.
    """
    freq = numpy.array([1, 2, 3], dtype=float)
    param = numpy.array([numpy.nan, numpy.nan, numpy.nan])

    result = beam_metrics.chromaticity_test(freq, param)

    assert numpy.isclose(result["correlation"], numpy.nan, equal_nan=True)
    assert numpy.isclose(result["freq_std"], 0.0)
    assert numpy.isclose(result["freq_grad"], 0.0)
    assert numpy.isclose(result["frac_resid"], 0.0)


def test_chromaticity_constant_parameter():
    """
    Constant parameter arrays produce zero slope and undefined correlation.
    """
    freq = numpy.array([1, 2, 3, 4, 5, 6], dtype=float)
    param = numpy.ones(6)

    result = beam_metrics.chromaticity_test(freq, param)

    assert numpy.isclose(result["correlation"], numpy.nan, equal_nan=True)
    assert numpy.isclose(result["freq_std"], 0.0)
    assert numpy.isclose(result["freq_grad"], 0.0)
    assert numpy.isclose(result["frac_resid"], 0.0)


def test_plot_beam_shape_basic():
    ax = MagicMock()

    theta = numpy.array([0, 1, 2])
    y = numpy.array([1, 2, 3])
    freq = 1e6

    beam_metrics.plot_beam_shape(ax, theta, y, freq)

    # Beam data plotted
    ax.plot.assert_called()
    ax.set_xlabel.assert_called_with("Angle (deg)")
    ax.set_ylabel.assert_called_with("Stokes I (XX+YY) Amplitude (Jy)")
    ax.set_title.assert_called_with("Autocorrelation beam profile (1.0 MHz)")
    ax.legend.assert_called_once()
    ax.set_yscale.assert_not_called()


def test_plot_beam_shape_with_fits():
    ax = MagicMock()

    theta = numpy.array([0, 1, 2])
    y = numpy.array([1, 2, 3])
    freq = 2e6

    gauss_result = MagicMock()
    airy_result = MagicMock()

    gauss_result.eval.return_value = numpy.array([0.1, 0.2, 0.3])
    airy_result.eval.return_value = numpy.array([0.2, 0.3, 0.4])

    beam_metrics.plot_beam_shape(ax, theta, y, freq, gauss_result, airy_result)

    # Ensure eval was called
    gauss_result.eval.assert_called()
    airy_result.eval.assert_called()

    # Check that fits were plotted
    assert ax.plot.call_count >= 3  # data + two fits


def test_plot_beam_shape_ylog():
    ax = MagicMock()

    theta = numpy.array([0, 1, 2])
    y = numpy.array([1, 2, 3])
    freq = 1e6

    beam_metrics.plot_beam_shape(ax, theta, y, freq, ylog=True)

    ax.set_yscale.assert_called_once_with("log")


def test_plot_spectrum_basic():
    ax = MagicMock()

    freq = numpy.array([1, 2, 3, 4, 5])
    param = numpy.array([10, 20, 30, 40, 50])

    beam_metrics.plot_spectrum(ax, freq, param, "Power", "Test Spectrum")

    ax.plot.assert_called_with(freq, param, "o")
    ax.set_xlabel.assert_called_with("Frequency (MHz)")
    ax.set_ylabel.assert_called_with("Power")
    ax.set_title.assert_called_with("Test Spectrum")

    # Check midpoint marker lines
    mid_idx = len(freq) // 2
    mid_x = freq[mid_idx]
    mid_y = param[mid_idx]

    ax.axhline.assert_called_with(
        mid_y, color="red", linestyle="--", linewidth=1
    )
    ax.axvline.assert_called_with(
        mid_x, color="red", linestyle="--", linewidth=1
    )


def test_plot_spectrum_midpoint_is_correct():
    ax = MagicMock()

    freq = numpy.array([10, 20, 30, 40])
    param = numpy.array([1, 2, 3, 4])

    beam_metrics.plot_spectrum(ax, freq, param, "Y", "T")

    mid_idx = len(freq) // 2  # 2
    assert ax.axhline.call_args[0][0] == param[mid_idx]
    assert ax.axvline.call_args[0][0] == freq[mid_idx]


def test_beam_metrics_init():

    with patch("valska.beam_metrics.SimulationConfig") as mock_config:
        mock_config.return_value = Mock()

        bm = beam_metrics.BeamMetrics(
            "test.uvh5",
            "config.yaml",
            Path("templates"),
        )

        mock_config.assert_called_once_with(
            Path("config.yaml"),
            Path("templates"),
        )

        assert bm.simulation_config is mock_config.return_value

    assert bm.uv_filename == "test.uvh5"

    numpy.testing.assert_array_equal(bm.baseline_counts, numpy.array([]))
    numpy.testing.assert_array_equal(bm.lsts_hours, numpy.array([]))
    numpy.testing.assert_array_equal(bm.theta_deg, numpy.array([]))
    numpy.testing.assert_array_equal(bm.freq_array, numpy.array([]))
    numpy.testing.assert_array_equal(bm.v_auto, numpy.array([]))
    numpy.testing.assert_array_equal(bm.v_time_bl, numpy.array([]))


def test_prepare_uv_data_success(tmp_path):

    with patch("valska.beam_metrics.SimulationConfig") as mock_config:
        mock_sim_config = Mock()
        mock_sim_config.latitude = Angle(-26.7, unit="deg")
        mock_sim_config.source_ra = Angle([0.15], unit="rad")
        mock_config.return_value = mock_sim_config

        bm = beam_metrics.BeamMetrics(
            "test.uvh5",
            "config.yaml",
            Path("templates"),
        )

    mock_uv = MagicMock()

    mock_uv.time_array = numpy.array([1.0, 1.0, 2.0, 2.0])
    mock_uv.lst_array = numpy.array([0.1, 0.1, 0.2, 0.2])
    mock_uv.freq_array = numpy.array([[100e6, 110e6]])

    # Shape:
    # (Nblts=4, Nspws=1, Nfreqs=2, Npols=2)
    mock_uv.data_array = numpy.ones((4, 1, 2, 2), dtype=complex)

    mock_uv.select.return_value = mock_uv

    bm.prepare_uv_data(mock_uv)

    assert bm.baseline_counts.tolist() == [2, 2]

    numpy.testing.assert_array_equal(
        bm.freq_array,
        numpy.array([100e6, 110e6]),
    )

    # Shape should be (Ntimes, Nfreqs)
    assert bm.v_auto.shape == (2, 2)

    # Shape should be (Ntimes, Nbls)
    assert bm.v_time_bl.shape == (2, 2)

    assert len(bm.theta_deg) == 2

    numpy.testing.assert_allclose(
        bm.theta_deg, numpy.array([-2.55926667, 2.55926667])
    )


def test_prepare_uv_data_raises_for_inconsistent_baselines(tmp_path):

    with patch("valska.beam_metrics.SimulationConfig") as mock_config:
        mock_config.return_value = Mock()

        bm = beam_metrics.BeamMetrics(
            "test.uvh5",
            "config.yaml",
        )

    mock_uv = MagicMock()

    # Uneven baseline counts per time
    mock_uv.time_array = numpy.array([1.0, 1.0, 2.0])
    mock_uv.lst_array = numpy.array([0.1, 0.1, 0.2])
    mock_uv.freq_array = numpy.array([[100e6, 110e6]])

    mock_uv.data_array = numpy.ones((3, 1, 2, 2), dtype=complex)

    mock_uv.select.return_value = mock_uv

    with pytest.raises(
        ValueError,
        match="Baselines per time are not constant",
    ):
        bm.prepare_uv_data(mock_uv)


@patch("valska.beam_metrics.chromaticity_test")
@patch("valska.beam_metrics.fit_beam_width_vs_frequency")
def test_compute_beam_metrics(
    mock_fit,
    mock_chromaticity,
    tmp_path,
):
    with patch("valska.beam_metrics.SimulationConfig") as mock_config:
        mock_config.return_value = Mock()

        bm = beam_metrics.BeamMetrics(
            "test.uvh5",
            "config.yaml",
        )

    bm.theta_deg = numpy.array([-5, 0, 5])
    bm.v_auto = numpy.ones((3, 4))
    bm.freq_array = numpy.array([100e6, 110e6, 120e6, 130e6])

    mock_fit.return_value = (
        numpy.array([10.0, 11.0, 12.0, 13.0]),
        numpy.array([1.0, 1.0, 1.0, 1.0]),
        "gauss_result",
        "airy_result",
    )

    bm.compute_beam_metrics()

    assert bm.gauss_result == "gauss_result"
    assert bm.airy_result == "airy_result"

    numpy.testing.assert_array_equal(
        bm.fit_vs_freq,
        numpy.array([10.0, 11.0, 12.0, 13.0]),
    )

    mock_fit.assert_called_once()
    mock_chromaticity.assert_called_once()


@patch("valska.beam_metrics.plt.show")
@patch("valska.beam_metrics.plot_waterfall_matplotlib")
@patch("valska.beam_metrics.plot_spectrum")
@patch("valska.beam_metrics.plot_beam_shape")
@patch("valska.beam_metrics.plot_baseline_heatmap")
def test_make_plots(
    mock_heatmap,
    mock_beam_shape,
    mock_spectrum,
    mock_waterfall,
    mock_show,
):
    with patch("valska.beam_metrics.SimulationConfig") as mock_config:
        mock_config.return_value = Mock()

        bm = beam_metrics.BeamMetrics(
            "test.uvh5",
            "config.yaml",
        )

    bm.v_auto = numpy.ones((2, 4))
    bm.v_time_bl = numpy.ones((2, 2))
    bm.baseline_counts = numpy.array([2, 2])
    bm.lsts_hours = numpy.array([1.0, 2.0])
    bm.theta_deg = numpy.array([-1.0, 1.0])
    bm.freq_array = numpy.array([100e6, 110e6, 120e6, 130e6])
    bm.gauss_result = "gauss"
    bm.airy_result = "airy"
    bm.fit_vs_freq = numpy.array([1, 2, 3, 4])

    bm.make_plots()

    mock_heatmap.assert_called_once()
    mock_beam_shape.assert_called_once()
    mock_spectrum.assert_called_once()
    mock_waterfall.assert_called_once()
    mock_show.assert_called_once()


@patch("valska.beam_metrics.plt.show")
@patch("valska.beam_metrics.plot_waterfall_matplotlib")
@patch("valska.beam_metrics.plot_spectrum")
@patch("valska.beam_metrics.plot_beam_shape")
@patch("valska.beam_metrics.plot_baseline_heatmap")
def test_make_plots_can_save_without_showing(
    mock_heatmap,
    mock_beam_shape,
    mock_spectrum,
    mock_waterfall,
    mock_show,
    tmp_path,
):
    with patch("valska.beam_metrics.SimulationConfig") as mock_config:
        mock_config.return_value = Mock()

        bm = beam_metrics.BeamMetrics(
            "test.uvh5",
            "config.yaml",
        )

    bm.v_auto = numpy.ones((2, 4))
    bm.v_time_bl = numpy.ones((2, 2))
    bm.baseline_counts = numpy.array([2, 2])
    bm.lsts_hours = numpy.array([1.0, 2.0])
    bm.theta_deg = numpy.array([-1.0, 1.0])
    bm.freq_array = numpy.array([100e6, 110e6, 120e6, 130e6])
    bm.gauss_result = "gauss"
    bm.airy_result = None
    bm.fit_vs_freq = numpy.array([1, 2, 3, 4])

    save_path = tmp_path / "beam_metrics.png"

    bm.make_plots(
        save_path=save_path,
        show=False,
    )

    assert save_path.exists()
    mock_heatmap.assert_called_once()
    mock_beam_shape.assert_called_once()
    mock_spectrum.assert_called_once()
    mock_waterfall.assert_called_once()
    mock_show.assert_not_called()


@patch("valska.beam_metrics.UVData")
def test_check_beam(mock_uvdata):

    with patch("valska.beam_metrics.SimulationConfig") as mock_config:
        mock_config.return_value = Mock()

        bm = beam_metrics.BeamMetrics(
            "test.uvh5",
            "config.yaml",
        )

    with (
        patch.object(bm, "prepare_uv_data") as mock_prepare,
        patch.object(
            bm,
            "compute_beam_metrics",
            return_value=(numpy.array([1]), numpy.array([1]), "g", "a"),
        ) as mock_compute,
        patch.object(bm, "make_plots") as mock_plots,
        patch.object(bm, "write_report", return_value={}) as mock_write,
    ):
        mock_uv_instance = MagicMock()
        mock_uvdata.from_file.return_value = mock_uv_instance

        bm.check_beam()

        mock_uvdata.from_file.assert_called_once_with("test.uvh5")
        mock_prepare.assert_called_once_with(mock_uv_instance)
        mock_compute.assert_called_once()
        mock_plots.assert_called_once()
        mock_write.assert_called_once()
