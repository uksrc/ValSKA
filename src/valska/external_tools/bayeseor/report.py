"""Sweep-level post-processing reports for BayesEoR runs."""

from __future__ import annotations

import csv
import io
import json
import math
import os
import re
import shutil
from contextlib import redirect_stdout
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from os.path import commonpath
from pathlib import Path
from typing import Any, Literal

import matplotlib.pyplot as plt
from rich.console import Console
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from valska.external_tools.bayeseor.bayeseor_direct_plotting import (
    BeamAnalysisPlotter,
)
from valska.external_tools.bayeseor.evidence import (
    ChainPair,
    run_complete_bayeseor_analysis,
)
from valska.external_tools.bayeseor.valska_bayeseor_plotting import (
    BayesEoRPlotConfig,
    load_bayeseor_analysis_outputs,
    plot_bayeseor_power_spectra_and_posteriors,
)

_EVIDENCE_LINE_RE = re.compile(
    r"^Nested (?P<mode>Sampling|Importance Sampling) Global Log-Evidence\s*:\s*"
    r"(?P<value>[+-]?[0-9.]+E[+-][0-9]+)\s*\+/-\s*(?P<err>\S+)\s*$"
)
_TRAILING_FLOAT_RE = re.compile(
    r"(?P<value>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?)$",
    re.IGNORECASE,
)
_LEGACY_PERTURBATION_FIELDS = {
    "fwhm_perturb_frac": "fwhm_deg",
    "antenna_diameter_perturb_frac": "antenna_diameter",
}

_Hyp = Literal["signal_fit", "no_signal"]
_Source = Literal["ns", "ins"]

_AXIS_LABEL_FONTSIZE = 13
_TICK_LABEL_FONTSIZE = 11
_TITLE_FONTSIZE = 14
_LEGEND_FONTSIZE = 10
_PLOT_DPI = 300


@dataclass(frozen=True)
class EvidenceValues:
    """Evidence summary parsed from a BayesEoR ``data-stats.dat`` file."""

    ns_log_evidence: float
    ns_log_evidence_err: float | None
    ins_log_evidence: float
    ins_log_evidence_err: float | None
    source_path: Path


@dataclass(frozen=True)
class SweepPointReportRow:
    """Per-sweep-point summary row for report tables."""

    perturb_parameter: str
    perturb_frac: float
    run_label: str
    run_dir: str
    status: str
    signal_fit_ns_log_evidence: float | None
    signal_fit_ns_log_evidence_err: float | None
    signal_fit_ins_log_evidence: float | None
    signal_fit_ins_log_evidence_err: float | None
    no_signal_ns_log_evidence: float | None
    no_signal_ns_log_evidence_err: float | None
    no_signal_ins_log_evidence: float | None
    no_signal_ins_log_evidence_err: float | None
    selected_source: str
    delta_log_evidence: float | None
    bayes_factor_signal_over_no_signal: float | None
    log10_bayes_factor_signal_over_no_signal: float | None
    note: str | None


@dataclass(frozen=True)
class SweepReportResult:
    """Paths and summary metadata for a generated sweep report."""

    sweep_dir: Path
    out_dir: Path
    evidence_source: _Source
    rows_total: int
    rows_complete: int
    summary_csv: Path
    summary_json: Path
    delta_plot_png: Path | None
    evidence_plot_png: Path | None
    plot_analysis_results_png: Path | None
    valska_plot_analysis_results_pngs: list[Path]
    complete_analysis_json: Path | None
    complete_analysis_csv: Path | None
    complete_analysis_rows: list[dict[str, Any]]


@dataclass(frozen=True)
class ReportArtefactExportResult:
    """Summary of report artefacts copied into a documentation asset directory."""

    assets_dir: Path
    manifest_json: Path
    artefact_paths: list[Path]
    manifest: dict[str, Any]


def _parse_float_or_none(raw: str) -> float | None:
    s = raw.strip()
    if s.lower() == "nan":
        return None
    return float(s)


