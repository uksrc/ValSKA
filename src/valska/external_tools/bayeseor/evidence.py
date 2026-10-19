"""
Evidence evaluation for the ValSKA BayesEoR integration.

This module provides functions to calculate and interpret Bayes factors
between models in the BayesEoR analysis of HERA beam perturbations.

Typical usage examples
----------------------
>>> from pathlib import Path
>>> from valska.external_tools.bayeseor.evidence import (
...     calculate_bayes_factor,
...     find_chain_pairs,
...     analyze_chain_pair,
...     run_complete_bayeseor_analysis,
... )
...
>>> base = Path("/path/to/BayesEoR/chains")
>>> v7_base = base / "v7d0"
>>> pairs = find_chain_pairs(v7_base)
>>> cp = pairs["1.0e00pp"]
>>> bf_result = calculate_bayes_factor(
...     cp.fgeor_root / "data-",
...     cp.fgonly_root / "data-",
... )
>>> bf_result["log_bayes_factor"]
-3.2

>>> summary = run_complete_bayeseor_analysis(
...     chain_pairs=pairs,
...     create_plots=False,
...     verbose=False,
... )
>>> summary["summary"]["pass"]
5
"""

from __future__ import annotations

import traceback
from collections.abc import Iterable
from dataclasses import dataclass
from os.path import commonpath
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import tqdm  # noqa: F401
from anesthetic import read_chains
from bayeseor.analyze.analyze import DataContainer

from valska.constants import DEFAULT_EOR_POWER_MK2_MPC3

PathLike = str | Path
BayesFactorResult = dict[str, Any]
PerturbationResult = dict[str, Any]
SummaryDict = dict[str, int]

__all__ = [
    "BayesFactorResult",
    "ChainPair",
    "ChainPairMap",
    "PathLike",
    "PerturbationResult",
    "SummaryDict",
    "analyze_chain_pair",
    "calculate_bayes_factor",
    "find_chain_pairs",
    "interpret_bayes_factor",
    "run_complete_bayeseor_analysis",
]


def interpret_bayes_factor(log_bf: float) -> str:  # noqa: PLR0911
    """
    Interpret the strength of evidence given a log Bayes factor.

    Parameters
    ----------
    log_bf :
        Natural logarithm of the Bayes factor, ln(Z1 / Z2).

    Returns
    -------
    str
        Readable description of evidence strength, based on
        commonly used (Jeffreys-like) thresholds.
    """
    if log_bf > 5:  # noqa: PLR2004
        return "Very strong evidence for model 1"
    if log_bf > 3:  # noqa: PLR2004
        return "Strong evidence for model 1"
    if log_bf > 1:  # noqa: PLR2004
        return "Moderate evidence for model 1"
    if log_bf > -1:  # noqa: PLR2004
        return "Weak/inconclusive evidence"
    if log_bf > -3:  # noqa: PLR2004
        return "Moderate evidence for model 2"
    if log_bf > -5:  # noqa: PLR2004
        return "Strong evidence for model 2"

    return "Very strong evidence for model 2"


