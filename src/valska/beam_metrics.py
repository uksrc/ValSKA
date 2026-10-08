from __future__ import annotations

import argparse
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import lmfit
import matplotlib.axes
import matplotlib.lines
import matplotlib.pyplot as plt
import numpy
from matplotlib.ticker import FuncFormatter, MultipleLocator
from pyuvdata import UVData
from scipy.constants import c as speed_of_light
from scipy.special import j1

from valska.simulation_config import SimulationConfig

log = logging.getLogger(__name__)

CORR_SAMPLES = 5


def _airy(
    theta: numpy.typing.NDArray,
    freq_hz: float,
    A: float,
    theta0: float,
    diam: float,
) -> numpy.typing.NDArray:
    """
    Airy power beam for a circular aperture.
    """
    lam = speed_of_light / freq_hz

    x = numpy.pi * diam * numpy.sin(theta - theta0) / lam
    beam = numpy.ones_like(x)
    mask = numpy.abs(x) > 1e-12

    beam[mask] = (2 * j1(x[mask]) / x[mask]) ** 2

    return A * beam


class BeamMetrics:
    def __init__(
        self,
        filename: str,
        config_yaml: Path | str,
        template_dir: Path | None = None,
    ):

        self.uv_filename = filename
        self.config_yaml = config_yaml

        self.simulation_config = SimulationConfig(
            Path(config_yaml), template_dir
        )

        self.save_path = None

        # derived quantities
        self.baseline_counts = numpy.array([])
        self.lsts_hours = numpy.array([])
        self.theta_deg = numpy.array([])
        self.freq_array = numpy.array([])
        self.v_auto = numpy.array([])
        self.v_time_bl = numpy.array([])

        self.fit_vs_freq = numpy.array([])
        self.chi2_vs_freq = numpy.array([])
        self.gauss_result = None
        self.airy_result = None

        self.results: dict[str, Any] = {}

    def check_beam(
        self,
        save_path: str | Path | None = None,
        show: bool = True,
        beam_ylog: bool = False,
    ):
        """
        Check beam parameters from pyuvsim data and produce
        validation report and plots.
        """

        uvd = UVData.from_file(self.uv_filename)
        self.prepare_uv_data(uvd)
        self.compute_beam_metrics()
        self.make_plots(
            save_path=save_path,
            show=show,
            beam_ylog=beam_ylog,
        )

        return self.write_report()

    def write_report(self):
        """Write report and collect results"""

        log.info("***** Beam Check Report *****\n")
        log.info("Generated at %s\n", datetime.now(UTC).isoformat())
        log.info("uvh5 file: %s", self.uv_filename)
        log.info("config yaml: %s", self.config_yaml)
        log.info("output PNG: %s\n", self.save_path)
        log.info(
            "LST range: %0.3f - %0.3f hours",
            self.lsts_hours[0],
            self.lsts_hours[-1],
        )
        log.info(
            "Time step: %0.3f sec",
            (self.lsts_hours[1] - self.lsts_hours[0]) * 3600.0,
        )
        log.info(
            "Freq range: %0.1f - %0.1f MHz\n",
            self.freq_array[0] / 1e6,
            self.freq_array[-1] / 1e6,
        )

        log.info(
            "Fitting for %s at central frequency\n",
            self.simulation_config.beam_shape,
        )
        self.results["beam_shape"] = self.simulation_config.beam_shape

        f_mid_idx = self.freq_array.shape[0] // 2
        mid_freq = self.freq_array[f_mid_idx]

        if self.simulation_config.beam_shape == "GaussianBeam":
            self.results["beam_fwhm_deg"] = self.fit_vs_freq[f_mid_idx]
            self.results["beam_sigma_deg"] = self.fit_vs_freq[f_mid_idx] / (
                2 * numpy.sqrt(2 * numpy.log(2))
            )
            log.info(
                "   Gaussian at %0.1f MHz: FWHM = %0.3f deg; sigma = %0.3f deg",
                mid_freq / 1e6,
                self.results["beam_fwhm_deg"],
                self.results["beam_sigma_deg"],
            )

            if self.simulation_config.beam_sigma is not None:
                beam_sigma_deg = self.simulation_config.beam_sigma.deg
                self.results["expected_fwhm_deg"] = (
                    2 * numpy.sqrt(numpy.log(2)) * beam_sigma_deg
                )
                self.results["expected_sigma_deg"] = (
                    beam_sigma_deg / numpy.sqrt(2)
                )

                log.info(
                    "   Expected Gauss FWHM = %0.3f deg; sigma = %0.3f deg",
                    self.results["expected_fwhm_deg"],
                    self.results["expected_sigma_deg"],
                )

        if self.simulation_config.beam_shape == "AiryBeam":
            self.results["dish_diameter"] = self.fit_vs_freq[f_mid_idx]
            log.info(
                "   Airy at %0.1f MHz: Diameter = %0.3f m",
                mid_freq / 1e6,
                self.results["dish_diameter"],
            )
            if self.simulation_config.diameter is not None:
                self.results["expected_diameter"] = (
                    self.simulation_config.diameter.value
                )
                log.info(
                    "   Expected diameter = %s m",
                    self.results["expected_diameter"],
                )

        self.results["fit_spread"] = numpy.nanstd(self.fit_vs_freq)
        log.info(
            "   Fit-parameter scatter over frequency: %.4f",
            self.results["fit_spread"],
        )
        if numpy.any(~numpy.isnan(self.chi2_vs_freq)):
            log.info(
                "   mean χ²: %.3g (%.3g)\n",
                numpy.nanmean(self.chi2_vs_freq),
                numpy.nanstd(self.chi2_vs_freq),
            )

        if "correlation" in self.results["chromaticity"].keys():
            log.info("Relative variation with frequency:\n")
            log.info(
                "   Fractional scatter across frequency band = %.3f %%",
                100 * self.results["chromaticity"]["freq_std"],
            )
            log.info(
                "   Fractional linear trend within frequency band = %.3f %%",
                100 * self.results["chromaticity"]["freq_grad"],
            )
            log.info(
                "   Fractional residual after removing linear trend = %.3f %%\n",
                100 * self.results["chromaticity"]["frac_resid"],
            )
            corr = self.results["chromaticity"]["correlation"]
            if numpy.isnan(corr):
                log.info(
                    "   Correlation with 1/frequency could not be determined"
                )
            elif corr > 0.95:
                log.info(
                    "   Frequency variation is strongly correlated with 1/frequency (r=%.3f)",
                    corr,
                )
            else:
                log.info(
                    "   Not a strong correlation with 1/frequency (r=%.3f)",
                    corr,
                )

        return self.results

    def prepare_uv_data(self, uvd: UVData):
        """Resize and prepare UV data"""

        # Select autocorrelations only
        uv_auto = uvd.select(ant_str="auto", inplace=False)
        # Reorder so time is the fastest grouping
        # (i.e [t0 bl0,t0 bl1,t0 bl2....] )
        uv_auto.reorder_blts(order="time")

        # --- Find time and baseline structure
        unique_times, counts = numpy.unique(
            uv_auto.time_array, return_counts=True
        )

        self.baseline_counts = counts

        # Get LST for each time
        lsts_per_time = numpy.zeros(counts.size)
        start = 0
        for i, count in enumerate(counts):
            lsts_per_time[i] = uv_auto.lst_array[start]
            start += count

        lsts_unwrapped = numpy.unwrap(lsts_per_time, period=2 * numpy.pi)
        self.lsts_hours = lsts_unwrapped * 12.0 / numpy.pi

        # Check that number of baselines is constant with time
        if not numpy.all(counts == counts[0]):
            raise ValueError(
                "Baselines per time are not constant — cannot reshape safely."
            )

        # --- Reshape directly: (n_times, n_bls, n_freq, n_pol)
        self.freq_array = numpy.squeeze(uv_auto.freq_array)

        n_times = unique_times.size
        n_bls = counts[0]
        n_freq = self.freq_array.shape[0]

        data = uv_auto.data_array.reshape(n_times, n_bls, n_freq, -1)

        # --- Extract XX and YY polarisations
        data_xx = data[..., 0]
        data_yy = data[..., 1]

        # --- Stokes I (pyuvsim convention)
        stokes_I = data_xx + data_yy
        # print(f"Stokes I shape: {stokes_I.shape}")

        # Average over baselines (axis=1) to get power
        self.v_auto = numpy.nanmean(stokes_I, axis=1)  # shape: (Ntimes, Nfreq)

        # Mid-frequency baseline amplitudes
        f_mid_idx = n_freq // 2
        self.v_time_bl = numpy.abs(
            stokes_I[:, :, f_mid_idx]
        )  # (Ntimes, Nbls_per_time)

        # Hour angle calculated from LST relative to source RA
        hour_angle_hours = (
            self.lsts_hours - self.simulation_config.source_ra.hour[0]
        )
        hour_angle_hours = (hour_angle_hours + 12) % 24 - 12
        hour_angle_rad = numpy.deg2rad(hour_angle_hours * 15)

        # Convert to real angle on the sky
        lat = self.simulation_config.latitude.rad
        cos_theta = numpy.sin(lat) ** 2 + numpy.cos(lat) ** 2 * numpy.cos(
            hour_angle_rad
        )

        # Get the sign correct so that it measures angle around mean LST
        self.theta_deg = numpy.sign(hour_angle_hours) * numpy.rad2deg(
            numpy.arccos(cos_theta)
        )

    def compute_beam_metrics(self):
        """Compute beam metrics"""

        # Beam width at every frequency
        (
            self.fit_vs_freq,
            self.chi2_vs_freq,
            self.gauss_result,
            self.airy_result,
        ) = fit_beam_width_vs_frequency(
            self.freq_array,
            self.theta_deg,
            numpy.abs(self.v_auto),
            self.simulation_config.beam_shape,
        )

        # Chromaticity
        self.results["chromaticity"] = chromaticity_test(
            self.freq_array, self.fit_vs_freq
        )

    def make_plots(
        self,
        save_path: str | Path | None = None,
        show: bool = True,
        beam_ylog: bool = False,
    ):
        """Create diagnostic plots"""

        f_mid_idx = self.freq_array.shape[0] // 2
        mid_freq = self.freq_array[f_mid_idx]

        # Plot figure
        fig, ax = plt.subplots(2, 2, figsize=(10, 7))
        fig.suptitle(
            f"Simulation check: {numpy.abs(self.v_auto.max()):0.1f} "
            "Jy point source transiting zenith",
            fontsize=16,
        )

        # Heatmap of Amplitude at angle vs Baseline Index
        plot_baseline_heatmap(
            ax[0, 0],
            numpy.abs(self.v_time_bl),
            self.baseline_counts,
            self.lsts_hours,
            self.theta_deg,
            mid_freq,
        )

        plot_beam_shape(
            ax[0, 1],
            self.theta_deg,
            numpy.abs(self.v_auto[:, f_mid_idx]),
            mid_freq,
            self.gauss_result,
            self.airy_result,
            ylog=beam_ylog,
        )

        if self.gauss_result is not None:
            y_label = "FWHM (deg)"
            plot_title = "Beam width vs frequency"
            plot_text = f"FWHM at {mid_freq / 1e6:0.1f} MHz: {self.fit_vs_freq[f_mid_idx]:0.2f} deg"
        elif self.airy_result is not None:
            y_label = "Telescope diameter (m)"
            plot_title = "Diameter vs frequency"
            plot_text = f"Diameter at {mid_freq / 1e6:0.1f} MHz: {self.fit_vs_freq[f_mid_idx]:0.2f} m"
        else:
            raise RuntimeError("No beam fit available.")

        plot_spectrum(
            ax[1, 0],
            self.freq_array / 1e6,
            self.fit_vs_freq,
            y_label,
            plot_title,
        )

        ax[1, 0].text(
            0.4,
            0.8,
            plot_text,
            transform=ax[1, 0].transAxes,
            fontsize=10,
            verticalalignment="top",
            bbox=dict(boxstyle="round", facecolor="white", alpha=0.7),
        )

        plot_waterfall_matplotlib(
            ax[1, 1],
            self.v_auto,
            self.freq_array,
            self.lsts_hours,
            self.theta_deg,
        )

        plt.tight_layout()
        if save_path is not None:
            self.save_path = Path(save_path)
            save_path.parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(self.save_path, dpi=200, bbox_inches="tight")
        if show:
            plt.show()
        else:
            plt.close(fig)

        return fig