def parse_data_stats_evidence(path: Path) -> EvidenceValues:
    """Parse NS/INS log-evidence values from a BayesEoR ``data-stats.dat`` file."""
    ns_val: float | None = None
    ns_err: float | None = None
    ins_val: float | None = None
    ins_err: float | None = None

    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            m = _EVIDENCE_LINE_RE.match(line.strip())
            if not m:
                continue
            is_ins = m.group("mode") == "Importance Sampling"
            val = float(m.group("value"))
            err = _parse_float_or_none(m.group("err"))
            if is_ins:
                ins_val = val
                ins_err = err
            else:
                ns_val = val
                ns_err = err
            if ns_val is not None and ins_val is not None:
                break

    if ns_val is None or ins_val is None:
        raise ValueError(f"Could not parse NS/INS evidence from {path}")

    return EvidenceValues(
        ns_log_evidence=ns_val,
        ns_log_evidence_err=ns_err,
        ins_log_evidence=ins_val,
        ins_log_evidence_err=ins_err,
        source_path=path,
    )


def _find_single_mn_dir(hypothesis_output_dir: Path) -> Path:
    candidates = sorted(
        p for p in hypothesis_output_dir.iterdir() if p.is_dir()
    )
    if not candidates:
        raise FileNotFoundError(
            f"No nested-sampling output directory found under {hypothesis_output_dir}"
        )
    if len(candidates) == 1:
        return candidates[0]

    newest = max(candidates, key=lambda p: p.stat().st_mtime)
    return newest


def _read_point_evidence(run_dir: Path, hypothesis: _Hyp) -> EvidenceValues:
    hyp_dir = run_dir / "output" / hypothesis
    mn_dir = _find_single_mn_dir(hyp_dir)

    chain_txt = mn_dir / "data-.txt"
    if not chain_txt.exists():
        raise FileNotFoundError(
            f"Missing chain file required for evidence analysis: {chain_txt}"
        )

    stats_path = mn_dir / "data-stats.dat"
    if not stats_path.exists():
        raise FileNotFoundError(f"Missing data-stats.dat: {stats_path}")
    return parse_data_stats_evidence(stats_path)


def _find_chain_root(run_dir: Path, hypothesis: _Hyp) -> Path:
    hyp_dir = run_dir / "output" / hypothesis
    mn_dir = _find_single_mn_dir(hyp_dir)
    chain_txt = mn_dir / "data-.txt"
    if not chain_txt.exists():
        raise FileNotFoundError(
            f"Missing chain file required for evidence analysis: {chain_txt}"
        )
    return mn_dir


def _compute_bf(delta_lnz: float) -> tuple[float | None, float | None]:
    log10_bf = delta_lnz / math.log(10)
    if delta_lnz > 700 or delta_lnz < -700:
        return None, log10_bf
    return math.exp(delta_lnz), log10_bf


def _select_lnz(e: EvidenceValues, source: _Source) -> float:
    return e.ns_log_evidence if source == "ns" else e.ins_log_evidence


def _coerce_perturb_frac(point: dict[str, Any], run_label: str) -> float:
    raw = point.get("perturb_frac")
    if raw is not None:
        return float(raw)

    for field in _LEGACY_PERTURBATION_FIELDS:
        raw = point.get(field)
        if raw is not None:
            return float(raw)

    match = _TRAILING_FLOAT_RE.search(run_label)
    if match is None:
        raise ValueError(
            f"Missing perturb_frac and could not infer it from run_label={run_label!r}"
        )
    return float(match.group("value"))


def _coerce_perturb_parameter(point: dict[str, Any], run_label: str) -> str:
    raw = point.get("perturb_parameter")
    if raw:
        return str(raw)
    for field, default_parameter in _LEGACY_PERTURBATION_FIELDS.items():
        if point.get(field) is not None:
            return default_parameter
    if "_" in run_label:
        return run_label.rsplit("_", 1)[0]
    return "unknown"