def calculate_bayes_factor(
    chain_path_1: PathLike,
    chain_path_2: PathLike,
    model_name_1: str = "Model 1",
    model_name_2: str = "Model 2",
    verbose: bool = True,
) -> BayesFactorResult:
    """
    Calculate Bayes factor between two models given their nested-sampling
    chains.

    The function assumes that the directories at ``chain_path_1`` and
    ``chain_path_2`` are readable by :func:`anesthetic.read_chains` and
    that the returned objects implement a ``logZ()`` method (as in
    anesthetic).

    Parameters
    ----------
    chain_path_1 :
        Path to the first model's chain directory (numerator in Bayes
        factor).
    chain_path_2 :
        Path to the second model's chain directory (denominator in Bayes
        factor).
    model_name_1 :
        Name of the first model for display and reporting.
    model_name_2 :
        Name of the second model for display and reporting.
    verbose :
        If ``True``, print intermediate information (loaded evidences
        and resulting Bayes factor) to stdout.

    Returns
    -------
    dict
        Dictionary containing results with keys:

        - ``'model_1'``: str, the name of model 1.
        - ``'model_2'``: str, the name of model 2.
        - ``'log_evidence_1'``: float or ``None``, log-evidence of model 1
        - ``'log_evidence_2'``: float or ``None``, log-evidence of model 2
        - ``'log_bayes_factor'``: float or ``None``, ln(Z1/Z2).
        - ``'interpretation'``: str, readable interpretation.
        - ``'success'``: bool, True if computation succeeded.
        - ``'error'``: str or ``None``, error message if failed.
    """
    result: BayesFactorResult = {
        "model_1": model_name_1,
        "model_2": model_name_2,
        "log_evidence_1": None,
        "log_evidence_2": None,
        "log_bayes_factor": None,
        "interpretation": "Analysis failed",
        "success": False,
        "error": None,
    }

    try:
        # Load first model chain
        if verbose:
            print(f"Loading {model_name_1} chain from: {chain_path_1}")
        chain_1 = read_chains(chain_path_1)
        evidence_1: float = float(chain_1.logZ())
        result["log_evidence_1"] = evidence_1
        if verbose:
            print(f"{model_name_1} log evidence: {evidence_1:.6f}")

        # Load second model chain
        if verbose:
            print(f"Loading {model_name_2} chain from: {chain_path_2}")
        chain_2 = read_chains(chain_path_2)
        evidence_2: float = float(chain_2.logZ())
        result["log_evidence_2"] = evidence_2
        if verbose:
            print(f"{model_name_2} log evidence: {evidence_2:.6f}")

        # Calculate Bayes factor (ln(Z1/Z2))
        log_bayes_factor: float = evidence_1 - evidence_2
        result["log_bayes_factor"] = log_bayes_factor
        result["interpretation"] = interpret_bayes_factor(log_bayes_factor)
        result["success"] = True

        if verbose:
            print(
                f"Log Bayes Factor (ln({model_name_1}/{model_name_2})):"
                f" {log_bayes_factor:.6f}"
            )
            print(f"Interpretation: {result['interpretation']}")

    except Exception as e:
        error_msg = (
            "Error calculating Bayes factor:\n"
            f"  model_1 path: {chain_path_1}\n"
            f"  model_2 path: {chain_path_2}\n"
            f"  exception: {e}\n"
            f"{traceback.format_exc()}"
        )
        result["error"] = error_msg
        if verbose:
            print(error_msg)

    return result


# ==========================================================================
# PAIR-BASED API
# ==========================================================================


@dataclass
class ChainPair:
    """Container for a matched FgEoR / FgOnly chain pair."""

    perturbation: str
    fgeor_root: Path  # directory that directly contains data-*
    fgonly_root: Path  # directory that directly contains data-*


ChainPairMap = dict[str, ChainPair]


def _find_single_mn_subdir(root: Path) -> Path:
    """
    Find the MN-* (or similar) subdirectory under a given root.

    Assumes there is exactly one subdirectory; raises if 0 or >1.
    This keeps the logic explicit and surfaces layout issues early.
    """
    subdirs = [p for p in root.iterdir() if p.is_dir()]
    if len(subdirs) == 0:
        raise RuntimeError(f"No subdirectories found under {root}")
    if len(subdirs) > 1:
        raise RuntimeError(
            f"Multiple subdirectories under {root}: {[p.name for p in subdirs]}"
        )
    return subdirs[0]


def _normalize_perturbation_key(raw_suffix: str) -> str:
    """
    Normalize a perturbation suffix into a stable key.

    For now this is just a passthrough, but by putting it in one place
    you can later convert between formats (e.g. '+1e0pp' vs '1.0e00pp')
    if needed.
    """
    return raw_suffix


