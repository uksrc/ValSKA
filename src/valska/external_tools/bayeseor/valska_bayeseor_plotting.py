"""ValSKA-owned plotting of BayesEoR outputs.

This module reads BayesEoR output directories, computes the posterior
summaries used for plotting and renders the figures within ValSKA. It does not
call BayesEoR's ``DataContainer``; for plotting delegated directly to
BayesEoR, see :mod:`valska.external_tools.bayeseor.bayeseor_direct_plotting`.

The chain-reading/statistics and default combined figure layout in this module
are derived from BayesEoR's BSD 3-Clause licensed
``bayeseor.analyze.analyze.DataContainer`` implementation. They are ported here
so ValSKA can own the plotting surface while preserving numerical parity with
BayesEoR analysis outputs.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import matplotlib.pyplot as plt
import numpy as np
import yaml  # type: ignore[import-untyped]
from matplotlib.colors import TwoSlopeNorm
from matplotlib.figure import Figure
from scipy import stats

from valska.constants import DEFAULT_NOISE_POWER_MK2_MPC3

__all__ = [
    "BayesEoRAnalysisOutputs",
    "BayesEoRChainSummary",
    "BayesEoRPlotConfig",
    "BayesEoRPlotDataConfig",
    "BayesEoRPlotFigureConfig",
    "BayesEoRPlotOutputConfig",
    "BayesEoRPlotStyleConfig",
    "dmps_to_ps",
    "load_bayeseor_analysis_outputs",
    "plot_bayeseor_power_spectra_and_posteriors",
    "ps_to_dmps",
    "weighted_quantiles",
]

Hypothesis = Literal["signal_fit", "no_signal"]
PriorMode = Literal["shared", "grouped", "per_chain", "off"]
ColorMode = Literal["perturbation", "cycle"]
UpperLimitMode = Literal["noise_proxy", "posterior_edge", "manual", "off"]
UpperLimitPlotMode = Literal["omit", "arrow"]

_TRAILING_FLOAT_RE = re.compile(
    r"(?P<prefix>.*?)[_-](?P<value>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?)$",
    re.IGNORECASE,
)
_PERTURBATION_LABELS = {
    "antdiam": "Diameter",
    "antenna_diameter": "Diameter",
    "fwhm": "FWHM",
}


@dataclass(frozen=True)
class BayesEoRPlotDataConfig:
    """Options controlling BayesEoR chain loading and posterior summaries."""

    hypotheses: tuple[Hypothesis, ...] = ("signal_fit",)
    sampler: str = "multinest"
    posterior_weighted: bool = True
    cred_intervals: tuple[int | float, ...] = (68, 95)
    cred_interval: int | float = 68
    calc_uplims: bool = True
    uplim_quantile: float = 0.95
    upper_limit_mode: UpperLimitMode = "noise_proxy"
    upper_limit_plot_mode: UpperLimitPlotMode = "omit"
    upper_limit_probability_threshold: float = 0.95
    detection_probability_threshold: float = 0.95
    upper_limit_indices: tuple[int, ...] | None = None
    detection_indices: dict[str, tuple[int, ...]] = field(default_factory=dict)
    ignore_uplims: bool = False
    nhistbins: int = 31
    density: bool = False
    calc_kurtosis: bool = False
    auto_uplim_peak_bin: int = 0
    ps_kind: Literal["ps", "dmps"] = "dmps"
    temp_unit: str = "mK"
    little_h_units: bool = False
    expected_ps: float | list[float] | None = DEFAULT_NOISE_POWER_MK2_MPC3
    expected_dmps: float | list[float] | None = None


@dataclass(frozen=True)
class BayesEoRPlotFigureConfig:
    """Options controlling the combined analysis figure layout."""

    suptitle: str | None = "Sweep signal fit chain comparison"
    plot_height_ps: float = 4.0
    plot_width: float = 7.0
    hspace_ps: float = 0.05
    height_ratios_ps: tuple[float, float] = (1.0, 0.5)
    plot_diff: bool = False
    plot_fracdiff: bool = True
    ylim_ps: tuple[float, float] | None = None
    ylim_diff_ps: tuple[float, float] | None = (-1.0, 1.0)
    plot_height_post: float = 1.0
    hspace_post: float = 0.01
    log_y: bool = False
    ymin_post: float = 1e-16
    show_k_vals: bool = True
    figlegend: bool = True
    legend_ncols: int = 6
    top: float = 0.875
    right_ps: float = 0.46
    left_post: float = 0.54


@dataclass(frozen=True)
class BayesEoRPlotStyleConfig:
    """Options controlling plotted marks and lines."""

    labels: list[str] | None = None
    colors: list[str] | None = None
    color_mode: ColorMode = "perturbation"
    cmap: str = "coolwarm"
    format_perturbation_labels: bool = True
    marker: str = "o"
    capsize: float = 3.0
    lw: float = 3.0
    ls_expected: str = ":"
    x_offset: float = 0.0
    zorder_offset: int = 0
    plot_priors: bool = True
    posterior_plot_priors: bool = True
    prior_mode: PriorMode = "shared"
    prior_alpha: float = 0.18
    posterior_prior_alpha: float = 0.10
    prior_color: str = "lightsteelblue"
    expected_label: str = "Noise level"


@dataclass(frozen=True)
class BayesEoRPlotOutputConfig:
    """Options controlling report output names."""

    filename_prefix: str = "plot_analysis_results"


@dataclass(frozen=True)
class BayesEoRPlotConfig:
    """Configuration for ValSKA-native BayesEoR analysis plots."""

    data: BayesEoRPlotDataConfig = field(
        default_factory=BayesEoRPlotDataConfig
    )
    figure: BayesEoRPlotFigureConfig = field(
        default_factory=BayesEoRPlotFigureConfig
    )
    style: BayesEoRPlotStyleConfig = field(
        default_factory=BayesEoRPlotStyleConfig
    )
    outputs: BayesEoRPlotOutputConfig = field(
        default_factory=BayesEoRPlotOutputConfig
    )

    @classmethod
    def from_yaml(cls, path: str | Path | None) -> BayesEoRPlotConfig:
        """Load plot configuration from a compact YAML file."""
        if path is None:
            return cls()
        with Path(path).expanduser().open(encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}
        if not isinstance(payload, dict):
            raise TypeError(
                "BayesEoR plot config YAML must contain a mapping."
            )
        return cls.from_mapping(payload)

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> BayesEoRPlotConfig:
        """Build plot configuration from a nested mapping."""
        data = dict(payload.get("data", {}) or {})
        figure = dict(payload.get("figure", {}) or {})
        style = dict(payload.get("style", {}) or {})
        outputs = dict(payload.get("outputs", {}) or {})

        if "hypothesis" in data and "hypotheses" not in data:
            data["hypotheses"] = data.pop("hypothesis")
        if "Nhistbins" in data and "nhistbins" not in data:
            data["nhistbins"] = data.pop("Nhistbins")
        if "height_ratios_ps" in figure:
            figure["height_ratios_ps"] = tuple(figure["height_ratios_ps"])
        if "ylim_ps" in figure and figure["ylim_ps"] is not None:
            figure["ylim_ps"] = tuple(figure["ylim_ps"])
        if "ylim_diff_ps" in figure and figure["ylim_diff_ps"] is not None:
            figure["ylim_diff_ps"] = tuple(figure["ylim_diff_ps"])
        if "cred_intervals" in data:
            data["cred_intervals"] = tuple(data["cred_intervals"])
        if (
            "upper_limit_indices" in data
            and data["upper_limit_indices"] is not None
        ):
            data["upper_limit_indices"] = tuple(data["upper_limit_indices"])
        if "upper_limit_mode" in data:
            data["upper_limit_mode"] = _normalise_upper_limit_mode(
                data["upper_limit_mode"]
            )
        if "detection_indices" in data:
            data["detection_indices"] = {
                str(key): tuple(value)
                for key, value in dict(data["detection_indices"]).items()
            }
        if "hypotheses" in data:
            data["hypotheses"] = _normalise_hypotheses(data["hypotheses"])
        if isinstance(style.get("prior_mode"), bool):
            style["prior_mode"] = "shared" if style["prior_mode"] else "off"
        if "prior_colour" in style:
            if "prior_color" not in style:
                style["prior_color"] = style["prior_colour"]
            style.pop("prior_colour")

        return cls(
            data=BayesEoRPlotDataConfig(**data),
            figure=BayesEoRPlotFigureConfig(**figure),
            style=BayesEoRPlotStyleConfig(**style),
            outputs=BayesEoRPlotOutputConfig(**outputs),
        )


@dataclass(frozen=True)
class BayesEoRChainSummary:
    """Loaded chain data and posterior summaries for one BayesEoR output."""

    path: Path
    label: str
    k_vals: np.ndarray
    k_vals_bins: np.ndarray
    version: str
    args: dict[str, Any]
    posteriors: np.ndarray
    posterior_bins: np.ndarray
    avgs: np.ndarray
    medians: np.ndarray
    cred_intervals: dict[int | float, dict[str, np.ndarray]]
    uplims: np.ndarray | None
    kurtoses: np.ndarray | None


@dataclass(frozen=True)
class BayesEoRAnalysisOutputs:
    """Collection of loaded BayesEoR analysis outputs ready for plotting."""

    chains: list[BayesEoRChainSummary]
    labels: list[str]
    ps_kind: Literal["ps", "dmps"]
    temp_unit: str
    little_h_units: bool
    expected_ps: list[np.ndarray] | None
    expected_dmps: list[np.ndarray] | None
    uplim_inds: list[np.ndarray]

    @property
    def k_vals_identical(self) -> bool:
        if len(self.chains) <= 1:
            return True
        shapes = {chain.k_vals.shape for chain in self.chains}
        if len(shapes) != 1:
            return False
        return bool(
            np.all(
                np.diff(np.array([c.k_vals for c in self.chains]), axis=0) == 0
            )
        )

    @property
    def has_expected(self) -> bool:
        return self.expected_ps is not None or self.expected_dmps is not None

    @property
    def k_units(self) -> str:
        return r"$h$ " * self.little_h_units + "Mpc$^{-1}$"

    @property
    def ps_label(self) -> str:
        return r"$P(k)$" if self.ps_kind == "ps" else r"$\Delta^2(k)$"

    @property
    def ps_units(self) -> str:
        return (
            f"{self.temp_unit}$^2$"
            + r" $h^{-3}$" * self.little_h_units
            + r" Mpc$^3$" * (self.ps_kind == "ps")
        )


def _normalise_hypotheses(raw: Any) -> tuple[Hypothesis, ...]:
    if raw == "both":
        return ("signal_fit", "no_signal")
    if isinstance(raw, str):
        values = (raw,)
    else:
        values = tuple(raw)
    allowed = {"signal_fit", "no_signal"}
    invalid = [value for value in values if value not in allowed]
    if invalid:
        raise ValueError(f"Unsupported hypothesis in plot config: {invalid}")
    return values  # type: ignore[return-value]


def _normalise_upper_limit_mode(raw: Any) -> UpperLimitMode:
    if isinstance(raw, bool):
        return "noise_proxy" if raw else "off"
    value = str(raw).lower()
    if value == "auto":
        value = "noise_proxy"
    if value in {"none", "false"}:
        value = "off"
    allowed = {"noise_proxy", "posterior_edge", "manual", "off"}
    if value not in allowed:
        raise ValueError(
            f"Unsupported upper_limit_mode in plot config: {raw!r}"
        )
    return value  # type: ignore[return-value]


def weighted_quantiles(
    data: np.ndarray,
    q: float,
    weights: np.ndarray | None = None,
) -> np.ndarray:
    """Compute BayesEoR-compatible column-wise weighted quantiles."""
    if q < 0 or q > 1:
        raise ValueError("q must be in [0, 1]")
    if data.ndim == 1:
        data = data.reshape(-1, 1)
    if weights is None:
        weights = np.ones(data.shape[0])
    else:
        shapes_okay = (
            weights.shape == data.shape or weights.shape == data[:, 0].shape
        )
        if not shapes_okay:
            raise ValueError(
                "weights must have the same shape as data or data[:, 0]"
            )
    quantiles = np.ones(data.shape[1], dtype=float)
    for i_col in range(data.shape[1]):
        sort_inds = np.argsort(data[:, i_col])
        sorted_data = data[:, i_col][sort_inds]
        sorted_weights = weights[sort_inds]
        cdf_w = np.cumsum(sorted_weights) / np.sum(sorted_weights)
        quantiles[i_col] = np.interp(q, cdf_w, sorted_data)
    return quantiles


def ps_to_dmps(ps: float | np.ndarray, ks: np.ndarray) -> np.ndarray:
    """Convert P(k) to Delta^2(k)."""
    return np.asarray(ps) * ks**3 / (2 * np.pi**2)


def dmps_to_ps(dmps: float | np.ndarray, ks: np.ndarray) -> np.ndarray:
    """Convert Delta^2(k) to P(k)."""
    return np.asarray(dmps) * 2 * np.pi**2 / ks**3


def load_bayeseor_analysis_outputs(
    chain_roots: Sequence[str | Path],
    *,
    labels: Sequence[str] | None = None,
    config: BayesEoRPlotConfig | None = None,
    dir_prefix: str | Path | None = None,
) -> BayesEoRAnalysisOutputs:
    """Load BayesEoR output directories into ValSKA-native plot data."""
    cfg = config or BayesEoRPlotConfig()
    data_cfg = cfg.data
    if labels is None:
        labels = [Path(path).name for path in chain_roots]
    if len(labels) != len(chain_roots):
        raise ValueError("labels must have the same length as chain_roots")

    root_prefix = (
        Path(dir_prefix).expanduser() if dir_prefix is not None else None
    )
    chains = [
        _load_one_chain(
            chain_root=Path(chain_root),
            label=str(label),
            dir_prefix=root_prefix,
            data_cfg=data_cfg,
        )
        for chain_root, label in zip(chain_roots, labels, strict=True)
    ]

    outputs_without_expected = BayesEoRAnalysisOutputs(
        chains=chains,
        labels=[str(label) for label in labels],
        ps_kind=data_cfg.ps_kind,
        temp_unit=data_cfg.temp_unit,
        little_h_units=data_cfg.little_h_units,
        expected_ps=None,
        expected_dmps=None,
        uplim_inds=[
            np.zeros(chain.k_vals.shape, dtype=bool) for chain in chains
        ],
    )
    expected_ps, expected_dmps = _calculate_expected_spectra(
        outputs_without_expected,
        data_cfg,
    )
    return BayesEoRAnalysisOutputs(
        chains=outputs_without_expected.chains,
        labels=outputs_without_expected.labels,
        ps_kind=outputs_without_expected.ps_kind,
        temp_unit=outputs_without_expected.temp_unit,
        little_h_units=outputs_without_expected.little_h_units,
        expected_ps=expected_ps,
        expected_dmps=expected_dmps,
        uplim_inds=_build_uplim_inds(
            chains,
            labels,
            data_cfg,
            ps_kind=outputs_without_expected.ps_kind,
            k_vals_identical=outputs_without_expected.k_vals_identical,
            expected_ps=expected_ps,
            expected_dmps=expected_dmps,
        ),
    )


def _load_one_chain(
    *,
    chain_root: Path,
    label: str,
    dir_prefix: Path | None,
    data_cfg: BayesEoRPlotDataConfig,
) -> BayesEoRChainSummary:
    path = chain_root if dir_prefix is None else dir_prefix / chain_root
    path = path.expanduser().resolve()
    sampler = data_cfg.sampler.lower()
    if sampler != "multinest":
        raise ValueError(
            "'multinest' is currently the only supported sampler."
        )

    k_vals = np.loadtxt(path / "k-vals.txt")
    k_vals_bins = np.loadtxt(path / "k-vals-bins.txt")
    version = (
        (path / "version.txt").read_text(encoding="utf-8").splitlines()[0]
    )
    args = json.loads((path / "args.json").read_text(encoding="utf-8"))
    (
        posteriors,
        posterior_bins,
        avgs,
        medians,
        ci_dict,
        uplims,
        kurtoses,
    ) = _get_posterior_data(
        path / "data-.txt",
        int(np.asarray(k_vals).size),
        posterior_weighted=data_cfg.posterior_weighted,
        cred_intervals=data_cfg.cred_intervals,
        calc_uplims=data_cfg.calc_uplims,
        uplim_quantile=data_cfg.uplim_quantile,
        nhistbins=data_cfg.nhistbins,
        density=data_cfg.density,
        log_priors=bool(args.get("log_priors", True)),
        calc_kurtosis=data_cfg.calc_kurtosis,
    )
    return BayesEoRChainSummary(
        path=path,
        label=label,
        k_vals=np.asarray(k_vals),
        k_vals_bins=np.asarray(k_vals_bins),
        version=version,
        args=args,
        posteriors=posteriors,
        posterior_bins=posterior_bins,
        avgs=avgs,
        medians=medians,
        cred_intervals=ci_dict,
        uplims=uplims,
        kurtoses=kurtoses,
    )


def _get_posterior_data(
    chain_file: Path,
    nkbins: int,
    *,
    posterior_weighted: bool,
    cred_intervals: Iterable[int | float],
    calc_uplims: bool,
    uplim_quantile: float,
    nhistbins: int,
    density: bool,
    log_priors: bool,
    calc_kurtosis: bool,
) -> tuple[
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    dict[int | float, dict[str, np.ndarray]],
    np.ndarray | None,
    np.ndarray | None,
]:
    data = np.loadtxt(chain_file)
    if len(data.shape) == 1:
        data = data.reshape(1, -1)
    if log_priors:
        data[:, 2:] = 10 ** data[:, 2:]

    weights = data[:, 0] if posterior_weighted else None
    samples = data[:, 2:]
    avgs = np.average(samples, axis=0, weights=weights)
    medians = weighted_quantiles(samples, 0.5, weights=weights)
    ci_dict: dict[int | float, dict[str, np.ndarray]] = {}
    for ci in cred_intervals:
        quantile = (ci / 2 + 50) / 100
        ci_dict[ci] = {
            "lo": weighted_quantiles(samples, 1 - quantile, weights=weights),
            "hi": weighted_quantiles(samples, quantile, weights=weights),
        }

    uplims = (
        weighted_quantiles(samples, uplim_quantile, weights=weights)
        if calc_uplims
        else None
    )

    posteriors = np.zeros((nkbins, nhistbins), dtype=float)
    bins = np.zeros((nkbins, nhistbins + 1), dtype=float)
    kurtoses = np.zeros(nkbins, dtype=float) if calc_kurtosis else None
    for i_k in range(samples.shape[1]):
        bins_min = samples[:, i_k].min()
        bins_max = samples[:, i_k].max()
        if log_priors:
            bins_min = np.log10(bins_min)
            bins_max = np.log10(bins_max)
        bins[i_k] = np.logspace(bins_min, bins_max, nhistbins + 1)
        posteriors[i_k], bins[i_k] = np.histogram(
            samples[:, i_k],
            bins=bins[i_k],
            density=density,
            weights=weights,
        )
        if kurtoses is not None:
            kurtoses[i_k] = stats.kurtosis(posteriors[i_k])

    return posteriors, bins, avgs, medians, ci_dict, uplims, kurtoses


def _build_uplim_inds(
    chains: Sequence[BayesEoRChainSummary],
    labels: Sequence[str],
    data_cfg: BayesEoRPlotDataConfig,
    *,
    ps_kind: Literal["ps", "dmps"],
    k_vals_identical: bool,
    expected_ps: list[np.ndarray] | None,
    expected_dmps: list[np.ndarray] | None,
) -> list[np.ndarray]:
    if (
        data_cfg.ignore_uplims
        or not data_cfg.calc_uplims
        or data_cfg.upper_limit_mode == "off"
    ):
        return [np.zeros(chain.k_vals.shape, dtype=bool) for chain in chains]

    uplim_inds: list[np.ndarray] = []
    for chain, label in zip(chains, labels, strict=True):
        i_chain = len(uplim_inds)
        if data_cfg.upper_limit_mode == "noise_proxy":
            arr = _noise_proxy_uplim_inds(
                chain,
                data_cfg,
                i_chain=i_chain,
                ps_kind=ps_kind,
                k_vals_identical=k_vals_identical,
                expected_ps=expected_ps,
                expected_dmps=expected_dmps,
            )
        elif data_cfg.upper_limit_mode == "posterior_edge":
            arr = _auto_uplim_inds(chain, data_cfg)
        else:
            arr = np.zeros(chain.k_vals.shape, dtype=bool)

        for idx in data_cfg.upper_limit_indices or ():
            if 0 <= idx < arr.size:
                arr[idx] = True
        for idx in data_cfg.detection_indices.get(str(label), ()):
            if 0 <= idx < arr.size:
                arr[idx] = False
        uplim_inds.append(arr)
    return uplim_inds


def _noise_proxy_uplim_inds(
    chain: BayesEoRChainSummary,
    data_cfg: BayesEoRPlotDataConfig,
    *,
    i_chain: int,
    ps_kind: Literal["ps", "dmps"],
    k_vals_identical: bool,
    expected_ps: list[np.ndarray] | None,
    expected_dmps: list[np.ndarray] | None,
) -> np.ndarray:
    expected = expected_ps if ps_kind == "ps" else expected_dmps
    if expected is None:
        return np.zeros(chain.k_vals.shape, dtype=bool)

    expected_idx = 0 if k_vals_identical else i_chain
    prob_below = _posterior_probability_below(
        chain,
        np.asarray(expected[expected_idx]),
        density=data_cfg.density,
    )
    prob_above = 1 - prob_below
    non_detection = prob_below >= data_cfg.upper_limit_probability_threshold
    detection = prob_above >= data_cfg.detection_probability_threshold
    return non_detection & ~detection


def _posterior_probability_below(
    chain: BayesEoRChainSummary,
    thresholds: np.ndarray,
    *,
    density: bool,
) -> np.ndarray:
    probabilities = np.zeros(chain.k_vals.shape, dtype=float)
    for i_k, threshold in enumerate(thresholds):
        hist = np.asarray(chain.posteriors[i_k], dtype=float)
        bins = np.asarray(chain.posterior_bins[i_k], dtype=float)
        widths = np.diff(bins)
        masses = hist * widths if density else hist
        total = masses.sum()
        if total <= 0:
            continue

        lo = bins[:-1]
        hi = bins[1:]
        below = hi <= threshold
        crossing = (lo < threshold) & (threshold < hi)
        mass_below = masses[below].sum()
        if np.any(crossing):
            frac = (threshold - lo[crossing]) / widths[crossing]
            mass_below += np.sum(masses[crossing] * frac)
        probabilities[i_k] = mass_below / total
    return probabilities


def _auto_uplim_inds(
    chain: BayesEoRChainSummary,
    data_cfg: BayesEoRPlotDataConfig,
) -> np.ndarray:
    """Classify lower-edge-peaked posteriors as upper limits."""
    posteriors = np.asarray(chain.posteriors)
    if posteriors.size == 0:
        return np.zeros(chain.k_vals.shape, dtype=bool)

    peak_bins = np.argmax(posteriors, axis=1)
    has_support = np.any(posteriors > 0, axis=1)
    return has_support & (peak_bins <= data_cfg.auto_uplim_peak_bin)


def _calculate_expected_spectra(
    outputs: BayesEoRAnalysisOutputs,
    data_cfg: BayesEoRPlotDataConfig,
) -> tuple[list[np.ndarray] | None, list[np.ndarray] | None]:
    expected_ps = data_cfg.expected_ps
    expected_dmps = data_cfg.expected_dmps
    if expected_ps is None and expected_dmps is None:
        return None, None

    if expected_ps is not None and data_cfg.ps_kind == "ps":
        return _expand_expected(expected_ps, outputs), None
    if expected_dmps is not None and data_cfg.ps_kind == "dmps":
        return None, _expand_expected(expected_dmps, outputs)
    if expected_ps is not None and data_cfg.ps_kind == "dmps":
        expected = _expand_expected(expected_ps, outputs)
        return None, [
            ps_to_dmps(val, chain.k_vals)
            for val, chain in _iter_expected_by_chain(expected, outputs)
        ]
    if expected_dmps is not None and data_cfg.ps_kind == "ps":
        expected = _expand_expected(expected_dmps, outputs)
        return [
            dmps_to_ps(val, chain.k_vals)
            for val, chain in _iter_expected_by_chain(expected, outputs)
        ], None
    return None, None


def _expand_expected(
    expected: float | list[float],
    outputs: BayesEoRAnalysisOutputs,
) -> list[np.ndarray]:
    input_iterable = isinstance(expected, Iterable) and not isinstance(
        expected, str
    )
    if outputs.k_vals_identical:
        value = np.asarray(expected, dtype=float)
        if not input_iterable:
            value = value * np.ones_like(outputs.chains[0].k_vals)
        return [value]
    expanded = []
    for chain in outputs.chains:
        value = np.asarray(expected, dtype=float)
        if not input_iterable:
            value = value * np.ones_like(chain.k_vals)
        expanded.append(value)
    return expanded


def _iter_expected_by_chain(
    expected: list[np.ndarray],
    outputs: BayesEoRAnalysisOutputs,
) -> Iterable[tuple[np.ndarray, BayesEoRChainSummary]]:
    if outputs.k_vals_identical:
        for chain in outputs.chains:
            yield expected[0], chain
    else:
        yield from zip(expected, outputs.chains, strict=True)


def plot_bayeseor_power_spectra_and_posteriors(
    outputs: BayesEoRAnalysisOutputs,
    *,
    config: BayesEoRPlotConfig | None = None,
) -> Figure:
    """Render the BayesEoR combined analysis figure using ValSKA logic."""
    cfg = config or BayesEoRPlotConfig()
    fig_cfg = cfg.figure
    style = cfg.style
    chains = outputs.chains
    if not chains:
        raise ValueError("No BayesEoR analysis outputs were provided.")

    plot_diff = fig_cfg.plot_diff
    plot_fracdiff = fig_cfg.plot_fracdiff
    if plot_diff and plot_fracdiff:
        plot_diff = False

    subplots_ps = bool(plot_diff or plot_fracdiff)
    nplots_ps = 1 + int(subplots_ps)
    nkbins = chains[0].k_vals.size
    plots_height_ps = (
        fig_cfg.plot_height_ps
        * (1 + fig_cfg.height_ratios_ps[1] * int(subplots_ps))
        * (1 + fig_cfg.hspace_ps * int(subplots_ps))
    )
    plots_height_post = (
        fig_cfg.plot_height_post * (1 + fig_cfg.hspace_post) * nkbins
    )
    fig_height = max(plots_height_ps, plots_height_post)
    fig_width = fig_cfg.plot_width * 2
    fig = plt.figure(figsize=(fig_width, fig_height))

    gridspec_kw_ps: dict[str, Any] = {
        "hspace": fig_cfg.hspace_ps,
        "right": fig_cfg.right_ps,
    }
    if subplots_ps:
        gridspec_kw_ps["height_ratios"] = fig_cfg.height_ratios_ps
    if fig_cfg.figlegend:
        gridspec_kw_ps["top"] = fig_cfg.top
    gs_ps = fig.add_gridspec(nplots_ps, 1, **gridspec_kw_ps)

    gridspec_kw_post: dict[str, Any] = {
        "hspace": fig_cfg.hspace_post,
        "left": fig_cfg.left_post,
    }
    if fig_cfg.figlegend:
        gridspec_kw_post["top"] = fig_cfg.top
    gs_post = fig.add_gridspec(nkbins, 1, **gridspec_kw_post)

    temp_ax = fig.add_subplot(gs_post[:, :])
    temp_ax.tick_params(
        labelcolor="none",
        top=False,
        bottom=False,
        left=False,
        right=False,
    )
    for side in ["left", "right", "top", "bottom"]:
        temp_ax.spines[side].set_visible(False)
    ylabel = "Power Spectrum Coefficient Posterior Distributions"
    if fig_cfg.log_y:
        ylabel = r"$\log_{10}$ " + ylabel
    temp_ax.set_ylabel(ylabel)

    axs_ps = _as_axes_list(gs_ps.subplots(sharex=True))
    axs_post = _as_axes_list(gs_post.subplots(sharex=True))

    labels = _resolve_labels(outputs, style)
    colors = _resolve_colors(style, outputs, labels)
    _plot_power_spectra(
        outputs,
        axs=axs_ps,
        colors=colors,
        labels=labels,
        config=cfg,
        plot_diff=plot_diff,
        plot_fracdiff=plot_fracdiff,
    )
    _plot_posteriors(outputs, axs=axs_post, colors=colors, config=cfg)

    if fig_cfg.figlegend:
        if fig_cfg.suptitle is not None:
            fig.suptitle(fig_cfg.suptitle)
        handles, labels_legend = axs_ps[0].get_legend_handles_labels()
        labels_legend = [
            style.expected_label if label == "Expected" else label
            for label in labels_legend
        ]
        if handles:
            ncols = (
                len(chains) + 1
                if fig_cfg.legend_ncols == 0
                else fig_cfg.legend_ncols
            )
            fig.legend(
                handles,
                labels_legend,
                loc="upper center",
                bbox_to_anchor=(0.5, fig_cfg.top + 0.075),
                ncols=ncols,
                frameon=False,
            )

    return fig


def _as_axes_list(axes: Any) -> list[Any]:
    if isinstance(axes, np.ndarray):
        return list(axes.flat)
    if isinstance(axes, Iterable):
        return list(axes)
    return [axes]


def _resolve_labels(
    outputs: BayesEoRAnalysisOutputs,
    style: BayesEoRPlotStyleConfig,
) -> list[str]:
    labels = style.labels or outputs.labels
    if not style.format_perturbation_labels:
        return list(labels)
    return [_format_perturbation_label(label) for label in labels]


def _format_perturbation_label(label: str) -> str:
    match = _TRAILING_FLOAT_RE.match(label)
    if match is None:
        return label
    prefix = match.group("prefix")
    value = float(match.group("value"))
    display_prefix = _PERTURBATION_LABELS.get(
        prefix,
        prefix.replace("_", " ").strip().title(),
    )
    percent = value * 100
    if np.isclose(percent, 0.0):
        percent_label = "0%"
    else:
        percent_label = f"{percent:+.3g}%"
    return f"{display_prefix} {percent_label}"


def _parse_perturbation_value(label: str) -> float | None:
    match = _TRAILING_FLOAT_RE.match(label)
    if match is None:
        return None
    return float(match.group("value"))


def _resolve_colors(
    style: BayesEoRPlotStyleConfig,
    outputs: BayesEoRAnalysisOutputs,
    labels: Sequence[str],
) -> list[Any]:
    n_chains = len(outputs.chains)
    if style.colors is not None:
        if len(style.colors) != n_chains:
            raise ValueError(
                "style.colors must match the number of plotted chains"
            )
        return list(style.colors)
    if style.color_mode == "perturbation":
        raw_values = [
            _parse_perturbation_value(label) for label in outputs.labels
        ]
        if all(value is not None for value in raw_values):
            values = np.array(raw_values, dtype=float)
            max_abs = float(np.max(np.abs(values)))
            cmap = plt.get_cmap(style.cmap)
            if max_abs == 0:
                return [cmap(0.5) for _ in labels]
            norm = TwoSlopeNorm(vmin=-max_abs, vcenter=0.0, vmax=max_abs)
            return [cmap(norm(value)) for value in values]
    return [f"C{i % 10}" for i in range(n_chains)]


def _plot_power_spectra(
    outputs: BayesEoRAnalysisOutputs,
    *,
    axs: list[Any],
    colors: list[Any],
    labels: list[str],
    config: BayesEoRPlotConfig,
    plot_diff: bool,
    plot_fracdiff: bool,
) -> None:
    fig_cfg = config.figure
    style = config.style
    data_cfg = config.data
    chains = outputs.chains
    subplots = len(axs) > 1
    ax = axs[0]
    ax.set_yscale("log")
    ax_diff = axs[1] if subplots else None
    zorder_offset = style.zorder_offset
    if len(chains) > 1 and style.x_offset == 0 and zorder_offset == 0:
        zorder_offset = 1

    expected = None
    if outputs.has_expected:
        expected = (
            outputs.expected_ps
            if outputs.ps_kind == "ps"
            else outputs.expected_dmps
        )
    plot_expected = True
    i_exp = 0

    _draw_power_priors(ax, outputs, colors, style)

    for i_dir, chain in enumerate(chains):
        if expected is not None and plot_expected:
            expected_color = "k" if outputs.k_vals_identical else colors[i_dir]
            ax.plot(
                chain.k_vals * (1 + style.x_offset * i_exp),
                expected[i_exp],
                color=expected_color,
                lw=style.lw,
                ls=style.ls_expected,
                label="Expected",
                zorder=0 + zorder_offset * i_dir,
            )

        xs = chain.k_vals * (1 + style.x_offset * i_dir)
        zorder = 10 + zorder_offset * i_dir
        upl_inds = outputs.uplim_inds[i_dir]
        det_inds = np.logical_not(upl_inds)
        plot_uplim_arrows = data_cfg.upper_limit_plot_mode == "arrow"
        if chain.uplims is not None and np.any(upl_inds) and plot_uplim_arrows:
            ax.errorbar(
                xs[upl_inds],
                chain.uplims[upl_inds],
                yerr=chain.uplims[upl_inds].copy() * 2 / 3,
                uplims=True,
                color=colors[i_dir],
                marker=style.marker,
                capsize=style.capsize,
                lw=style.lw,
                ls="",
                zorder=zorder,
            )
        yerr_lo = (
            chain.medians - chain.cred_intervals[data_cfg.cred_interval]["lo"]
        )
        yerr_hi = (
            chain.cred_intervals[data_cfg.cred_interval]["hi"] - chain.medians
        )
        yerr = np.array([yerr_lo, yerr_hi])
        if np.any(det_inds):
            ax.errorbar(
                xs[det_inds],
                chain.medians[det_inds],
                yerr=yerr[:, det_inds],
                color=colors[i_dir],
                marker=style.marker,
                capsize=style.capsize,
                lw=style.lw,
                ls="",
                label=labels[i_dir],
                zorder=zorder,
            )
        else:
            ax.plot(
                [],
                [],
                color=colors[i_dir],
                marker=style.marker,
                ls="",
                label=labels[i_dir],
            )

        if expected is not None and subplots and ax_diff is not None:
            if plot_diff:
                diff = chain.medians - expected[i_exp]
                diff_err = yerr.copy()
                if np.any(upl_inds) and chain.uplims is not None:
                    diff[upl_inds] = (
                        chain.uplims[upl_inds] - expected[i_exp][upl_inds]
                    )
                    if fig_cfg.ylim_diff_ps is not None:
                        diff_err[1, upl_inds] = (
                            np.abs(fig_cfg.ylim_diff_ps).max() / 2
                        )
            else:
                diff = chain.medians / expected[i_exp] - 1
                diff_err = yerr / expected[i_exp]
                if np.any(upl_inds) and chain.uplims is not None:
                    diff[upl_inds] = (
                        chain.uplims[upl_inds] / expected[i_exp][upl_inds]
                    )
                    diff[upl_inds] -= 1
                    if fig_cfg.ylim_diff_ps is not None:
                        diff_err[1, upl_inds] = (
                            np.abs(fig_cfg.ylim_diff_ps).max() / 2
                        )

            if np.any(upl_inds) and plot_uplim_arrows:
                ax_diff.errorbar(
                    xs[upl_inds],
                    diff[upl_inds],
                    yerr=diff_err[:, upl_inds],
                    uplims=True,
                    color=colors[i_dir],
                    marker=style.marker,
                    capsize=style.capsize,
                    lw=style.lw,
                    ls="",
                    zorder=zorder,
                )
            ax_diff.errorbar(
                xs[det_inds],
                diff[det_inds],
                yerr=diff_err[:, det_inds],
                color=colors[i_dir],
                marker=style.marker,
                capsize=style.capsize,
                lw=style.lw,
                ls="",
                zorder=zorder,
            )

        if expected is not None:
            if outputs.k_vals_identical:
                plot_expected = False
            else:
                i_exp += 1

    if subplots and ax_diff is not None:
        ax_diff.axhline(
            0, ls=style.ls_expected, color="k", lw=style.lw, zorder=0
        )
        ax_diff.set_ylabel(
            "Fractional\nDifference" if plot_fracdiff else "Difference"
        )
        ax_diff.set_xlabel(rf"$k$ [{outputs.k_units}]")
        if fig_cfg.ylim_diff_ps is not None:
            ax_diff.set_ylim(fig_cfg.ylim_diff_ps)
    else:
        ax.set_xlabel(rf"$k$ [{outputs.k_units}]")

    ax.set_ylabel(rf"{outputs.ps_label} [{outputs.ps_units}]")
    if fig_cfg.ylim_ps is not None:
        ax.set_ylim(fig_cfg.ylim_ps)
    for ax_i in axs:
        ax_i.grid()
        ax_i.set_xscale("log")


def _draw_power_priors(
    ax: Any,
    outputs: BayesEoRAnalysisOutputs,
    colors: Sequence[Any],
    style: BayesEoRPlotStyleConfig,
) -> None:
    if not style.plot_priors or style.prior_mode == "off":
        return

    groups = _prior_groups(outputs)
    if style.prior_mode == "shared" and len(groups) == 1:
        groups_to_draw = groups
        use_neutral_color = True
    elif style.prior_mode == "per_chain":
        groups_to_draw = [
            ([i], *_linear_prior_bounds(chain), chain.k_vals_bins)
            for i, chain in enumerate(outputs.chains)
        ]
        use_neutral_color = False
    else:
        groups_to_draw = groups
        use_neutral_color = False

    for i_group, (indices, priors_lo, priors_hi, k_vals_bins) in enumerate(
        groups_to_draw
    ):
        color = style.prior_color if use_neutral_color else colors[indices[0]]
        ax.stairs(
            priors_hi,
            k_vals_bins,
            baseline=priors_lo,
            fill=True,
            alpha=style.prior_alpha,
            color=color,
            label="Priors" if i_group == 0 else None,
            zorder=0,
        )


def _prior_groups(
    outputs: BayesEoRAnalysisOutputs,
) -> list[tuple[list[int], np.ndarray, np.ndarray, np.ndarray]]:
    groups: list[tuple[list[int], np.ndarray, np.ndarray, np.ndarray]] = []
    for i_chain, chain in enumerate(outputs.chains):
        priors_lo, priors_hi = _linear_prior_bounds(chain)
        for indices, group_lo, group_hi, group_bins in groups:
            if (
                np.allclose(priors_lo, group_lo)
                and np.allclose(priors_hi, group_hi)
                and np.allclose(chain.k_vals_bins, group_bins)
            ):
                indices.append(i_chain)
                break
        else:
            groups.append(([i_chain], priors_lo, priors_hi, chain.k_vals_bins))
    return groups


def _linear_prior_bounds(
    chain: BayesEoRChainSummary,
) -> tuple[np.ndarray, np.ndarray]:
    priors = np.array(chain.args["priors"])
    priors_lo = priors[:, 0]
    priors_hi = priors[:, 1]
    if bool(chain.args.get("log_priors", True)):
        priors_lo = 10**priors_lo
        priors_hi = 10**priors_hi
    return priors_lo, priors_hi


def _plot_posteriors(
    outputs: BayesEoRAnalysisOutputs,
    *,
    axs: list[Any],
    colors: list[Any],
    config: BayesEoRPlotConfig,
) -> None:
    fig_cfg = config.figure
    style = config.style
    expected = None
    if outputs.has_expected:
        expected = (
            outputs.expected_ps
            if outputs.ps_kind == "ps"
            else outputs.expected_dmps
        )

    if style.posterior_plot_priors and style.prior_mode != "per_chain":
        _draw_posterior_priors(axs, outputs, colors, style)

    for i_dir, chain in enumerate(outputs.chains):
        expected_idx = 0 if outputs.k_vals_identical else i_dir
        for i_k, ax in enumerate(axs):
            ax.stairs(
                chain.posteriors[i_k],
                chain.posterior_bins[i_k],
                color=colors[i_dir],
                lw=style.lw,
            )
            ax.set_yticks([])
            if i_dir == 0:
                ax.grid()
                if expected is not None:
                    ax.axvline(
                        expected[expected_idx][i_k],
                        lw=style.lw,
                        ls=style.ls_expected,
                        color="k",
                        zorder=0,
                    )
                ax.set_ylabel(rf"$\varphi_{i_k}$")
                if fig_cfg.show_k_vals:
                    ax.annotate(
                        rf"$k=${outputs.chains[0].k_vals[i_k]:.1f} [{outputs.k_units}]",
                        (0.02, 0.9),
                        xycoords="axes fraction",
                        ha="left",
                        va="top",
                    )
                ax.set_xscale("log")
                if fig_cfg.log_y:
                    ax.set_ylim([fig_cfg.ymin_post, ax.get_ylim()[1]])
                    ax.set_yscale("log")
            if style.posterior_plot_priors and style.prior_mode == "per_chain":
                priors_lo, priors_hi = _linear_prior_bounds(chain)
                ax.axvspan(
                    priors_lo[i_k],
                    priors_hi[i_k],
                    color=colors[i_dir],
                    alpha=style.posterior_prior_alpha,
                    zorder=0,
                )
    axs[-1].set_xlabel(rf"{outputs.ps_label} [{outputs.ps_units}]")


def _draw_posterior_priors(
    axs: Sequence[Any],
    outputs: BayesEoRAnalysisOutputs,
    colors: Sequence[Any],
    style: BayesEoRPlotStyleConfig,
) -> None:
    if not style.plot_priors or style.prior_mode == "off":
        return

    groups = _prior_groups(outputs)
    use_neutral_color = style.prior_mode == "shared" and len(groups) == 1
    for indices, priors_lo, priors_hi, _ in groups:
        color = style.prior_color if use_neutral_color else colors[indices[0]]
        for i_k, ax in enumerate(axs):
            ax.axvspan(
                priors_lo[i_k],
                priors_hi[i_k],
                color=color,
                alpha=style.posterior_prior_alpha,
                zorder=0,
            )
