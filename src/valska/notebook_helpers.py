"""Reusable helpers for validation notebooks."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from os.path import commonpath
from pathlib import Path
from typing import TYPE_CHECKING, Any

import matplotlib.pyplot as plt
import numpy
import pandas as pd
from IPython.display import HTML, display

from valska.external_tools.bayeseor.bayeseor_direct_plotting import (
    BeamAnalysisPlotter,
)

from .evidence import (
    ChainPair,
    calculate_bayes_factor,
    run_complete_bayeseor_analysis,
)

if TYPE_CHECKING:
    from pyuvdata import UVData


def unpack_shape(arr: numpy.typing.NDArray) -> tuple[int, int, int, int]:
    """Extract dimensions from data_array with flexible shape handling."""
    if arr.ndim == 4:
        # (Nblts, Nspws, Nfreq, Npol)
        return arr.shape
    elif arr.ndim == 3:
        # (Nblts, Nfreq, Npol)
        nblts, nfreq, npol = arr.shape
        return nblts, 1, nfreq, npol
    else:
        raise ValueError(
            f"Expected a 3D or 4D visibility array, got shape {arr.shape}"
        )


def extract_vis(
    uv: UVData, time_idx: int, pol_idx: int, freq_idx: int | None = None
) -> numpy.typing.NDArray:
    """Extract visibilities across frequency for a single time."""
    time_mask = uv.time_array == uv.time_array[time_idx]

    if uv.data_array.ndim == 4:
        if freq_idx is None:
            return uv.data_array[time_mask, 0, :, pol_idx]
        return uv.data_array[time_mask, 0, freq_idx, pol_idx]

    if freq_idx is None:
        return uv.data_array[time_mask, :, pol_idx]
    return uv.data_array[time_mask, freq_idx, pol_idx]


def extract_airy_point_bayes_factors(
    chains_dir: str | Path,
    sweep_relative_dir: str = "airy_diam14m/GSM_plus_GLEAM/_sweeps/sweep_airy_init",
) -> dict[str, Any]:
    """Parse Airy sweep points and compute per-point Bayes factors."""
    base_chains_dir = Path(chains_dir)
    sweep_dir = base_chains_dir / sweep_relative_dir
    manifest_path = sweep_dir / "sweep_manifest.json"

    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing manifest: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    points = manifest.get("points", [])

    rows: list[dict[str, Any]] = []
    for point in points:
        run_label = point.get("run_label", "unknown")
        run_dir = Path(point.get("run_dir", ""))

        signal_root = run_dir / "output" / "signal_fit"
        no_signal_root = run_dir / "output" / "no_signal"

        signal_subdirs = (
            [path for path in signal_root.iterdir() if path.is_dir()]
            if signal_root.exists()
            else []
        )
        no_signal_subdirs = (
            [path for path in no_signal_root.iterdir() if path.is_dir()]
            if no_signal_root.exists()
            else []
        )

        if len(signal_subdirs) != 1 or len(no_signal_subdirs) != 1:
            rows.append(
                {
                    "run_label": run_label,
                    "status": "skip",
                    "reason": (
                        "Expected exactly one MN subdir per hypothesis, "
                        f"got signal={len(signal_subdirs)}, "
                        f"no_signal={len(no_signal_subdirs)}"
                    ),
                }
            )
            continue

        fgeor_root = signal_subdirs[0]
        fgonly_root = no_signal_subdirs[0]

        bf = calculate_bayes_factor(
            chain_path_1=fgeor_root / "data-",
            chain_path_2=fgonly_root / "data-",
            model_name_1=f"signal_fit_{run_label}",
            model_name_2=f"no_signal_{run_label}",
            verbose=False,
        )

        rows.append(
            {
                "run_label": run_label,
                "status": "ok" if bf.get("success", False) else "error",
                "log_bayes_factor": bf.get("log_bayes_factor"),
                "interpretation": bf.get("interpretation"),
                "error": bf.get("error"),
            }
        )

    status_counts = {"ok": 0, "skip": 0, "error": 0}
    for row in rows:
        status = str(row.get("status", "error"))
        status_counts[status] = status_counts.get(status, 0) + 1

    return {
        "sweep_dir": sweep_dir,
        "manifest_path": manifest_path,
        "points": points,
        "rows": rows,
        "status_counts": status_counts,
    }


def plot_report_summary_diagnostics(
    sweep_dir: str | Path,
    title_fs: int = 24,
    axis_fs: int = 18,
    tick_fs: int = 14,
    legend_fs: int = 14,
) -> tuple[dict[str, Any], pd.DataFrame]:
    """Plot $\\Delta\\ln Z$ and $\\ln Z$ diagnostics from sweep report summary."""
    summary_json = Path(sweep_dir) / "report" / "sweep_report_summary.json"
    if not summary_json.exists():
        raise FileNotFoundError(
            f"Missing report summary: {summary_json}\n"
            "Run valska-bayeseor-report (or report-all) first."
        )

    payload = json.loads(summary_json.read_text(encoding="utf-8"))
    report_df = pd.DataFrame(payload.get("points", []))
    report_df = report_df.sort_values("perturb_frac").reset_index(drop=True)

    fig, ax = plt.subplots(figsize=(12, 7))
    ok = report_df[report_df["delta_log_evidence"].notna()]
    ax.plot(
        ok["perturb_frac"],
        ok["delta_log_evidence"],
        color="0.55",
        linewidth=1.2,
    )
    ax.scatter(
        ok[ok["delta_log_evidence"] <= 0]["perturb_frac"],
        ok[ok["delta_log_evidence"] <= 0]["delta_log_evidence"],
        color="tab:blue",
        edgecolors="black",
        linewidths=0.5,
        s=90,
        label=r"$\Delta \ln Z \leq 0$ (null test passed)",
    )
    ax.scatter(
        ok[ok["delta_log_evidence"] > 0]["perturb_frac"],
        ok[ok["delta_log_evidence"] > 0]["delta_log_evidence"],
        color="tab:red",
        edgecolors="black",
        linewidths=0.5,
        s=95,
        label=r"$\Delta \ln Z > 0$ (spurious detection preference)",
    )
    ax.axhline(0.0, linestyle="--", color="black", linewidth=1.6, alpha=0.85)
    ax.set_xlabel("Perturbation fraction", fontsize=axis_fs)
    ax.set_ylabel(r"$\Delta \ln Z$ (signal fit – no signal)", fontsize=axis_fs)
    ax.set_title(
        r"BayesEoR sweep: evidence difference ($\Delta \ln Z$)",
        fontsize=title_fs,
        pad=10,
    )
    ax.tick_params(axis="both", labelsize=tick_fs)
    ax.grid(alpha=0.25, linewidth=0.9)
    ax.legend(fontsize=legend_fs)
    fig.tight_layout()
    plt.show()

    source = payload.get("evidence_source", "ins")
    signal_col = f"signal_fit_{source}_log_evidence"
    no_signal_col = f"no_signal_{source}_log_evidence"

    if (
        signal_col not in report_df.columns
        or no_signal_col not in report_df.columns
    ):
        raise KeyError(
            f"Expected columns '{signal_col}' and '{no_signal_col}' in report summary."
        )

    fig2, ax2 = plt.subplots(figsize=(12, 7))
    ok_signal = report_df[report_df[signal_col].notna()]
    ok_no_signal = report_df[report_df[no_signal_col].notna()]
    ax2.plot(
        ok_signal["perturb_frac"],
        ok_signal[signal_col],
        marker="o",
        linewidth=1.8,
        markersize=6,
        color="tab:blue",
        label=rf"$\ln Z$ (signal fit, {source.upper()})",
    )
    ax2.plot(
        ok_no_signal["perturb_frac"],
        ok_no_signal[no_signal_col],
        marker="s",
        linewidth=1.8,
        markersize=5.5,
        color="tab:orange",
        label=rf"$\ln Z$ (no signal, {source.upper()})",
    )
    ax2.set_xlabel("Perturbation fraction", fontsize=axis_fs)
    ax2.set_ylabel(r"$\ln Z$", fontsize=axis_fs)
    ax2.set_title(
        rf"BayesEoR sweep: log evidence by model ({source.upper()})",
        fontsize=title_fs,
        pad=10,
    )
    ax2.tick_params(axis="both", labelsize=tick_fs)
    ax2.grid(alpha=0.25, linewidth=0.9)
    ax2.legend(fontsize=legend_fs)
    fig2.tight_layout()
    plt.show()

    return payload, report_df


def plot_signal_fit_chain_comparison(
    points: list[dict[str, Any]],
    title: str = "Sweep signal fit chain comparison",
    title_fs: int = 24,
    axis_fs: int = 18,
    tick_fs: int = 14,
    legend_fs: int = 11,
) -> Any:
    """Plot complementary signal-fit chain comparison directly from point run dirs."""

    def _label_order(item: tuple[str, Path]) -> float:
        label = item[0]
        try:
            return float(label.split("_", 1)[1])
        except Exception:
            return 0.0

    signal_chain_roots: list[tuple[str, Path]] = []
    for point in points:
        run_label = point.get("run_label", "unknown")
        run_dir = Path(point.get("run_dir", ""))
        signal_root = run_dir / "output" / "signal_fit"
        signal_subdirs = (
            [path for path in signal_root.iterdir() if path.is_dir()]
            if signal_root.exists()
            else []
        )
        if len(signal_subdirs) == 1:
            signal_chain_roots.append((run_label, signal_subdirs[0]))

    if not signal_chain_roots:
        raise RuntimeError("No signal_fit chains found for Airy sweep points.")

    signal_chain_roots = sorted(signal_chain_roots, key=_label_order)
    plot_keys = [label for label, _ in signal_chain_roots]
    chain_paths = [path for _, path in signal_chain_roots]
    base_dir = Path(commonpath([str(path) for path in chain_paths]))
    custom_paths = {
        label: str(path.relative_to(base_dir))
        for label, path in signal_chain_roots
    }

    custom_plotter = BeamAnalysisPlotter(
        base_chains_dir=base_dir,
        paths=custom_paths,
    )
    fig = custom_plotter.plot_analysis_results(
        analysis_keys=plot_keys,
        labels=plot_keys,
        suptitle=title,
    )

    fig.suptitle(title, fontsize=title_fs)
    for ax in fig.axes:
        ax.xaxis.label.set_fontsize(axis_fs)
        ax.yaxis.label.set_fontsize(axis_fs)
        ax.tick_params(axis="both", labelsize=tick_fs)
        legend = ax.get_legend()
        if legend is not None:
            legend.set_title("")
            for txt in legend.get_texts():
                txt.set_fontsize(legend_fs)

    plt.show()
    return fig


def run_airy_banter_summary(
    points: list[dict[str, Any]],
) -> dict[str, Any]:
    """Run Airy BaNTER summary and display a wide, non-truncating summary table."""

    def label_from_run_label(run_label: str) -> str:
        try:
            frac = float(run_label.split("_", 1)[1])
            return f"ΔD/D = {frac * 100:+.2f}%"
        except Exception:
            return run_label

    def interpretation_from_logbf(log_bf: float | None) -> str:
        if log_bf is None:
            return "Unable to evaluate"
        if log_bf > 0:
            return "Strong evidence for spurious power detected"
        if log_bf < 0:
            return "Unbiased inferences recovered"
        return "Inconclusive"

    airy_pairs: dict[str, ChainPair] = {}
    for point in points:
        run_label = point.get("run_label", "unknown")
        run_dir = Path(point.get("run_dir", ""))

        signal_root = run_dir / "output" / "signal_fit"
        no_signal_root = run_dir / "output" / "no_signal"

        signal_subdirs = (
            [path for path in signal_root.iterdir() if path.is_dir()]
            if signal_root.exists()
            else []
        )
        no_signal_subdirs = (
            [path for path in no_signal_root.iterdir() if path.is_dir()]
            if no_signal_root.exists()
            else []
        )

        if len(signal_subdirs) != 1 or len(no_signal_subdirs) != 1:
            continue

        airy_pairs[run_label] = ChainPair(
            perturbation=run_label,
            fgeor_root=signal_subdirs[0],
            fgonly_root=no_signal_subdirs[0],
        )

    print(f"Found {len(airy_pairs)} valid Airy chain pairs")
    print("Example keys:", list(airy_pairs.keys())[:5])

    capture = io.StringIO()
    with redirect_stdout(capture):
        results = run_complete_bayeseor_analysis(
            chain_pairs=airy_pairs,
            create_plots=False,
            verbose=False,
        )

    summary_rows: list[dict[str, Any]] = []
    for row in results.get("successful_results", []):
        raw_label = str(row.get("perturbation", "unknown"))
        log_bf = row.get("log_bayes_factor")
        try:
            perturb_frac = float(raw_label.split("_", 1)[1])
        except Exception:
            perturb_frac = None

        fail = log_bf is not None and log_bf > 0
        summary_rows.append(
            {
                "perturbation": label_from_run_label(raw_label),
                "perturb_frac": perturb_frac,
                "log_bayes_factor": log_bf,
                "validation": "❌ FAIL" if fail else "✅ PASS",
                "interpretation": interpretation_from_logbf(log_bf),
            }
        )

    print("=" * 88)
    print(
        "COMPLETE BAYESEOR PERTURBATION ANALYSIS SUMMARY (AIRY, PLAIN-LANGUAGE)"
    )
    print("=" * 88)

    summary_df = pd.DataFrame(summary_rows)
    if len(summary_df):
        summary_df = summary_df.sort_values("perturb_frac").reset_index(
            drop=True
        )
        table_df = summary_df[
            [
                "perturbation",
                "log_bayes_factor",
                "validation",
                "interpretation",
            ]
        ]
        table_html = table_df.to_html(index=False, escape=False)
        display(
            HTML(
                "<div style='width:100%; overflow-x:auto;'>"
                + table_html
                + "</div>"
            )
        )
    else:
        print("No successful results to summarise.")

    summary = results.get("summary", {})
    if len(summary_df):
        print(
            f"TOTAL: {summary.get('total', len(summary_df))} | "
            f"PASS: {summary.get('pass', int((summary_df['validation'] == '✅ PASS').sum()))} | "
            f"FAIL: {summary.get('fail', int((summary_df['validation'] == '❌ FAIL').sum()))} | "
            f"ERROR: {summary.get('error', 0)}"
        )

    return {
        "airy_pairs": airy_pairs,
        "results": results,
        "summary_df": summary_df,
    }