def fit_beam_width_vs_frequency(
    freq: numpy.typing.NDArray,
    theta_deg: numpy.typing.NDArray,
    v_auto: numpy.typing.NDArray,
    shape: str,
) -> tuple[
    numpy.typing.NDArray,
    numpy.typing.NDArray,
    lmfit.model.ModelResult | None,
    lmfit.model.ModelResult | None,
]:
    """
    Fit beam shape vs frequency using lmfit.

    Parameters
    ----------
    freq :
        Frequency in Hz
    theta_deg :
        Angular coordinate in degrees.
    v_auto :
        Visibility data with shape (angle, frequency).
    shape :
        Either "GaussianBeam" or "AiryBeam".

    Returns
    -------
    fit_vs_freq :
        Gaussian FWHM values at each frequency.
    gauss_result :
        Gaussian result at middle frequency.
    airy_result :
        Airy result at middle frequency.
    """

    n_f = freq.shape[0]
    f_mid_idx = n_f // 2

    fit_vs_freq = numpy.full(n_f, numpy.nan)
    chi2_vs_freq = numpy.full(n_f, numpy.nan)

    gauss_result_mid = None
    airy_result_mid = None

    # lmfit models
    gaussian_model = lmfit.models.GaussianModel(prefix="g_")
    airy_model = lmfit.Model(_airy, independent_vars=["theta", "freq_hz"])

    for freq_idx in range(n_f):
        # Gaussian fit
        if shape == "GaussianBeam":
            try:
                # Restrict fit to main lobe
                mask = numpy.abs(v_auto[:, freq_idx]) > 0.2
                theta_fit = theta_deg[mask]
                data_fit = numpy.abs(v_auto[:, freq_idx][mask])
                if len(theta_fit) == 0:
                    continue

                peak = numpy.nanmax(data_fit)
                params = gaussian_model.make_params(
                    g_amplitude=peak,
                    g_center=0.0,
                    g_sigma=3.0,
                )
                params["g_sigma"].min = 0

                result = gaussian_model.fit(
                    data_fit,
                    params,
                    x=theta_fit,
                )

                fit_vs_freq[freq_idx] = result.params["g_fwhm"].value
                chi2_vs_freq[freq_idx] = result.redchi

                if freq_idx == f_mid_idx:
                    gauss_result_mid = result

            except Exception as e:
                log.info("Gaussian fit failed at freq %s: %s", freq_idx, e)

        # Airy fit
        elif shape == "AiryBeam":
            try:
                params = airy_model.make_params(
                    A=1.0,
                    theta0=0.0,
                    diam=12.0,
                )
                params["A"].set(min=0.9, max=1.1)
                params["theta0"].set(
                    min=numpy.radians(-1), max=numpy.radians(1)
                )
                params["diam"].set(min=1, max=25)

                result = airy_model.fit(
                    v_auto[:, freq_idx],
                    params,
                    theta=numpy.radians(theta_deg),
                    freq_hz=freq[freq_idx],
                )

                fit_vs_freq[freq_idx] = result.params["diam"].value
                chi2_vs_freq[freq_idx] = result.redchi

                if freq_idx == f_mid_idx:
                    airy_result_mid = result

            except Exception as e:
                log.info("Airy fit failed at freq %s: %s", freq_idx, e)

        else:
            raise ValueError(
                "Shape must be either 'GaussianBeam' or 'AiryBeam'"
            )

    return fit_vs_freq, chi2_vs_freq, gauss_result_mid, airy_result_mid