def find_chain_pairs(  # noqa: PLR0912
    base_dir: Path,
    fgeor_prefix: str = "GL_FgEoR_",
    fgonly_prefix: str = "GL_FgOnly_",
    debug: bool = False,
) -> ChainPairMap:
    """
    Discover matched FgEoR / FgOnly chain pairs under a base directory.

    This is meant to work with layouts like::

        ``base_dir / "GL_FgEoR_1.0e00pp"/MN-23-23-38-2-ffm-.../data-``
        ``base_dir / "GL_FgOnly_1.0e00pp"/MN-23-23-38-2-ffm-.../data-``

    or v5-style directories such as::

        ``base_dir / "GSM_FgEoR_-5e0pp"/MN-23-23-38-2-.../data-``
        ``base_dir / "GSM_FgOnly_-5e0pp"/MN-23-23-38-2-.../data-``

    by adjusting ``fgeor_prefix`` and ``fgonly_prefix``.

    Parameters
    ----------
    base_dir :
        Directory containing GL_FgEoR_* and GL_FgOnly_* subdirectories
        (e.g. ``paths.chains_dir / 'v7d0'``), or GSM_*_* for v5-style.
    fgeor_prefix :
        Prefix for Fg+EoR directories.
    fgonly_prefix :
        Prefix for FgOnly directories.
    debug :
        If ``True``, print information about discovered entries and matches.

    Returns
    -------
    dict
        Mapping from a normalized perturbation key to a :class:`ChainPair`.
        The ``fgeor_root`` and ``fgonly_root`` paths are the MN-* level
        directories that directly contain the ``data-`` files.
    """
    if not base_dir.is_dir():
        raise FileNotFoundError(f"Base directory does not exist: {base_dir}")

    if debug:
        print(f"[find_chain_pairs] Scanning base_dir: {base_dir}")
        children = sorted(p.name for p in base_dir.iterdir())
        print(f"[find_chain_pairs] Entries under base_dir ({len(children)}):")
        for name in children:
            print(f"  - {name}")

        print(
            f"[find_chain_pairs] Using prefixes: "
            f"fgeor_prefix='{fgeor_prefix}', fgonly_prefix='{fgonly_prefix}'"
        )

    # Collect top-level FgEoR and FgOnly directories
    fgeor_dirs: dict[str, Path] = {}
    fgonly_dirs: dict[str, Path] = {}

    for entry in base_dir.iterdir():
        if not entry.is_dir():
            continue
        name = entry.name

        if name.startswith(fgeor_prefix):
            # Take the part *after* the last underscore as the perturbation
            # e.g. "GSM_FgEoR_-5e0pp" -> suffix = "-5e0pp"
            suffix = name.rsplit("_", 1)[-1]
            key = _normalize_perturbation_key(suffix)
            fgeor_dirs[key] = entry
            if debug:
                print(
                    f"[find_chain_pairs] FgEoR match: name='{name}', "
                    f"suffix='{suffix}', key='{key}'"
                )

        elif name.startswith(fgonly_prefix):
            suffix = name.rsplit("_", 1)[-1]  # e.g. "-5e0pp"
            key = _normalize_perturbation_key(suffix)
            fgonly_dirs[key] = entry
            if debug:
                print(
                    f"[find_chain_pairs] FgOnly match: name='{name}', "
                    f"suffix='{suffix}', key='{key}'"
                )

    if debug:
        print(
            "[find_chain_pairs] Collected FgEoR keys: "
            f"{sorted(fgeor_dirs.keys())}"
        )
        print(
            "[find_chain_pairs] Collected FgOnly keys:"
            f" {sorted(fgonly_dirs.keys())}"
        )

    # Determine all perturbation keys where we have both sides
    common_keys = sorted(set(fgeor_dirs.keys()) & set(fgonly_dirs.keys()))
    pairs: ChainPairMap = {}

    if debug:
        print(f"[find_chain_pairs] Common perturbation keys: {common_keys}")

    for key in common_keys:
        fgeor_top = fgeor_dirs[key]
        fgonly_top = fgonly_dirs[key]

        if debug:
            print(
                f"[find_chain_pairs] Building pair for key='{key}':\n"
                f"    FgEoR top:  {fgeor_top}\n"
                f"    FgOnly top: {fgonly_top}"
            )

        # Find the MN-* (or equivalent) subdirectory on each side
        fgeor_root = _find_single_mn_subdir(fgeor_top)
        fgonly_root = _find_single_mn_subdir(fgonly_top)

        if debug:
            print(
                f"[find_chain_pairs]   -> FgEoR root:  {fgeor_root}\n"
                f"[find_chain_pairs]   -> FgOnly root: {fgonly_root}"
            )

        pairs[key] = ChainPair(
            perturbation=key,
            fgeor_root=fgeor_root,
            fgonly_root=fgonly_root,
        )

    if debug:
        print(f"[find_chain_pairs] Total pairs found: {len(pairs)}")

    return pairs


