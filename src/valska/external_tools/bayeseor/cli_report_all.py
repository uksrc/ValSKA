#!/usr/bin/env python3
"""Generate BayesEoR reports for all discovered sweeps."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from valska.cli_format import (
    CliColors,
    add_color_argument,
    add_progress_argument,
    resolve_color_mode,
    resolve_progress_mode,
    show_progress,
)
from valska.utils import get_default_path_manager

from .cli_list_sweeps import discover_sweeps
from .plot_configs import resolve_analysis_plot_config_path
from .report import SweepReportResult, generate_sweep_report
from .valska_bayeseor_plotting import BayesEoRPlotConfig


def _apply_filters(
    entries: list[dict[str, Any]],
    *,
    run_id: str | None,
    beam: str | None,
    sky: str | None,
    latest: bool,
    max_results: int | None,
) -> list[dict[str, Any]]:
    out = entries

    if run_id:
        out = [
            item
            for item in out
            if item.get("run_id") and run_id in str(item["run_id"])
        ]
    if beam:
        out = [
            item
            for item in out
            if item.get("beam_model") and beam in str(item["beam_model"])
        ]
    if sky:
        out = [
            item
            for item in out
            if item.get("sky_model") and sky in str(item["sky_model"])
        ]

    if latest and out:
        dated = [item for item in out if item.get("created_utc")]
        if dated:
            newest = max(dated, key=lambda item: str(item["created_utc"]))
            out = [newest]
        else:
            out = [out[-1]]

    if max_results is not None and max_results >= 0:
        out = out[:max_results]

    return out


def _resolve_out_dir(
    *,
    sweep_dir: Path,
    results_root: Path,
    out_root: Path | None,
) -> Path | None:
    if out_root is None:
        return None

    search_root = (results_root / "bayeseor").resolve()
    sweep_dir = sweep_dir.resolve()
    try:
        relative = sweep_dir.relative_to(search_root)
    except Exception:
        relative = Path(sweep_dir.name)
    return out_root / relative


def _summary_exists(out_dir: Path | None, sweep_dir: Path) -> bool:
    target = out_dir if out_dir is not None else (sweep_dir / "report")
    return (target / "sweep_report_summary.json").exists()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="valska-bayeseor-report-all",
        description=(
            "Discover sweeps under results_root and run "
            "valska-bayeseor-report for each sweep."
        ),
        epilog=(
            "Examples:\n"
            "  valska-bayeseor-report-all\n"
            "  valska-bayeseor-report-all --beam airy_diam14m --sky GSM_plus_GLEAM\n"
            "  valska-bayeseor-report-all --only-new --json"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--results-root",
        type=Path,
        default=None,
        help=(
            "Override results root (default: ValSKA path manager results_root)."
        ),
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default=None,
        help="Filter by run_id substring.",
    )
    parser.add_argument(
        "--beam",
        type=str,
        default=None,
        help="Filter by beam_model substring.",
    )
    parser.add_argument(
        "--sky",
        type=str,
        default=None,
        help="Filter by sky_model substring.",
    )
    parser.add_argument(
        "--latest",
        action="store_true",
        help="Process only the latest sweep after applying filters.",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=None,
        help="Limit number of sweeps to process.",
    )
    parser.add_argument(
        "--out-root",
        type=Path,
        default=None,
        help=(
            "Optional output root. When set, reports are written under "
            "<out_root>/<beam>/<sky>/_sweeps/<run_id>."
        ),
    )
    parser.add_argument(
        "--only-new",
        action="store_true",
        help="Skip sweeps that already have sweep_report_summary.json.",
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
        "--include-complete-analysis-table",
        action="store_true",
        help=(
            "Also run run_complete_bayeseor_analysis across complete points "
            "and write summary table/json outputs."
        ),
    )
    parser.add_argument(
        "--fail-on-error",
        action="store_true",
        help="Exit with code 1 if any sweep report generation fails.",
    )
    parser.add_argument(
        "--json",
        dest="json_out",
        action="store_true",
        help="Print machine-readable JSON output.",
    )
    add_progress_argument(parser)
    add_color_argument(parser)
    return parser


def _result_to_payload(result: SweepReportResult) -> dict[str, Any]:
    return {
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
        "complete_analysis_json": str(result.complete_analysis_json)
        if result.complete_analysis_json is not None
        else None,
        "complete_analysis_csv": str(result.complete_analysis_csv)
        if result.complete_analysis_csv is not None
        else None,
        "complete_analysis_rows": result.complete_analysis_rows,
    }


def _format_status(status: object, *, colors: CliColors) -> str:
    text = str(status)
    if text == "generated":
        return colors.success(text)
    if text == "skipped":
        return colors.warning(text)
    if text == "error":
        return colors.error(text)
    return text


def _print_text(payload: dict[str, Any], *, colors: CliColors) -> None:
    summary = payload["summary"]
    print(colors.heading("Sweep batch report summary:"))
    print(f"  results_root: {colors.path(payload['results_root'])}")
    print(f"  discovered:   {summary['count_discovered']}")
    print(f"  targeted:     {summary['count_targeted']}")
    print(f"  generated:    {colors.success(summary['count_generated'])}")
    print(f"  skipped:      {colors.warning(summary['count_skipped'])}")
    print(f"  errors:       {colors.error(summary['count_errors'])}")

    print("\n" + colors.heading("Per-sweep:"))
    if not payload["sweeps"]:
        print("  (none)")
        return

    for row in payload["sweeps"]:
        status = _format_status(row["status"], colors=colors)
        print(
            "  - "
            f"{row.get('run_id') or '(unknown)'} "
            f"[{row.get('beam_model')}/{row.get('sky_model')}] "
            f"=> {status}"
        )
        print(f"      dir: {colors.path(row['sweep_dir'])}")
        if row.get("out_dir") is not None:
            print(f"      out: {colors.path(row['out_dir'])}")
        if row.get("summary_json") is not None:
            print(f"      summary_json: {colors.path(row['summary_json'])}")
        if row.get("error") is not None:
            print(f"      error: {colors.error(row['error'])}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        plot_config_path = None
        plot_config = None
        if bool(args.include_plot_analysis_results):
            plot_config_path = resolve_analysis_plot_config_path(
                args.plot_config
            )
            plot_config = BayesEoRPlotConfig.from_yaml(plot_config_path)
    except Exception as exc:
        print(f"ERROR: failed to load plot config: {exc}", file=sys.stderr)
        return 2

    try:
        results_root = (
            Path(args.results_root).expanduser().resolve()
            if args.results_root is not None
            else Path(get_default_path_manager().results_root).resolve()
        )
    except Exception as exc:
        print(f"ERROR: failed to resolve results root: {exc}", file=sys.stderr)
        return 2

    search_root = results_root / "bayeseor"
    if not search_root.exists():
        print(
            f"ERROR: search root does not exist: {search_root}",
            file=sys.stderr,
        )
        return 2

    out_root = (
        Path(args.out_root).expanduser().resolve()
        if args.out_root is not None
        else None
    )

    entries = discover_sweeps(results_root)
    filtered = _apply_filters(
        entries,
        run_id=args.run_id,
        beam=args.beam,
        sky=args.sky,
        latest=bool(args.latest),
        max_results=args.max_results,
    )

    rows: list[dict[str, Any]] = []
    generated = 0
    skipped = 0
    errors = 0

    for item in filtered:
        sweep_dir = Path(str(item["sweep_dir"]))
        run_out_dir = _resolve_out_dir(
            sweep_dir=sweep_dir,
            results_root=results_root,
            out_root=out_root,
        )

        row: dict[str, Any] = {
            "sweep_dir": str(sweep_dir),
            "run_id": item.get("run_id"),
            "beam_model": item.get("beam_model"),
            "sky_model": item.get("sky_model"),
            "created_utc": item.get("created_utc"),
            "out_dir": str(run_out_dir) if run_out_dir is not None else None,
            "status": None,
            "error": None,
            "summary_json": None,
            "result": None,
        }

        if args.only_new and _summary_exists(run_out_dir, sweep_dir):
            row["status"] = "skipped"
            skipped += 1
            rows.append(row)
            continue

        try:
            result = generate_sweep_report(
                sweep_dir=sweep_dir,
                out_dir=run_out_dir,
                evidence_source=args.evidence_source,
                make_plots=not bool(args.no_plots),
                include_plot_analysis_results=bool(
                    args.include_plot_analysis_results
                ),
                include_complete_analysis_table=bool(
                    args.include_complete_analysis_table
                ),
                plot_config=plot_config,
                show_progress=show_progress(
                    resolve_progress_mode(args.progress),
                    json_out=bool(args.json_out),
                ),
            )
            row["status"] = "generated"
            row["out_dir"] = str(result.out_dir)
            row["summary_json"] = str(result.summary_json)
            row["result"] = _result_to_payload(result)
            generated += 1
        except Exception as exc:
            row["status"] = "error"
            row["error"] = str(exc)
            errors += 1

        rows.append(row)

    payload = {
        "results_root": str(results_root),
        "summary": {
            "count_discovered": len(entries),
            "count_targeted": len(filtered),
            "count_generated": generated,
            "count_skipped": skipped,
            "count_errors": errors,
        },
        "settings": {
            "run_id": args.run_id,
            "beam": args.beam,
            "sky": args.sky,
            "latest": bool(args.latest),
            "max_results": args.max_results,
            "out_root": str(out_root) if out_root is not None else None,
            "only_new": bool(args.only_new),
            "evidence_source": args.evidence_source,
            "make_plots": not bool(args.no_plots),
            "include_plot_analysis_results": bool(
                args.include_plot_analysis_results
            ),
            "plot_config": str(plot_config_path)
            if plot_config_path is not None
            else None,
            "include_complete_analysis_table": bool(
                args.include_complete_analysis_table
            ),
        },
        "sweeps": rows,
    }

    if args.json_out:
        print(json.dumps(payload, indent=2))
    else:
        colors = CliColors(
            resolve_color_mode(args.color), enabled=not bool(args.json_out)
        )
        _print_text(payload, colors=colors)

    if bool(args.fail_on_error) and errors > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