def _plot_delta_log_evidence(
    rows: list[SweepPointReportRow], out_path: Path
) -> None:
    usable_points = [
        (r.perturb_frac, r.delta_log_evidence)
        for r in rows
        if r.delta_log_evidence is not None
    ]
    if not usable_points:
        return

    x = [float(xx) for xx, _ in usable_points]
    y = [float(yy) for _, yy in usable_points]

    with plt.rc_context({"font.family": "serif", "mathtext.fontset": "stix"}):
        fig, ax = plt.subplots(figsize=(8, 5))

        ax.plot(x, y, color="0.5", linewidth=1.25, alpha=0.9)

        x_fail = [xx for xx, yy in zip(x, y, strict=False) if yy > 0.0]
        y_fail = [yy for yy in y if yy > 0.0]
        x_pass = [xx for xx, yy in zip(x, y, strict=False) if yy <= 0.0]
        y_pass = [yy for yy in y if yy <= 0.0]

        if x_pass:
            ax.scatter(
                x_pass,
                y_pass,
                color="tab:blue",
                edgecolors="black",
                linewidths=0.4,
                s=38,
                label=r"$\Delta\ln Z \leq 0$ (null test passed)",
                zorder=3,
            )
        if x_fail:
            ax.scatter(
                x_fail,
                y_fail,
                color="tab:red",
                edgecolors="black",
                linewidths=0.4,
                s=42,
                label=r"$\Delta\ln Z > 0$ (spurious detection preference)",
                zorder=4,
            )

        ax.axhline(0.0, linestyle="--", linewidth=1.0, color="black")
        ax.set_xlabel("Perturbation fraction", fontsize=_AXIS_LABEL_FONTSIZE)
        ax.set_ylabel(
            r"$\Delta\ln Z\;\left(\mathrm{signal\ fit}-\mathrm{no\ signal}\right)$",
            fontsize=_AXIS_LABEL_FONTSIZE,
        )
        ax.set_title(
            r"BayesEoR sweep: evidence difference ($\Delta\ln Z$)",
            fontsize=_TITLE_FONTSIZE,
        )
        ax.tick_params(axis="both", labelsize=_TICK_LABEL_FONTSIZE)
        ax.grid(alpha=0.3)
        ax.legend(frameon=True, fontsize=_LEGEND_FONTSIZE)
        fig.tight_layout()
        fig.savefig(out_path, dpi=_PLOT_DPI)
        plt.close(fig)


def _plot_log_evidence_by_model(
    rows: list[SweepPointReportRow],
    *,
    out_path: Path,
    source: _Source,
) -> None:
    usable_points = [
        (
            r.perturb_frac,
            r.signal_fit_ns_log_evidence,
            r.no_signal_ns_log_evidence,
            r.signal_fit_ins_log_evidence,
            r.no_signal_ins_log_evidence,
        )
        for r in rows
        if (
            r.signal_fit_ns_log_evidence is not None
            and r.no_signal_ns_log_evidence is not None
            and r.signal_fit_ins_log_evidence is not None
            and r.no_signal_ins_log_evidence is not None
        )
    ]
    if not usable_points:
        return

    x = [float(xx) for xx, _, _, _, _ in usable_points]
    if source == "ns":
        signal_vals = [float(sf_ns) for _, sf_ns, _, _, _ in usable_points]
        no_signal_vals = [float(ns_ns) for _, _, ns_ns, _, _ in usable_points]
        ylabel = r"$\ln Z$ (Nested Sampling)"
    else:
        signal_vals = [float(sf_ins) for _, _, _, sf_ins, _ in usable_points]
        no_signal_vals = [
            float(ns_ins) for _, _, _, _, ns_ins in usable_points
        ]
        ylabel = r"$\ln Z$ (Nested Importance Sampling)"

    with plt.rc_context({"font.family": "serif", "mathtext.fontset": "stix"}):
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.plot(x, signal_vals, marker="o", label="signal fit")
        ax.plot(x, no_signal_vals, marker="o", label="no signal")
        ax.set_xlabel("Perturbation fraction", fontsize=_AXIS_LABEL_FONTSIZE)
        ax.set_ylabel(ylabel, fontsize=_AXIS_LABEL_FONTSIZE)
        ax.set_title(
            r"BayesEoR sweep: model evidences ($\ln Z$)",
            fontsize=_TITLE_FONTSIZE,
        )
        ax.tick_params(axis="both", labelsize=_TICK_LABEL_FONTSIZE)
        ax.grid(alpha=0.3)
        ax.legend(frameon=True, fontsize=_LEGEND_FONTSIZE)
        fig.tight_layout()
        fig.savefig(out_path, dpi=_PLOT_DPI)
        plt.close(fig)