def chromaticity_test(
    freq_array: numpy.typing.NDArray, test_param: numpy.typing.NDArray
) -> dict:
    """
    Test the variation of a parameter with frequency.

    Parameters
    ----------
    freq_array :
        Frequency array.
    test_param :
        The parameter to test against frequency.
    """

    chromaticity = {}

    inv_freq = 1 / freq_array
    valid = ~numpy.isnan(test_param)
    bandwidth = freq_array.max() - freq_array.min()

    # Measure variation across frequency band
    if numpy.sum(valid) > 1:
        freq_std = numpy.std(test_param[valid]) / numpy.mean(test_param[valid])
        p = numpy.polyfit(
            freq_array[valid], numpy.abs(test_param[valid]), deg=1
        )
        freq_grad = p[0] * bandwidth / numpy.mean(test_param[valid])
        trend = numpy.polyval(p, freq_array[valid])
        residual = test_param[valid] - trend
        frac_resid = numpy.std(residual) / numpy.mean(test_param[valid])
    else:
        freq_std = 0.0
        freq_grad = 0.0
        frac_resid = 0.0

    # Correlation to frequency
    if numpy.sum(valid) > CORR_SAMPLES and not numpy.isclose(
        numpy.std(test_param[valid]), 0.0
    ):
        corr = numpy.corrcoef(test_param[valid], inv_freq[valid])[0, 1]
    else:
        corr = numpy.nan

    chromaticity["freq_std"] = freq_std
    chromaticity["freq_grad"] = freq_grad
    chromaticity["frac_resid"] = frac_resid
    chromaticity["correlation"] = corr

    return chromaticity