def analyze_chain_pair(  # noqa: PLR0912
    pair: ChainPair,
    dir_prefix: Path | None = None,
    expected_ps: float = DEFAULT_EOR_POWER_MK2_MPC3,
    create_plots: bool = True,
    verbose: bool = True,
) -> PerturbationResult:
    """
    Analyse a single FgEoR/FgOnly chain pair using BaNTER-style validation.

    Parameters
    ----------
    pair :
        :class:`ChainPair` describing the perturbation and root directories.
    dir_prefix :
        Optional prefix to strip off when handing paths to
        :class:`DataContainer`. If ``None``, the common ancestor of both
        roots is used.
    expected_ps :
        Expected power spectrum value passed through to :class:`DataContainer`.
    create_plots :
        If ``True``, generate and show posterior / power spectrum plots.
    verbose :
        If ``True``, print detailed log output to stdout.

    Returns
    -------
    dict
        Result dictionary with keys:

        - ``'perturbation'``
        - ``'plot_success'``
        - ``'bayes_factor_result'``
        - ``'validation'`` (``'PASS'``, ``'FAIL'`` or ``'ERROR'``)
    """
    pert_label = pair.perturbation

    if verbose:
        print(f"\n--- Processing chain pair: {pert_label} ---")

    result: PerturbationResult = {
        "perturbation": pert_label,
        "plot_success": False,
        "bayes_factor_result": None,
        "validation": "ERROR",
    }

    # Determine dir_prefix for DataContainer if not provided
    if dir_prefix is None:
        # Use the true common ancestor of both roots
        # (may be several levels up)

        common_str = commonpath([str(pair.fgeor_root), str(pair.fgonly_root)])
        dir_prefix = Path(common_str)

    # Relative directory name for DataContainer (FgEoR side)
    fgeor_rel = pair.fgeor_root.relative_to(dir_prefix)

    # Create posterior plot if requested
    if create_plots:
        if verbose:
            print(f"Creating posterior plot for {fgeor_rel}")
        try:
            data = DataContainer(
                [str(fgeor_rel)],
                dir_prefix=dir_prefix,
                expected_ps=expected_ps,
                labels=[f"FgEoR_{pert_label}"],
            )

            fig = data.plot_power_spectra_and_posteriors(
                suptitle=f"FgEoR Analysis - {pert_label}",
                plot_fracdiff=True,
                plot_priors=True,
            )

            assert fig is not None, "Plot generation failed"

            plt.show()
            result["plot_success"] = True

        except Exception as e:
            if verbose:
                print(f"Error creating plot for {pert_label}: {e}")
            return result
    else:
        result["plot_success"] = True

    # Calculate Bayes factor
    if verbose:
        print(f"--- Bayes Factor Calculation for {pert_label} ---")

    fgeor_path: Path = pair.fgeor_root / "data-"
    fgonly_path: Path = pair.fgonly_root / "data-"

    bf_result: BayesFactorResult = calculate_bayes_factor(
        chain_path_1=fgeor_path,
        chain_path_2=fgonly_path,
        model_name_1=f"FgEoR_{pert_label}",
        model_name_2=f"FgOnly_{pert_label}",
        verbose=verbose,
    )

    result["bayes_factor_result"] = bf_result

    if bf_result["success"]:
        log_bayes_factor = bf_result["log_bayes_factor"]
        result["validation"] = "PASS" if log_bayes_factor < 0 else "FAIL"
        if verbose:
            if log_bayes_factor < 0:
                print("✅ PASS: BaNTER correctly favors foreground-only model")
            else:
                print(
                    "❌ FAIL: BaNTER incorrectly detects EoR signal in "
                    "foreground-only data"
                )
    else:
        result["validation"] = "ERROR"

    return result


