#!/usr/bin/env python3
"""Generate summary plots/tables for a completed BayesEoR sweep."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rich import box
from rich.table import Table

from valska.cli_format import (
    CliColors,
    add_color_argument,
    add_progress_argument,
    resolve_color_mode,
    resolve_progress_mode,
    show_progress,
)
from valska.external_tools.bayeseor.plot_configs import (
    resolve_analysis_plot_config_path,
)
from valska.external_tools.bayeseor.report import (
    ReportArtefactExportResult,
    SweepReportResult,
    export_report_artefacts,
    generate_sweep_report,
)
from valska.external_tools.bayeseor.valska_bayeseor_plotting import (
    BayesEoRPlotConfig,
)

_TableStyle = str


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for ``valska-bayeseor-report``."""
    parser = argparse.ArgumentParser(
        prog="valska-bayeseor-report",
        description=(
            "Generate report tables and plots from an existing ValSKA BayesEoR sweep.\n\n"
            "Typical input:\n"
            "  <results_root>/bayeseor/<beam>/<sky>/_sweeps/<run_id>/"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )

    parser.add_argument(
        "sweep_dir",
        type=Path,
        help=(
            "Path to an existing sweep directory containing sweep_manifest.json.\n"
            "Example: /.../bayeseor/airy_diam14m/GSM_plus_GLEAM/_sweeps/sweep_airy_init"
        ),
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Output directory for generated report files (default: <sweep_dir>/report).",
    )
    parser.add_argument(
        "--evidence-source",
        choices=["ns", "ins"],
        default="ins",
        help="Which evidence estimate to use for ΔlnZ/Bayes factor (default: ins).",
    )
    parser.add_argument(
        "--no-plots",
        action="store_true",
        help="Only write tabular report files (skip PNG plot generation).",
    )
    parser.add_argument(
        "--include-plot-analysis-results",
        action="store_true",
        help=(
            "Also generate a BeamAnalysisPlotter.plot_analysis_results figure "
            "and a ValSKA-rendered figure for complete points."
        ),
    )
    parser.add_argument(
        "--plot-config",
        type=Path,
        default=None,
        help=(
            "Optional YAML config for ValSKA-rendered BayesEoR analysis plots "
            "(used with --include-plot-analysis-results). If omitted, "
            "ValSKA uses ./plot.yaml when present, then the packaged "
            "plot_configs/plot.yaml if available."
        ),
    )
    parser.add_argument(
        "--export-report-assets",
        type=Path,
        default=None,
        help=(
            "Copy generated report artefacts into this directory and write "
            "artefact_manifest.json. This is intended for documentation report "
            "asset snapshots; the canonical report outputs remain in --out-dir."
        ),
    )
    parser.add_argument(
        "--include-complete-analysis-table",
        action="store_true",
        help=(
            "Also run run_complete_bayeseor_analysis across complete points "
            "and write summary table/json outputs."
        ),
    )
    parser.add_argument(
        "--print-complete-analysis-table",
        action="store_true",
        help=(
            "Print a terminal summary table for complete-analysis results. "
            "Implies --include-complete-analysis-table."
        ),
    )
    parser.add_argument(
        "--complete-analysis-table-style",
        choices=["emoji", "plain"],
        default="emoji",
        help=(
            "Terminal style for --print-complete-analysis-table. "
            "Use 'plain' for ASCII-only validation labels. Default: emoji."
        ),
    )
    parser.add_argument(
        "--json",
        dest="json_out",
        action="store_true",
        help="Print report result payload as JSON.",
    )
    add_progress_argument(parser)
    add_color_argument(parser)
    return parser


def _format_perturbation_label(raw_label: object) -> str:
    label = str(raw_label)
    try:
        prefix, raw_frac = label.rsplit("_", 1)
        frac = float(raw_frac)
    except Exception:
        return label

    if prefix in {"antdiam", "antenna_diameter"}:
        return f"ΔD/D = {frac * 100:+.2f}%"
    if prefix == "fwhm":
        return f"ΔFWHM/FWHM = {frac * 100:+.2f}%"
    return f"Δ = {frac * 100:+.2f}%"


def _perturbation_fraction(raw_label: object) -> float | None:
    label = str(raw_label)
    try:
        return float(label.rsplit("_", 1)[1])
    except Exception:
        return None


def _coerce_float(raw: object) -> float:
    if isinstance(raw, str | int | float):
        return float(raw)
    raise TypeError(f"Expected a numeric value, got {type(raw).__name__}")


def _plain_interpretation(log_bayes_factor: object) -> str:
    try:
        log_bf = _coerce_float(log_bayes_factor)
    except Exception:
        return "Unable to evaluate"
    if log_bf > 0:
        return "Strong evidence for spurious power detected"
    if log_bf < 0:
        return "Unbiased inferences recovered"
    return "Inconclusive"


def _format_log_bayes_factor(raw: object) -> str:
    try:
        return f"{_coerce_float(raw):.3f}"
    except Exception:
        return "N/A"


def _validation_display(validation: object, *, style: _TableStyle) -> str:
    text = str(validation)
    if style == "plain":
        return text
    if text == "PASS":
        return "✅ PASS"
    if text == "FAIL":
        return "❌ FAIL"
    return f"❌ {text}" if text else "❌ ERROR"


def _validation_style(validation: object, *, colors: CliColors) -> str | None:
    if not colors.enabled:
        return None
    text = str(validation)
    if "PASS" in text:
        return "green"
    if "FAIL" in text or "ERROR" in text:
        return "red"
    return "yellow"


def _print_complete_analysis_table(
    rows: list[dict[str, object]], *, style: _TableStyle, colors: CliColors
) -> None:
    if not rows:
        print("\nNo successful complete-analysis results to summarise.")
        return

    table_rows = [
        {
            "perturbation": _format_perturbation_label(
                row.get("perturbation", "unknown")
            ),
            "log_bf": _format_log_bayes_factor(row.get("log_bayes_factor")),
            "validation": _validation_display(
                row.get("validation", "ERROR"),
                style=style,
            ),
            "validation_style": _validation_style(
                row.get("validation", "ERROR"),
                colors=colors,
            ),
            "interpretation": _plain_interpretation(
                row.get("log_bayes_factor")
            ),
            "sort_value": _perturbation_fraction(
                row.get("perturbation", "unknown")
            ),
        }
        for row in rows
    ]
    table_rows.sort(
        key=lambda row: (
            row["sort_value"] is None,
            row["sort_value"] if isinstance(row["sort_value"], float) else 0.0,
            str(row["perturbation"]),
        )
    )

    table = Table(
        title="Complete BayesEoR Perturbation Analysis Summary",
        box=box.ASCII,
        show_lines=False,
    )
    table.add_column("Perturbation", style="cyan" if colors.enabled else None)
    table.add_column("Log BF", justify="right")
    table.add_column("Validation")
    table.add_column("Interpretation")

    pass_count = 0
    fail_count = 0
    for row in table_rows:
        validation = str(row["validation"])
        if "PASS" in validation:
            pass_count += 1
        elif "FAIL" in validation:
            fail_count += 1
        table.add_row(
            str(row["perturbation"]),
            str(row["log_bf"]),
            str(row["validation"]),
            str(row["interpretation"]),
            style=row["validation_style"]
            if isinstance(row["validation_style"], str)
            else None,
        )

    colors.console.print()
    colors.console.print(table)
    colors.console.print(
        colors.success(
            f"TOTAL: {len(table_rows)} | PASS: {pass_count} | "
            f"FAIL: {fail_count} | ERROR: 0"
        )
    )


def _print_summary(result: SweepReportResult, *, colors: CliColors) -> None:
    print("\n" + colors.heading("Sweep report generated:"))
    print(f"  sweep_dir:      {colors.path(result.sweep_dir)}")
    print(f"  out_dir:        {colors.path(result.out_dir)}")
    print(f"  evidence_source:{result.evidence_source}")
    print(f"  points_total:   {result.rows_total}")
    print(f"  points_complete:{colors.success(result.rows_complete)}")
    print(f"  summary_csv:    {colors.path(result.summary_csv)}")
    print(f"  summary_json:   {colors.path(result.summary_json)}")
    if result.delta_plot_png is not None:
        print(f"  delta_plot:     {colors.path(result.delta_plot_png)}")
    if result.evidence_plot_png is not None:
        print(f"  evidence_plot:  {colors.path(result.evidence_plot_png)}")
    if result.plot_analysis_results_png is not None:
        print(
            "  plot_analysis_results: "
            f"{colors.path(result.plot_analysis_results_png)}"
        )
    for path in result.valska_plot_analysis_results_pngs:
        print(f"  valska_plot_analysis_results: {colors.path(path)}")
    if result.complete_analysis_json is not None:
        print(
            "  complete_analysis_json: "
            f"{colors.path(result.complete_analysis_json)}"
        )
    if result.complete_analysis_csv is not None:
        print(
            "  complete_analysis_csv:  "
            f"{colors.path(result.complete_analysis_csv)}"
        )


def _export_payload(
    export: ReportArtefactExportResult | None,
) -> dict[str, object] | None:
    if export is None:
        return None
    return {
        "assets_dir": str(export.assets_dir),
        "manifest_json": str(export.manifest_json),
        "artefact_paths": [str(path) for path in export.artefact_paths],
        "artefact_count": len(export.artefact_paths),
    }


def _print_export_summary(
    export: ReportArtefactExportResult, *, colors: CliColors
) -> None:
    print("\n" + colors.heading("Report assets exported:"))
    print(f"  assets_dir:     {colors.path(export.assets_dir)}")
    print(f"  manifest_json:  {colors.path(export.manifest_json)}")
    print(f"  artefact_count: {len(export.artefact_paths)}")


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for ``valska-bayeseor-report``."""
    args = build_parser().parse_args(argv)

    if args.json_out and args.print_complete_analysis_table:
        print(
            "ERROR: --print-complete-analysis-table cannot be combined with --json.",
            file=sys.stderr,
        )
        return 2

    try:
        plot_config_path = None
        plot_config = None
        if bool(args.include_plot_analysis_results):
            plot_config_path = resolve_analysis_plot_config_path(
                args.plot_config
            )
            plot_config = BayesEoRPlotConfig.from_yaml(plot_config_path)
        result = generate_sweep_report(
            sweep_dir=Path(args.sweep_dir),
            out_dir=Path(args.out_dir) if args.out_dir is not None else None,
            evidence_source=args.evidence_source,
            make_plots=not bool(args.no_plots),
            include_plot_analysis_results=bool(
                args.include_plot_analysis_results
            ),
            include_complete_analysis_table=bool(
                args.include_complete_analysis_table
                or args.print_complete_analysis_table
            ),
            plot_config=plot_config,
            show_progress=show_progress(
                resolve_progress_mode(args.progress),
                json_out=bool(args.json_out),
            ),
        )
        artefact_export = (
            export_report_artefacts(
                result,
                Path(args.export_report_assets),
            )
            if args.export_report_assets is not None
            else None
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json_out:
        payload = {
            "sweep_dir": str(result.sweep_dir),
            "out_dir": str(result.out_dir),
            "evidence_source": result.evidence_source,
            "rows_total": result.rows_total,
            "rows_complete": result.rows_complete,
            "summary_csv": str(result.summary_csv),
            "summary_json": str(result.summary_json),
            "delta_plot_png": str(result.delta_plot_png)
            if result.delta_plot_png is not None
            else None,
            "evidence_plot_png": str(result.evidence_plot_png)
            if result.evidence_plot_png is not None
            else None,
            "plot_analysis_results_png": str(result.plot_analysis_results_png)
            if result.plot_analysis_results_png is not None
            else None,
            "valska_plot_analysis_results_pngs": [
                str(path) for path in result.valska_plot_analysis_results_pngs
            ],
            "plot_config": str(plot_config_path)
            if plot_config_path is not None
            else None,
            "complete_analysis_json": str(result.complete_analysis_json)
            if result.complete_analysis_json is not None
            else None,
            "complete_analysis_csv": str(result.complete_analysis_csv)
            if result.complete_analysis_csv is not None
            else None,
            "complete_analysis_rows": result.complete_analysis_rows,
            "report_assets": _export_payload(artefact_export),
        }
        print(json.dumps(payload, indent=2))
        return 0

    colors = CliColors(
        resolve_color_mode(args.color),
        enabled=not bool(args.json_out),
    )
    _print_summary(result, colors=colors)
    if artefact_export is not None:
        _print_export_summary(artefact_export, colors=colors)
    if args.print_complete_analysis_table:
        _print_complete_analysis_table(
            result.complete_analysis_rows,
            style=str(args.complete_analysis_table_style),
            colors=colors,
        )
    if result.rows_complete < result.rows_total:
        print(
            "\n"
            + colors.warning(
                "Note: some points were incomplete and are marked in the summary table."
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