def plot_beam_shape(
    ax: matplotlib.axes.Axes,
    theta_deg: numpy.typing.NDArray,
    ydata: numpy.typing.NDArray,
    freq: float,
    gauss_result: lmfit.model.ModelResult | None = None,
    airy_result: lmfit.model.ModelResult | None = None,
    ylog: bool = False,
) -> list[matplotlib.lines.Line2D]:
    """
    Plot the beam shape (normalized response) along with Gaussian
    and Airy fits.

    Parameters
    ----------
    ax :
        The axes on which to plot the data.
    theta_deg :
        The angle array.
    ydata :
        The data to plot.
    gauss_result :
        Result from the Gaussian fit.
    airy_result :
        Result from the Airy fit.
    ylog :
        Boolean - if True, plot y-axis with log scale
    """
    x_fine = numpy.linspace(theta_deg.min(), theta_deg.max(), 200)

    lines = ax.plot(theta_deg, ydata, "xk", label="Beam data")

    if gauss_result is not None:
        gauss_fit = gauss_result.eval(x=x_fine)
        ax.plot(x_fine, gauss_fit, "-", label="Gaussian fit")

    if airy_result is not None:
        airy_fit = airy_result.eval(theta=numpy.radians(x_fine), freq_hz=freq)
        ax.plot(x_fine, airy_fit, "--", label="Airy fit")

    if ylog is True:
        ax.set_yscale("log")

    ax.set_xlabel("Angle (deg)")
    ax.set_ylabel("Stokes I (XX+YY) Amplitude (Jy)")
    ax.set_title(f"Autocorrelation beam profile ({freq / 1e6:0.1f} MHz)")

    ax.legend()

    return lines