def _rows_to_dicts(rows: list[SweepPointReportRow]) -> list[dict[str, Any]]:
    return [asdict(r) for r in rows]


def _portable_path(path: Path, root: Path, *, fallback: str) -> str:
    """Return a POSIX path relative to ``root`` without leaking host paths."""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return fallback


def _write_summary_csv(
    rows: list[SweepPointReportRow], out_path: Path
) -> None:
    payload = _rows_to_dicts(rows)
    if not payload:
        headers = [
            "perturb_parameter",
            "perturb_frac",
            "run_label",
            "run_dir",
            "status",
            "selected_source",
        ]
    else:
        headers = list(payload[0].keys())

    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=headers, lineterminator="\n"
        )
        writer.writeheader()
        for row in payload:
            writer.writerow(row)


def _write_summary_json(
    rows: list[SweepPointReportRow], out_path: Path
) -> None:
    out_path.write_text(
        json.dumps({"points": _rows_to_dicts(rows)}, indent=2),
        encoding="utf-8",
    )


def generate_sweep_report(
    *,
    sweep_dir: Path,
    out_dir: Path | None = None,
    evidence_source: _Source = "ins",
    make_plots: bool = True,
    include_plot_analysis_results: bool = False,
    include_complete_analysis_table: bool = False,
    plot_config: BayesEoRPlotConfig | None = None,
    show_progress: bool = False,
) -> SweepReportResult:
    """Generate summary table(s) and plots for an existing sweep directory."""
    sweep_dir = Path(sweep_dir).expanduser().resolve()
    if not sweep_dir.exists():
        raise FileNotFoundError(f"Sweep directory not found: {sweep_dir}")

    manifest_path = sweep_dir / "sweep_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing sweep manifest: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    points = manifest.get("points", [])
    if not isinstance(points, list) or not points:
        raise ValueError(f"No points found in {manifest_path}")

    report_dir = (
        Path(out_dir).expanduser().resolve()
        if out_dir is not None
        else (sweep_dir / "report").resolve()
    )
    report_dir.mkdir(parents=True, exist_ok=True)

    rows: list[SweepPointReportRow] = []
    signal_chain_roots: list[tuple[str, Path]] = []
    no_signal_chain_roots: list[tuple[str, Path]] = []
    chain_pairs: dict[str, ChainPair] = {}
    for point in points:
        run_label = str(point.get("run_label", ""))
        perturb_parameter = _coerce_perturb_parameter(point, run_label)
        perturb_frac = _coerce_perturb_frac(point, run_label)
        run_dir = Path(str(point.get("run_dir", ""))).expanduser().resolve()
        portable_run_dir = _portable_path(
            run_dir,
            sweep_dir,
            fallback=run_label,
        )

        try:
            signal = _read_point_evidence(run_dir, "signal_fit")
            no_signal = _read_point_evidence(run_dir, "no_signal")
            signal_root = signal.source_path.parent
            no_signal_root = no_signal.source_path.parent

            delta = _select_lnz(signal, evidence_source) - _select_lnz(
                no_signal, evidence_source
            )
            bf, log10_bf = _compute_bf(delta)

            signal_chain_roots.append((run_label, signal_root))
            no_signal_chain_roots.append((run_label, no_signal_root))
            chain_pairs[run_label] = ChainPair(
                perturbation=run_label,
                fgeor_root=signal_root,
                fgonly_root=no_signal_root,
            )

            row = SweepPointReportRow(
                perturb_parameter=perturb_parameter,
                perturb_frac=perturb_frac,
                run_label=run_label,
                run_dir=portable_run_dir,
                status="ok",
                signal_fit_ns_log_evidence=signal.ns_log_evidence,
                signal_fit_ns_log_evidence_err=signal.ns_log_evidence_err,
                signal_fit_ins_log_evidence=signal.ins_log_evidence,
                signal_fit_ins_log_evidence_err=signal.ins_log_evidence_err,
                no_signal_ns_log_evidence=no_signal.ns_log_evidence,
                no_signal_ns_log_evidence_err=no_signal.ns_log_evidence_err,
                no_signal_ins_log_evidence=no_signal.ins_log_evidence,
                no_signal_ins_log_evidence_err=no_signal.ins_log_evidence_err,
                selected_source=evidence_source,
                delta_log_evidence=delta,
                bayes_factor_signal_over_no_signal=bf,
                log10_bayes_factor_signal_over_no_signal=log10_bf,
                note=None,
            )
        except Exception as exc:
            row = SweepPointReportRow(
                perturb_parameter=perturb_parameter,
                perturb_frac=perturb_frac,
                run_label=run_label,
                run_dir=portable_run_dir,
                status="incomplete",
                signal_fit_ns_log_evidence=None,
                signal_fit_ns_log_evidence_err=None,
                signal_fit_ins_log_evidence=None,
                signal_fit_ins_log_evidence_err=None,
                no_signal_ns_log_evidence=None,
                no_signal_ns_log_evidence_err=None,
                no_signal_ins_log_evidence=None,
                no_signal_ins_log_evidence_err=None,
                selected_source=evidence_source,
                delta_log_evidence=None,
                bayes_factor_signal_over_no_signal=None,
                log10_bayes_factor_signal_over_no_signal=None,
                note=str(exc).replace(str(run_dir), portable_run_dir),
            )

        rows.append(row)

    rows.sort(key=lambda r: r.perturb_frac)

    summary_csv = report_dir / "sweep_report_summary.csv"
    summary_json = report_dir / "sweep_report_summary.json"
    _write_summary_csv(rows, summary_csv)
    _write_summary_json(rows, summary_json)

    delta_plot: Path | None = None
    evidence_plot: Path | None = None
    if make_plots:
        delta_plot = report_dir / "delta_log_evidence_vs_perturb_frac.png"
        evidence_plot = (
            report_dir / "log_evidence_by_model_vs_perturb_frac.png"
        )
        _plot_delta_log_evidence(rows, delta_plot)
        _plot_log_evidence_by_model(
            rows,
            out_path=evidence_plot,
            source=evidence_source,
        )

    plot_analysis_results_png: Path | None = None
    valska_plot_analysis_results_pngs: list[Path] = []
    if include_plot_analysis_results and signal_chain_roots:
        try:
            plot_keys = [label for label, _ in signal_chain_roots]
            chain_paths = [path for _, path in signal_chain_roots]
            base_dir = Path(commonpath([str(p) for p in chain_paths]))
            custom_paths = {
                label: str(path.relative_to(base_dir))
                for label, path in signal_chain_roots
            }
            plotter = BeamAnalysisPlotter(
                base_chains_dir=base_dir,
                paths=custom_paths,
            )
            fig = plotter.plot_analysis_results(
                analysis_keys=plot_keys,
                labels=plot_keys,
                suptitle="Sweep signal fit chain comparison",
            )
            out_plot = report_dir / "plot_analysis_results_signal_fit.png"
            fig.savefig(out_plot, dpi=_PLOT_DPI)
            plt.close(fig)
            if out_plot.exists():
                plot_analysis_results_png = out_plot
        except Exception:
            plot_analysis_results_png = None

        cfg = plot_config or BayesEoRPlotConfig()
        hyp_roots: dict[_Hyp, list[tuple[str, Path]]] = {
            "signal_fit": signal_chain_roots,
            "no_signal": no_signal_chain_roots,
        }
        for hypothesis in cfg.data.hypotheses:
            roots = hyp_roots[hypothesis]
            if not roots:
                continue
            try:
                labels = [label for label, _ in roots]
                chain_paths = [path for _, path in roots]
                render_cfg = _plot_config_for_hypothesis(cfg, hypothesis)
                outputs = load_bayeseor_analysis_outputs(
                    chain_paths,
                    labels=labels,
                    config=render_cfg,
                )
                fig = plot_bayeseor_power_spectra_and_posteriors(
                    outputs,
                    config=render_cfg,
                )
                out_plot = (
                    report_dir
                    / f"{render_cfg.outputs.filename_prefix}_{hypothesis}_valska.png"
                )
                fig.savefig(out_plot, dpi=_PLOT_DPI)
                plt.close(fig)
                if out_plot.exists():
                    valska_plot_analysis_results_pngs.append(out_plot)
            except Exception:
                continue

    complete_analysis_json: Path | None = None
    complete_analysis_csv: Path | None = None
    complete_analysis_rows: list[dict[str, Any]] = []
    if include_complete_analysis_table and chain_pairs:
        buffer = io.StringIO()
        if show_progress:
            progress_console = Console(
                stderr=True,
                force_terminal=True,
                no_color=os.environ.get("NO_COLOR") is not None,
            )
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                TimeElapsedColumn(),
                console=progress_console,
                transient=True,
            ) as progress:
                progress.add_task(
                    "Running complete BayesEoR analysis",
                    total=None,
                )
                with redirect_stdout(buffer):
                    complete_res = run_complete_bayeseor_analysis(
                        chain_pairs=chain_pairs,
                        create_plots=False,
                        verbose=False,
                        show_progress=False,
                    )
        else:
            with redirect_stdout(buffer):
                complete_res = run_complete_bayeseor_analysis(
                    chain_pairs=chain_pairs,
                    create_plots=False,
                    verbose=False,
                    show_progress=False,
                )

        complete_analysis_json = report_dir / "complete_analysis_results.json"
        complete_analysis_json.write_text(
            json.dumps(complete_res, indent=2),
            encoding="utf-8",
        )

        successful_rows = complete_res.get("successful_results", [])
        complete_analysis_rows = (
            list(successful_rows) if isinstance(successful_rows, list) else []
        )
        complete_analysis_csv = report_dir / "complete_analysis_successful.csv"
        if complete_analysis_rows:
            headers = list(complete_analysis_rows[0].keys())
            with complete_analysis_csv.open(
                "w", encoding="utf-8", newline=""
            ) as handle:
                dict_writer = csv.DictWriter(
                    handle, fieldnames=headers, lineterminator="\n"
                )
                dict_writer.writeheader()
                for complete_row in complete_analysis_rows:
                    dict_writer.writerow(complete_row)
        else:
            with complete_analysis_csv.open(
                "w", encoding="utf-8", newline=""
            ) as handle:
                csv_writer = csv.writer(handle, lineterminator="\n")
                csv_writer.writerow(
                    [
                        "perturbation",
                        "log_evidence_fgeor",
                        "log_evidence_fgonly",
                        "log_bayes_factor",
                        "validation",
                        "interpretation",
                    ]
                )

    n_complete = sum(1 for row in rows if row.status == "ok")
    return SweepReportResult(
        sweep_dir=sweep_dir,
        out_dir=report_dir,
        evidence_source=evidence_source,
        rows_total=len(rows),
        rows_complete=n_complete,
        summary_csv=summary_csv,
        summary_json=summary_json,
        delta_plot_png=delta_plot
        if delta_plot and delta_plot.exists()
        else None,
        evidence_plot_png=(
            evidence_plot if evidence_plot and evidence_plot.exists() else None
        ),
        plot_analysis_results_png=(
            plot_analysis_results_png
            if plot_analysis_results_png and plot_analysis_results_png.exists()
            else None
        ),
        valska_plot_analysis_results_pngs=valska_plot_analysis_results_pngs,
        complete_analysis_json=(
            complete_analysis_json
            if complete_analysis_json and complete_analysis_json.exists()
            else None
        ),
        complete_analysis_csv=(
            complete_analysis_csv
            if complete_analysis_csv and complete_analysis_csv.exists()
            else None
        ),
        complete_analysis_rows=complete_analysis_rows,
    )


