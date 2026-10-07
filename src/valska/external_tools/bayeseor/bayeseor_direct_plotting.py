"""Plotting that delegates directly to BayesEoR's ``DataContainer``.

This module wraps :class:`bayeseor.analyze.analyze.DataContainer`, so BayesEoR
itself reads the chains, computes the posterior summaries and renders the
figures. For ValSKA's own reader, posterior calculations and renderer for
BayesEoR outputs, see
:mod:`valska.external_tools.bayeseor.valska_bayeseor_plotting`.
"""

from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np

# from anesthetic import read_chains
from bayeseor.analyze.analyze import DataContainer
from matplotlib.figure import Figure

from valska.constants import (
    DEFAULT_EOR_POWER_MK2_MPC3,
    DEFAULT_NOISE_TO_EOR_POWER_RATIO,
)
from valska.utils import get_default_path_manager, load_paths

__all__ = ["BeamAnalysisPlotter", "plot_gleam_analysis", "plot_gsm_comparison"]


class BeamAnalysisPlotter:
    """
    Plot beam-analysis results for HERA-focused workflows within ValSKA.
    """

    def __init__(  # noqa: PLR0913
        self,
        base_chains_dir: str | Path | None = None,
        paths_file: str | Path | None = None,
        paths: dict[str, str] | None = None,
        eor_ps: float = DEFAULT_EOR_POWER_MK2_MPC3,
        noise_ratio: float = DEFAULT_NOISE_TO_EOR_POWER_RATIO,
        default_expected_ps: float | None = None,
    ):
        """Initialize the plotter with a base directory for chains.

        Parameters
        ----------
        base_chains_dir : str or Path, optional
            Base directory for chains. If None, uses the default BayesEoR path
        paths_file : str or Path, optional
            YAML file containing analysis paths. If None, uses the default
            paths file.
        paths : Dict[str, str], optional
            Dictionary of analysis paths relative to base_chains_dir. If None,
            uses default paths.
        eor_ps : float, optional
            EoR power spectrum value in mK^2 Mpc^3.
            Defaults to ``DEFAULT_EOR_POWER_MK2_MPC3``.
        noise_ratio : float, optional
            Ratio of noise PS to EoR PS. Defaults to
            ``DEFAULT_NOISE_TO_EOR_POWER_RATIO``.
        default_expected_ps : float, optional
            Default expected power spectrum to use in plots.
            If None, uses noise_ps.
        """
        if base_chains_dir is None:
            self.dir_prefix = Path(get_default_path_manager().chains_dir)
        else:
            self.dir_prefix = Path(base_chains_dir)

        # Backwards-compatibility: some callers/tests expect attribute
        # `base_chains_dir`. Expose it as an alias to dir_prefix.
        self.base_chains_dir = self.dir_prefix

        # Define paths to different analysis directories
        # Load paths from file if not provided directly
        if paths is None:
            self.paths = load_paths(paths_file)
        else:
            self.paths = paths

        # Default values
        self.eor_ps = eor_ps  # mK^2 Mpc^3
        self.noise_ps = self.eor_ps * noise_ratio  # mK^2 Mpc^3
        # Set default expected PS value (if not provided, use noise_ps)
        self.default_expected_ps = (
            default_expected_ps
            if default_expected_ps is not None
            else self.noise_ps
        )

    def add_analysis_path(self, key: str, path: str) -> None:
        """Add a new analysis path to the plotter.

        Parameters
        ----------
        key : str
            Key for the analysis path
        path : str
            Path to the analysis directory, relative to base_chains_dir
        """
        self.paths[key] = path

    def get_data_container(
        self,
        analysis_keys: list[str],
        labels: list[str] | None = None,
        expected_ps: float | None = None,
        **kwargs,
    ) -> DataContainer:
        """Create a DataContainer for the specified analyses.

        Parameters
        ----------
        analysis_keys : list of str
            Keys for analyses to plot from self.paths
        labels : list of str, optional
            Labels for each analysis. If None, uses analysis_keys
        expected_ps : float, optional
            Expected power spectrum value.
            If None, uses self.default_expected_ps
        ``**kwargs`` : dict
            Additional arguments to pass to DataContainer

        Returns
        -------
        data : DataContainer
            DataContainer for the specified analyses
        """
        dirnames = [self.paths[key] for key in analysis_keys]
        if labels is None:
            labels = analysis_keys

        if expected_ps is None:
            expected_ps = self.default_expected_ps

        return DataContainer(
            dirnames,
            dir_prefix=self.dir_prefix,
            expected_ps=expected_ps,
            labels=labels,
            **kwargs,
        )

    def plot_analysis_results(  # noqa: PLR0912,PLR0913
        self,
        analysis_keys: list[str],
        labels: list[str] | None = None,
        suptitle: str = "UKSRC validation: Burba et al. 2023",
        expected_ps: float | None = None,
        expected_label: str = "Noise level",
        upper_limit_indices: list[int] | None = None,
        detection_indices: dict[str, list[int]] | None = None,
        ignore_uplims: bool = False,
        plot_fracdiff: bool = True,
        plot_priors: bool = True,
        ls_expected: str = ":",
        figsize: tuple[float, float] | None = None,
        data_container_kwargs: dict[str, Any] | None = None,
        plot_kwargs: dict[str, Any] | None = None,
    ) -> Figure:
        """
        Plot power spectra and posteriors for selected analyses.

        Parameters
        ----------
        analysis_keys : list of str
            Keys for analyses to plot from self.paths
        labels : list of str, optional
            Labels for each analysis. If None, uses analysis_keys
        suptitle : str, optional
            Super title for the plot
        expected_ps : float, optional
            Expected power spectrum value. If None, uses
            self.default_expected_ps
        labels : str, optional
            Label for the expected PS line
        upper_limit_indices : list of int, optional
            Indices of k-modes to treat as upper limits for ALL analyses.
            If None, assume no upper limits.
        detection_indices : dict, optional
            Dictionary mapping analysis keys to lists of k-mode indices that
            should be treated as detections rather than upper limits. This
            overrides upper_limit_indices for specific analyses.
        ignore_uplims : bool, optional
            Whether to ignore upper limits entirely
        plot_fracdiff : bool, optional
            Whether to plot fractional differences
        plot_priors : bool, optional
            Whether to plot priors
        ls_expected : str, optional
            Line style for expected PS
        figsize : tuple of float, optional
            Figure size in inches (width, height)
        data_container_kwargs : dict, optional
            Additional arguments to pass to DataContainer
        plot_kwargs : dict, optional
            Additional arguments to pass to plot_power_spectra_and_posteriors

        Returns
        -------
        fig : matplotlib.figure.Figure
            The resulting figure
        """
        # Set up data container with optional kwargs
        dc_kwargs = data_container_kwargs or {}
        data = self.get_data_container(
            analysis_keys=analysis_keys,
            labels=labels,
            expected_ps=expected_ps,
            **dc_kwargs,
        )

        # Store original labels for legend fix later
        original_labels = labels if labels is not None else analysis_keys

        # Set up upper limits
        uplim_inds = None
        if not ignore_uplims:
            n_dim = len(data.k_vals[0])
            # Default to first k-mode only if not specified
            indices_to_use = (
                upper_limit_indices if upper_limit_indices is not None else [0]
            )

            # Create boolean array for each analysis
            uplim_inds_list = []
            for i, key in enumerate(analysis_keys):
                # Start with all False
                uplim_ind = np.zeros(n_dim, dtype=bool)

                # Set True for specified indices
                for idx in indices_to_use:
                    if 0 <= idx < n_dim:
                        uplim_ind[idx] = True

                # Override with detection indices if specified for this
                # analysis
                if detection_indices is not None and key in detection_indices:
                    for idx in detection_indices[key]:
                        if 0 <= idx < n_dim:
                            uplim_ind[idx] = False

                uplim_inds_list.append(uplim_ind)

            uplim_inds = np.array(uplim_inds_list)

        # Create and return plot with optional kwargs
        plot_args = {
            "suptitle": suptitle,
            "plot_fracdiff": plot_fracdiff,
            "uplim_inds": uplim_inds,
            "plot_priors": plot_priors,
            "ls_expected": ls_expected,
            "labels": labels,
            "legend_ncols": 6,
        }

        # Add custom figsize if provided
        if figsize:
            # plot_args["figsize"] = figsize
            plot_args["plot_width"] = int(figsize[0] / 2)

        # Add any additional plot kwargs
        if plot_kwargs:
            plot_args.update(plot_kwargs)

        # Create the plot
        fig = data.plot_power_spectra_and_posteriors(**plot_args)

        # Fix legend labels
        for ax in fig.axes:
            legend = ax.get_legend()
            if legend is not None:
                # Get all the line handles and texts
                handles = getattr(legend, "legendHandles", None)
                if handles is None:
                    handles = getattr(legend, "legend_handles", None)
                if handles is None:
                    handles, _ = ax.get_legend_handles_labels()
                texts = legend.get_texts()

                # Create a mapping of single letter labels to full labels
                letter_to_label = {}
                for i, label in enumerate(original_labels):
                    # Maximum of 26 letters in alphabet
                    if i < 26:  # noqa: PLR2004
                        letter = chr(ord("A") + i)
                        letter_to_label[letter] = label

                # Replace single-letter texts with full labels
                for i, text in enumerate(texts):
                    current_text = text.get_text()
                    if (
                        len(current_text) == 1
                        and current_text in letter_to_label
                    ):
                        text.set_text(letter_to_label[current_text])
                    elif current_text == "Expected":
                        text.set_text(expected_label)

                # Calculate optimal number of columns for the legend
                # For fewer than 4 items, keep them in one row
                # Otherwise, aim for roughly square arrangement
                n_items = len(handles)
                if n_items <= 3:  # noqa: PLR2004
                    ncol = n_items
                else:
                    # Calculate a reasonable number of columns
                    # (sqrt of n_items, rounded)
                    # This creates a roughly square legend
                    ncol = min(
                        int(np.sqrt(n_items) + 0.5), 4
                    )  # Cap at 4 columns max

                # Create a new legend with the updated texts and multiple columns
                legend_loc = getattr(legend, "_loc", None)
                legend_fontsize = getattr(legend, "_fontsize", None)
                ax.legend(
                    handles=handles,
                    labels=[text.get_text() for text in texts],
                    loc=legend_loc,
                    fontsize=legend_fontsize,
                    ncol=ncol,  # Use multiple columns
                    frameon=True,  # Add a frame around the legend
                    framealpha=0.8,  # Make the frame slightly transparent
                )

        return fig

    # Update create_comparison_plot to pass through the detection_indices
    # parameter
    def create_comparison_plot(
        self,
        groups: dict[str, list[str]],
        group_labels: dict[str, str] | None = None,
        suptitle: str = "HERA FWHM Sensitivity Analysis",
        **kwargs,
    ) -> Figure:
        """
        Create a comparison plot for different analysis groups.

        Parameters
        ----------
        groups : dict of str: list of str
            Dictionary mapping group names to lists of analysis keys
        group_labels : dict of str: str, optional
            Dictionary mapping group names to display labels
        suptitle : str, optional
            Super title for the plot
        ``**kwargs`` : dict
            Additional arguments to pass to plot_analysis_results

        Returns
        -------
        fig : matplotlib.figure.Figure
            The resulting figure
        """
        all_keys = []
        all_labels = []

        for group, keys in groups.items():
            all_keys.extend(keys)

            # Use custom group labels if provided
            group_label = group
            if group_labels and group in group_labels:
                group_label = group_labels[group]

            # Create labels that include the group
            if len(keys) == 1:
                all_labels.append(group_label)
            else:
                all_labels.extend([f"{group_label} - {key}" for key in keys])

        # Pass all arguments to plot_analysis_results
        return self.plot_analysis_results(
            analysis_keys=all_keys,
            labels=all_labels,
            suptitle=suptitle,
            **kwargs,
        )