def plot_spectrum(
    ax: matplotlib.axes.Axes,
    freq_array: numpy.typing.NDArray,
    parameter: numpy.typing.NDArray,
    ylabel: str,
    title: str,
) -> list[matplotlib.lines.Line2D]:
    """Plot spectrum"""

    lines = ax.plot(freq_array, parameter, "o")
    ax.set_xlabel("Frequency (MHz)")
    ax.set_ylabel(ylabel)
    ax.set_title(title)

    # --- find closest data point
    idx = freq_array.shape[-1] // 2
    mid_y = parameter[idx]

    # --- draw horizontal line
    ax.axhline(mid_y, color="red", linestyle="--", linewidth=1)
    ax.axvline(freq_array[idx], color="red", linestyle="--", linewidth=1)

    return lines


def lst_formatter(x: float, pos: int) -> str:
    """Format LST in hours, wrapped to [0, 24)."""
    return f"{x % 24:.0f}"


def plot_waterfall_matplotlib(
    ax: matplotlib.axes.Axes,
    data: numpy.typing.NDArray[numpy.floating | numpy.complexfloating],
    freqs: numpy.typing.NDArray[numpy.floating],
    lsts_hours: numpy.typing.NDArray[numpy.floating],
    theta_deg: numpy.typing.NDArray[numpy.floating],
    cmap: str = "viridis",
) -> matplotlib.axes.Axes:
    """
    Create a waterfall plot (frequency vs LST).
    """

    # --- safety checks
    if data.shape[0] != len(lsts_hours):
        raise ValueError("Mismatch between data time axis and lsts_hours")
    if data.shape[1] != len(freqs):
        raise ValueError("Mismatch between data frequency axis and freqs")

    # --- physical axis mapping
    extent = (
        freqs.min() / 1e6,  # MHz
        freqs.max() / 1e6,
        lsts_hours.min(),
        lsts_hours.max(),
    )

    plot_2d_lst_deg(ax, data, extent, lsts_hours, theta_deg, cmap=cmap)

    ax.set_xlabel("Frequency (MHz)")
    ax.set_ylabel("LST (hours)")
    ax.set_title("Waterfall Plot")

    return ax