def _plot_config_for_hypothesis(
    config: BayesEoRPlotConfig,
    hypothesis: _Hyp,
) -> BayesEoRPlotConfig:
    default_titles = {
        "Sweep signal_fit chain comparison",
        "Sweep signal fit chain comparison",
    }
    if config.figure.suptitle in default_titles:
        figure = replace(
            config.figure,
            suptitle=f"Sweep {_hypothesis_display_label(hypothesis)} chain comparison",
        )
        return replace(config, figure=figure)
    return config


def _hypothesis_display_label(hypothesis: _Hyp) -> str:
    return hypothesis.replace("_", " ")


def _report_artefact_sources(
    result: SweepReportResult,
) -> list[tuple[str, Path | None]]:
    artefacts: list[tuple[str, Path | None]] = [
        ("sweep_summary_csv", result.summary_csv),
        ("sweep_summary_json", result.summary_json),
        ("delta_log_evidence_plot", result.delta_plot_png),
        ("log_evidence_by_model_plot", result.evidence_plot_png),
        ("legacy_analysis_plot", result.plot_analysis_results_png),
    ]
    artefacts.extend(
        ("valska_analysis_plot", path)
        for path in result.valska_plot_analysis_results_pngs
    )
    artefacts.extend(
        [
            ("complete_analysis_json", result.complete_analysis_json),
            ("complete_analysis_csv", result.complete_analysis_csv),
        ]
    )
    return artefacts