def run_complete_bayeseor_analysis(  # noqa: PLR0912,PLR0913,PLR0915
    chain_pairs: ChainPairMap,
    perturbation_levels: Iterable[str] | None = None,
    dir_prefix: Path | None = None,
    expected_ps: float = DEFAULT_EOR_POWER_MK2_MPC3,
    create_plots: bool = False,
    show_detailed_results: bool = False,
    verbose: bool = True,
    show_progress: bool = True,
) -> dict[str, Any]:
    """
    Run a complete BayesEoR perturbation analysis over multiple chain pairs.

    Parameters
    ----------
    chain_pairs :
        Mapping of perturbation keys to :class:`ChainPair` objects, typically
        created by :func:`find_chain_pairs`.
    perturbation_levels :
        Optional iterable of perturbation keys to analyse. If ``None``,
        all keys in ``chain_pairs`` are used.
    dir_prefix :
        Optional directory prefix for :func:`analyze_chain_pair`. If ``None``,
        the common ancestor of each pair is used individually.
    expected_ps :
        Expected power spectrum value passed on to :func:`analyze_chain_pair`.
    create_plots :
        If ``True``, generate plots for each perturbation level.
    show_detailed_results :
        If ``True``, print detailed numerical results per successful
        perturbation.
    verbose :
        If ``True``, print readable progress and summary messages.
    show_progress :
        If ``True`` and multiple perturbation levels are analysed, display
        a ``tqdm`` progress bar (if available).

    Returns
    -------
    dict
        Contains ``'results'``, ``'summary'``, and ``'successful_results'``.
    """
    # Select and order perturbations
    pair_items = list(chain_pairs.items())

    if perturbation_levels is not None:
        requested = set(perturbation_levels)
        pair_items = [(k, v) for k, v in pair_items if k in requested]

    pair_items.sort(key=lambda kv: kv[0])
    labels: list[str] = [k for k, _ in pair_items]
    total_cases = len(labels)

    if verbose:
        print("=== Complete BayesEoR Analysis (pair-based) ===")
        print(f"Analysing {total_cases} perturbation levels...")
        print("Perturbation levels:", labels)
        if create_plots:
            print("Note: Plots will be generated for each perturbation")

    all_results: list[PerturbationResult] = []

    # Progress bar
    if verbose and show_progress and total_cases > 1:
        try:
            perturbation_iterator: Iterable[str] = tqdm.tqdm(
                labels,
                desc="Analysing perturbations",
                unit="case",
                ncols=80,
                bar_format=(
                    "{l_bar}{bar}| {n_fmt}/{total_fmt} "
                    "[{elapsed}<{remaining}, {rate_fmt}]"
                ),
            )
        except ImportError:
            print("Note: Install 'tqdm' for progress bar display")
            perturbation_iterator = labels
    else:
        perturbation_iterator = labels

    for i, pert_label in enumerate(perturbation_iterator, 1):
        if verbose and not show_progress:
            print(f"\n--- Processing {i}/{total_cases}: {pert_label} ---")

        pair = chain_pairs[pert_label]
        result = analyze_chain_pair(
            pair=pair,
            dir_prefix=dir_prefix,
            expected_ps=expected_ps,
            create_plots=create_plots,
            verbose=(False if show_progress else verbose),
        )
        all_results.append(result)

        if show_progress:
            set_description = getattr(
                perturbation_iterator, "set_description", None
            )
            if callable(set_description):
                set_description(f"Analysing: {pert_label}")

    # Summary table
    print("\n" + "=" * 80)
    print("COMPLETE BAYESEOR PERTURBATION ANALYSIS SUMMARY")
    print("=" * 80)
    print(
        f"{'Perturbation':<20} {'Log BF':<10} "
        f"{'Validation':<12} {'Interpretation'}"
    )
    print("-" * 80)

    pass_count: int = 0
    fail_count: int = 0
    error_count: int = 0

    for result in all_results:
        pert = result["perturbation"]
        validation = result["validation"]

        if validation == "ERROR":
            print(
                f"{pert:<20} {'ERROR':<10} {'❌ ERROR':<15} {'Analysis failed'}"
            )
            error_count += 1
        else:
            bf_result = result["bayes_factor_result"]
            if bf_result and bf_result["success"]:
                log_bf = bf_result["log_bayes_factor"]
                interpretation = bf_result["interpretation"]

                if validation == "PASS":
                    validation_display = "✅ PASS"
                    pass_count += 1
                else:
                    validation_display = "❌ FAIL"
                    fail_count += 1

                print(
                    f"{pert:<20} {log_bf:<10.3f} "
                    f"{validation_display:<15} {interpretation}"
                )
            else:
                print(
                    f"{pert:<20} {'N/A':<10} "
                    f"{'❌ ERROR':<15} {'Calculation failed'}"
                )
                error_count += 1

    print("-" * 80)
    print(
        f"TOTAL: {len(all_results)} cases | PASS: {pass_count} | "
        f"FAIL: {fail_count} | ERROR: {error_count}"
    )

    if pass_count == len(all_results) - error_count:
        print("🎉 ALL VALID CASES PASSED BaNTER VALIDATION!")
    elif fail_count > 0:
        print("⚠️  SOME CASES FAILED BaNTER VALIDATION - Investigation needed")

    print(
        f"\nBaNTER Validation Complete - Processed {len(all_results)} "
        f"perturbation levels"
    )

    # Collect successful results
    successful_results: list[dict[str, Any]] = []
    for result in all_results:
        if (
            result["validation"] != "ERROR"
            and result["bayes_factor_result"]["success"]
        ):
            bf_data = result["bayes_factor_result"]
            detailed_result: dict[str, Any] = {
                "perturbation": result["perturbation"],
                "log_evidence_fgeor": bf_data["log_evidence_1"],
                "log_evidence_fgonly": bf_data["log_evidence_2"],
                "log_bayes_factor": bf_data["log_bayes_factor"],
                "validation": result["validation"],
                "interpretation": bf_data["interpretation"],
            }
            successful_results.append(detailed_result)

    if show_detailed_results:
        print("\n" + "=" * 60)
        print("DETAILED RESULTS FOR FURTHER ANALYSIS")
        print("=" * 60)

        for detailed_result in successful_results:
            print(f"Perturbation: {detailed_result['perturbation']}")
            print(
                f"  FgEoR Evidence: {detailed_result['log_evidence_fgeor']:.6f}"
            )
            print(
                f"  FgOnly Evidence: "
                f"{detailed_result['log_evidence_fgonly']:.6f}"
            )
            print(
                f"  Log Bayes Factor: {detailed_result['log_bayes_factor']:.6f}"
            )
            print(f"  Validation: {detailed_result['validation']}")
            print(f"  Interpretation: {detailed_result['interpretation']}")
            print()

        print(
            f"Successfully analysed {len(successful_results)} "
            f"out of {len(all_results)} perturbations"
        )

    summary: SummaryDict = {
        "total": len(all_results),
        "pass": pass_count,
        "fail": fail_count,
        "error": error_count,
    }
    return {
        "results": all_results,
        "summary": summary,
        "successful_results": successful_results,
    }
