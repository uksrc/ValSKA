"""Tests for ValSKA-native BayesEoR analysis plot loading/rendering."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from valska.external_tools.bayeseor.plot_configs import (
    get_default_analysis_plot_config_path,
    resolve_analysis_plot_config_path,
)
from valska.external_tools.bayeseor.valska_bayeseor_plotting import (
    BayesEoRPlotConfig,
    _format_perturbation_label,
    _prior_groups,
    dmps_to_ps,
    load_bayeseor_analysis_outputs,
    plot_bayeseor_power_spectra_and_posteriors,
    ps_to_dmps,
    weighted_quantiles,
)

pytest.importorskip("bayeseor")
from bayeseor.analyze.analyze import DataContainer  # noqa: E402


def _write_chain(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    np.savetxt(root / "k-vals.txt", np.array([0.1, 0.2]))
    np.savetxt(root / "k-vals-bins.txt", np.array([0.08, 0.15, 0.25]))
    (root / "version.txt").write_text("test-version\n", encoding="utf-8")
    (root / "args.json").write_text(
        json.dumps({"log_priors": True, "priors": [[0.0, 4.0], [0.0, 4.0]]}),
        encoding="utf-8",
    )
    data = np.array(
        [
            [0.10, 0.0, 1.0, 1.2],
            [0.20, 0.0, 1.2, 1.4],
            [0.30, 0.0, 1.4, 1.6],
            [0.25, 0.0, 1.6, 1.8],
            [0.15, 0.0, 1.8, 2.0],
        ]
    )
    np.savetxt(root / "data-.txt", data)


def _write_chain_with_samples(root: Path, samples: np.ndarray) -> None:
    root.mkdir(parents=True, exist_ok=True)
    np.savetxt(root / "k-vals.txt", np.array([0.1, 0.2]))
    np.savetxt(root / "k-vals-bins.txt", np.array([0.08, 0.15, 0.25]))
    (root / "version.txt").write_text("test-version\n", encoding="utf-8")
    (root / "args.json").write_text(
        json.dumps({"log_priors": True, "priors": [[0.0, 4.0], [0.0, 4.0]]}),
        encoding="utf-8",
    )
    weights = np.ones((samples.shape[0], 1))
    log_likelihood = np.zeros((samples.shape[0], 1))
    np.savetxt(
        root / "data-.txt", np.hstack([weights, log_likelihood, samples])
    )


def test_weighted_quantiles_matches_bayeseor_algorithm() -> None:
    data = np.array([[1.0, 10.0], [2.0, 20.0], [4.0, 40.0]])
    weights = np.array([1.0, 2.0, 1.0])

    got = weighted_quantiles(data, 0.5, weights=weights)

    np.testing.assert_allclose(got, np.array([1.5, 15.0]))


def test_power_spectrum_conversions_round_trip() -> None:
    ks = np.array([0.1, 0.2])
    ps = np.array([100.0, 200.0])

    dmps = ps_to_dmps(ps, ks)

    np.testing.assert_allclose(dmps_to_ps(dmps, ks), ps)


def test_default_plot_config_uses_wrapped_valska_legend() -> None:
    assert BayesEoRPlotConfig().figure.legend_ncols == 6


def test_default_plot_config_uses_display_title() -> None:
    assert (
        BayesEoRPlotConfig().figure.suptitle
        == "Sweep signal fit chain comparison"
    )


def test_default_plot_config_uses_shared_light_priors() -> None:
    style = BayesEoRPlotConfig().style
    assert style.prior_mode == "shared"
    assert style.prior_alpha < 0.3
    assert style.posterior_prior_alpha < 0.3
    assert style.prior_color == "lightsteelblue"


def test_default_plot_config_uses_noise_proxy_non_detection_omission() -> None:
    data = BayesEoRPlotConfig().data

    assert data.upper_limit_mode == "noise_proxy"
    assert data.upper_limit_plot_mode == "omit"


def test_plot_config_accepts_prior_colour_alias() -> None:
    config = BayesEoRPlotConfig.from_mapping(
        {"style": {"prior_colour": "gainsboro"}}
    )

    assert config.style.prior_color == "gainsboro"


def test_packaged_default_plot_config_matches_builtin_defaults() -> None:
    from_file = BayesEoRPlotConfig.from_yaml(
        get_default_analysis_plot_config_path()
    )

    assert from_file == BayesEoRPlotConfig()


def test_plot_config_resolution_uses_cwd_plot_yaml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plot_yaml = tmp_path / "plot.yaml"
    plot_yaml.write_text("style:\n  prior_mode: off\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert resolve_analysis_plot_config_path() == Path("plot.yaml")
    assert (
        BayesEoRPlotConfig.from_yaml(
            resolve_analysis_plot_config_path()
        ).style.prior_mode
        == "off"
    )


def test_plot_config_resolution_falls_back_to_packaged_plot_yaml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    resolved = resolve_analysis_plot_config_path()

    assert resolved is not None
    assert resolved.name == "plot.yaml"
    assert resolved.parent.name == "plot_configs"


def test_perturbation_labels_are_formatted_as_percentages() -> None:
    assert _format_perturbation_label("antdiam_-2.0e-01") == "Diameter -20%"
    assert _format_perturbation_label("fwhm_0.0e+00") == "FWHM 0%"


def test_load_bayeseor_analysis_outputs_matches_data_container(
    tmp_path: Path,
) -> None:
    chain = tmp_path / "MN-test"
    _write_chain(chain)
    config = BayesEoRPlotConfig.from_mapping(
        {"data": {"expected_ps": 100.0, "nhistbins": 7}}
    )

    valska = load_bayeseor_analysis_outputs(
        [chain],
        labels=["chain"],
        config=config,
    )
    bayeseor = DataContainer(
        [str(chain)],
        expected_ps=100.0,
        posterior_weighted=True,
        cred_intervals=[68, 95],
        Nhistbins=7,
    )

    np.testing.assert_allclose(valska.chains[0].medians, bayeseor.medians[0])
    np.testing.assert_allclose(valska.chains[0].avgs, bayeseor.avgs[0])
    assert valska.chains[0].uplims is not None
    np.testing.assert_allclose(valska.chains[0].uplims, bayeseor.uplims[0])
    np.testing.assert_allclose(
        valska.chains[0].cred_intervals[68]["lo"],
        bayeseor.cred_intervals[0][68]["lo"],
    )
    np.testing.assert_allclose(
        valska.chains[0].cred_intervals[68]["hi"],
        bayeseor.cred_intervals[0][68]["hi"],
    )
    np.testing.assert_allclose(
        valska.chains[0].posteriors, bayeseor.posteriors[0]
    )
    np.testing.assert_allclose(
        valska.chains[0].posterior_bins,
        bayeseor.posterior_bins[0],
    )
    assert valska.expected_dmps is not None
    np.testing.assert_allclose(
        valska.expected_dmps[0], bayeseor.expected_dmps[0]
    )


def test_noise_proxy_upper_limit_selection_uses_noise_level(
    tmp_path: Path,
) -> None:
    chain = tmp_path / "MN-noise-proxy-uplims"
    _write_chain_with_samples(
        chain,
        np.array(
            [
                [1.0, 3.0],
                [1.05, 3.05],
                [1.1, 3.1],
                [1.15, 3.15],
                [1.2, 3.2],
            ]
        ),
    )
    config = BayesEoRPlotConfig.from_mapping(
        {
            "data": {
                "expected_ps": 100.0,
                "nhistbins": 4,
                "ps_kind": "ps",
            }
        }
    )

    outputs = load_bayeseor_analysis_outputs(
        [chain],
        labels=["chain"],
        config=config,
    )

    np.testing.assert_array_equal(
        outputs.uplim_inds[0], np.array([True, False])
    )


def test_posterior_edge_upper_limit_selection_uses_lower_edge_peak(
    tmp_path: Path,
) -> None:
    chain = tmp_path / "MN-posterior-edge-uplims"
    _write_chain_with_samples(
        chain,
        np.array(
            [
                [0.0, 0.0],
                [0.0, 2.0],
                [0.0, 2.0],
                [2.0, 2.0],
                [4.0, 4.0],
            ]
        ),
    )
    config = BayesEoRPlotConfig.from_mapping(
        {
            "data": {
                "upper_limit_mode": "posterior_edge",
                "nhistbins": 4,
                "expected_ps": None,
            }
        }
    )

    outputs = load_bayeseor_analysis_outputs(
        [chain],
        labels=["chain"],
        config=config,
    )

    np.testing.assert_array_equal(
        outputs.uplim_inds[0], np.array([True, False])
    )


def test_manual_upper_limit_selection_is_still_available(
    tmp_path: Path,
) -> None:
    chain = tmp_path / "MN-manual-uplims"
    _write_chain(chain)
    config = BayesEoRPlotConfig.from_mapping(
        {
            "data": {
                "upper_limit_mode": "manual",
                "upper_limit_indices": [1],
                "detection_indices": {"chain": [1]},
                "expected_ps": None,
            }
        }
    )

    outputs = load_bayeseor_analysis_outputs(
        [chain],
        labels=["chain"],
        config=config,
    )

    np.testing.assert_array_equal(
        outputs.uplim_inds[0], np.array([False, False])
    )


def test_identical_priors_are_grouped_once(tmp_path: Path) -> None:
    first = tmp_path / "MN-first"
    second = tmp_path / "MN-second"
    _write_chain(first)
    _write_chain(second)

    outputs = load_bayeseor_analysis_outputs(
        [first, second],
        labels=["antdiam_-1.0e-01", "antdiam_1.0e-01"],
        config=BayesEoRPlotConfig.from_mapping({"data": {"nhistbins": 7}}),
    )

    assert len(_prior_groups(outputs)) == 1


def test_renderer_smoke_writes_png(tmp_path: Path) -> None:
    chain = tmp_path / "MN-test"
    _write_chain(chain)
    config = BayesEoRPlotConfig.from_mapping(
        {
            "data": {"expected_ps": 100.0, "nhistbins": 7},
            "figure": {"suptitle": "Native ValSKA plot"},
        }
    )
    outputs = load_bayeseor_analysis_outputs(
        [chain],
        labels=["chain"],
        config=config,
    )

    fig = plot_bayeseor_power_spectra_and_posteriors(outputs, config=config)
    out = tmp_path / "plot.png"
    fig.savefig(out)

    assert out.exists()
    assert out.stat().st_size > 0