def plot_baseline_heatmap(
    ax: matplotlib.axes.Axes,
    data: numpy.typing.NDArray[numpy.floating | numpy.complexfloating],
    bl_counts: numpy.typing.NDArray[numpy.integer],
    lsts_hours: numpy.typing.NDArray[numpy.floating],
    theta_deg: numpy.typing.NDArray[numpy.floating],
    freq: float,
    cmap: str = "viridis",
) -> matplotlib.axes.Axes:
    """
    Baseline vs angle heatmap with axes:
    - Left: LST (hours)
    - Right: Angle (deg)
    - External colorbar
    """

    if ax is None:
        _, ax = plt.subplots(figsize=(6, 4))

    n_baselines = bl_counts.max()
    extent = (
        -0.5,
        n_baselines - 0.5,
        lsts_hours.min(),
        lsts_hours.max(),
    )

    plot_2d_lst_deg(ax, data, extent, lsts_hours, theta_deg, cmap=cmap)

    ax.set_xlabel("Baseline index")
    ax.set_ylabel("LST (hours)")
    ax.set_title(f"Autocorr per baseline at {freq / 1e6:0.1f} MHz")

    if n_baselines <= 10:
        major_tick_step = 1
    elif n_baselines <= 20:
        major_tick_step = 2
    elif n_baselines <= 50:
        major_tick_step = 5
    elif n_baselines <= 100:
        major_tick_step = 10
    else:
        major_tick_step = 20

    ax.xaxis.set_major_locator(MultipleLocator(major_tick_step))
    ax.xaxis.set_minor_locator(MultipleLocator(1))

    return ax


def plot_2d_lst_deg(
    ax: matplotlib.axes.Axes,
    data: numpy.typing.NDArray[numpy.floating | numpy.complexfloating],
    extent: tuple[float, float, float, float],
    lsts_hours: numpy.typing.NDArray[numpy.floating],
    theta_deg: numpy.typing.NDArray[numpy.floating],
    cmap: str = "viridis",
) -> matplotlib.axes.Axes:
    """
    Plot a 2D image with:
    - Left y-axis: LST (hours)
    - Right y-axis: angular separation (degrees)
    """

    im = ax.imshow(
        numpy.abs(data),
        origin="lower",
        aspect="auto",
        extent=extent,
        cmap=cmap,
        interpolation="none",
        resample=False,
    )

    ax.yaxis.set_major_formatter(FuncFormatter(lst_formatter))
    ax.yaxis.set_major_locator(MultipleLocator(1))

    ax.tick_params(
        axis="y",
        direction="out",
        length=3,
        pad=2,
    )

    # --- secondary axis with linear transform ---
    a, b = numpy.polyfit(lsts_hours, theta_deg, 1)

    secax = ax.secondary_yaxis(
        "right", functions=(lambda x: a * x + b, lambda x: (x - b) / a)
    )

    secax.set_ylabel("Anglular Separation (deg)", labelpad=0)
    secax.yaxis.set_major_locator(MultipleLocator(10))

    secax.tick_params(
        axis="y",
        direction="out",
        length=3,
        pad=2,
    )

    cbar = plt.colorbar(im, ax=ax, pad=0.16)
    vmin, vmax = im.get_clim()
    ticks = numpy.round(numpy.linspace(vmin, vmax, 6), decimals=2).tolist()
    cbar.set_ticks(ticks)
    cbar.ax.set_title("Stokes I", fontsize=8)

    return ax


def main():
    parser = argparse.ArgumentParser(
        description="Run beam diagnostics on a pyuvsim simulation."
    )
    parser.add_argument("uvh5", help="Path to the simulated uvh5 file.")
    parser.add_argument(
        "simulation_config",
        help="Simulation configuration used to generate the simulation.",
    )
    parser.add_argument(
        "--template-dir",
        default=None,
        help="Template directory for config files (default: %(default)s).",
    )
    parser.add_argument(
        "--log-suffix",
        default=".beamcheck.log",
        help="Suffix for the beam check log file (default: %(default)s).",
    )

    parser.add_argument(
        "--fig-suffix",
        default=".beamcheck.png",
        help="Suffix for the beam check figure (default: %(default)s).",
    )
    args = parser.parse_args()

    uvh5 = Path(args.uvh5)
    config_yaml = Path(args.simulation_config)

    template_dir = args.template_dir
    if template_dir is not None:
        template_dir = Path(template_dir)

    # Check uvh5 file exists
    if not uvh5.exists():
        raise FileNotFoundError(f"No such file or directory: {args.uvh5}")

    # Write log and plot into uvh5 directory
    handlers = [logging.StreamHandler()]
    handlers.append(logging.FileHandler(uvh5.with_suffix(args.log_suffix)))
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        handlers=handlers,
    )

    fig_save_path = uvh5.with_suffix(args.fig_suffix)

    bm = BeamMetrics(uvh5, config_yaml, template_dir=template_dir)

    bm.check_beam(save_path=fig_save_path, show=False, beam_ylog=False)


if __name__ == "__main__":
    main()