def export_report_artefacts(
    result: SweepReportResult,
    assets_dir: Path,
    *,
    overwrite: bool = True,
) -> ReportArtefactExportResult:
    """Copy generated report artefacts into a documentation asset directory.

    Normal BayesEoR report generation keeps the canonical outputs under the
    sweep report directory. This helper creates an explicit snapshot for
    narrative validation reports that need stable figure/table paths.
    """
    assets_dir = Path(assets_dir).expanduser().resolve()
    assets_dir.mkdir(parents=True, exist_ok=True)

    copied_paths: list[Path] = []
    manifest_artefacts: list[dict[str, str]] = []
    for role, source in _report_artefact_sources(result):
        if source is None:
            continue
        source = Path(source).expanduser().resolve()
        if not source.exists():
            continue

        target = assets_dir / source.name
        if target.exists() and not overwrite:
            raise FileExistsError(f"Report artefact already exists: {target}")

        shutil.copy2(source, target)
        copied_paths.append(target)
        manifest_artefacts.append(
            {
                "role": role,
                "name": source.name,
                "source_path": _portable_path(
                    source,
                    result.sweep_dir,
                    fallback=f"{result.out_dir.name}/{source.name}",
                ),
                "copied_path": _portable_path(
                    target,
                    assets_dir,
                    fallback=target.name,
                ),
            }
        )

    manifest: dict[str, Any] = {
        "created_utc": datetime.now(UTC).isoformat(),
        "sweep_dir": result.sweep_dir.name,
        "report_dir": _portable_path(
            result.out_dir,
            result.sweep_dir,
            fallback=result.out_dir.name,
        ),
        "assets_dir": ".",
        "evidence_source": result.evidence_source,
        "rows_total": result.rows_total,
        "rows_complete": result.rows_complete,
        "artefacts": manifest_artefacts,
    }
    manifest_json = assets_dir / "artefact_manifest.json"
    manifest_json.write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )

    return ReportArtefactExportResult(
        assets_dir=assets_dir,
        manifest_json=manifest_json,
        artefact_paths=copied_paths,
        manifest=manifest,
    )