# Example usage functions
def plot_gleam_analysis(
    base_chains_dir: str | Path | None = None,
) -> Figure:
    """Example function that reproduces the GLEAM analysis plot.

    Parameters
    ----------
    base_chains_dir : str or Path, optional
        Base directory for chains. If None, uses the default BayesEoR path.

    Returns
    -------
    fig : matplotlib.figure.Figure
        The resulting figure
    """
    plotter = BeamAnalysisPlotter(base_chains_dir=base_chains_dir)
    fig = plotter.plot_analysis_results(
        analysis_keys=["GLEAM_FgEoR"],
        labels=["GLEAM"],
        suptitle=(
            "UKSRC validation: Burba et al. 2023, Case 1. \n"
            "12.9 deg. GLEAM Analysis."
        ),
    )
    return fig


def plot_gsm_comparison(
    base_chains_dir: str | Path | None = None,
) -> Figure:
    """Example function comparing different GSM perturbation levels.

    Parameters
    ----------
    base_chains_dir : str or Path, optional
        Base directory for chains. If None, uses the default BayesEoR path.

    Returns
    -------
    fig : matplotlib.figure.Figure
        The resulting figure
    """
    plotter = BeamAnalysisPlotter(base_chains_dir=base_chains_dir)

    # Compare different GSM perturbations
    fig = plotter.create_comparison_plot(
        groups={
            "-0.1% FWHM": ["GSM_FgEoR_-1e-1pp"],
            "-1% FWHM": ["GSM_FgEoR_-1e0pp"],
            "-5% FWHM": ["GSM_FgEoR_-5e0pp"],
        },
        suptitle="Impact of FWHM Perturbations on GSM Foreground Analysis",
    )
    return fig


if __name__ == "__main__":
    # This code runs when the script is executed directly
    figure = plot_gleam_analysis()
    plt.show()
