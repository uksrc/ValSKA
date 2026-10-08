#!/usr/bin/env python3
"""Discover sweeps and run status/validation checks in one command."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from valska.cli_format import (
    CliColors,
    add_color_argument,
    resolve_color_mode,
)
from valska.utils import get_default_path_manager

from .cli_list_sweeps import discover_sweeps
from .sweep_health import inspect_sweep_health, validation_exit_code


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="valska-bayeseor-sweep-audit",
        description=(
            "Discover sweeps and run status/validation checks per sweep "
            "(list + status + validate in one command)."
        ),
        epilog=(
            "Examples:\n"
            "  valska-bayeseor-sweep-audit\n"
            "  valska-bayeseor-sweep-audit --beam airy_diam14m --sky GSM_plus_GLEAM\n"
            "  valska-bayeseor-sweep-audit --latest --json\n"
            "  valska-bayeseor-sweep-audit --fail-on-invalid"
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
        help="Audit only the latest sweep after applying filters.",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=None,
        help="Limit number of sweeps to audit.",
    )
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Validation policy: accept partial sweeps.",
    )
    parser.add_argument(
        "--require-jobs-json",
        action="store_true",
        help="Validation policy: require jobs.json in all points.",
    )
    parser.add_argument(
        "--fail-on-invalid",
        action="store_true",
        help="Exit with code 1 if any audited sweep fails validation.",
    )
    parser.add_argument(
        "--json",
        dest="json_out",
        action="store_true",
        help="Print machine-readable JSON output.",
    )
    add_color_argument(parser)
    return parser


def _audit_entries(
    entries: list[dict[str, Any]],
    *,
    allow_partial: bool,
    require_jobs_json: bool,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in entries:
        sweep_dir = Path(str(item["sweep_dir"]))
        record: dict[str, Any] = {
            "sweep_dir": str(sweep_dir),
            "run_id": item.get("run_id"),
            "beam_model": item.get("beam_model"),
            "sky_model": item.get("sky_model"),
            "created_utc": item.get("created_utc"),
        }

        try:
            health = inspect_sweep_health(sweep_dir)
            exit_code, failures = validation_exit_code(
                health,
                allow_partial=allow_partial,
                require_jobs_json=require_jobs_json,
            )
            record.update(
                {
                    "sweep_status": health.sweep_status,
                    "points_total": health.points_total,
                    "points_ok": health.points_ok,
                    "points_partial": health.points_partial,
                    "points_missing": health.points_missing,
                    "validation_exit_code": exit_code,
                    "validation_failures": failures,
                    "error": None,
                }
            )
        except Exception as exc:
            record.update(
                {
                    "sweep_status": "error",
                    "points_total": 0,
                    "points_ok": 0,
                    "points_partial": 0,
                    "points_missing": 0,
                    "validation_exit_code": 2,
                    "validation_failures": ["Could not inspect sweep health"],
                    "error": str(exc),
                }
            )

        out.append(record)
    return out


def _build_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts: dict[str, int] = {
        "ok": 0,
        "partial": 0,
        "missing": 0,
        "error": 0,
    }
    invalid_count = 0

    for row in rows:
        status = str(row.get("sweep_status", "error"))
        status_counts[status] = status_counts.get(status, 0) + 1
        if int(row.get("validation_exit_code", 1)) != 0:
            invalid_count += 1

    return {
        "count": len(rows),
        "status_counts": status_counts,
        "invalid_count": invalid_count,
    }


def _format_status(status: object, *, colors: CliColors) -> str:
    text = str(status)
    if text == "ok":
        return colors.success(text)
    if text == "partial":
        return colors.warning(text)
    if text in ("missing", "invalid", "error"):
        return colors.error(text)
    return text


def _format_validation(exit_code: object, *, colors: CliColors) -> str:
    text = str(exit_code)
    return colors.success(text) if text == "0" else colors.error(text)


def _print_text(
    results_root: Path, rows: list[dict[str, Any]], *, colors: CliColors
) -> None:
    summary = _build_summary(rows)
    print(colors.heading("Sweep audit summary:"))
    print(f"  results_root: {colors.path(results_root)}")
    print(f"  sweeps:       {summary['count']}")
    print(
        "  status:       "
        f"ok={colors.success(summary['status_counts'].get('ok', 0))}, "
        f"partial={colors.warning(summary['status_counts'].get('partial', 0))}, "
        f"missing={colors.error(summary['status_counts'].get('missing', 0))}, "
        f"error={colors.error(summary['status_counts'].get('error', 0))}"
    )
    print(f"  invalid:      {colors.error(summary['invalid_count'])}")

    print("\n" + colors.heading("Per-sweep:"))
    if not rows:
        print("  (none)")
        return

    for row in rows:
        status = _format_status(row.get("sweep_status"), colors=colors)
        validation = _format_validation(
            row.get("validation_exit_code"), colors=colors
        )
        print(
            "  - "
            f"{row.get('run_id') or '(unknown)'} "
            f"[{row.get('beam_model')}/{row.get('sky_model')}] "
            f"=> {status} "
            f"(validate={validation})"
        )
        print(
            "      points: "
            f"total={row.get('points_total')}, "
            f"ok={colors.success(row.get('points_ok'))}, "
            f"partial={colors.warning(row.get('points_partial'))}, "
            f"missing={colors.error(row.get('points_missing'))}"
        )
        if row.get("validation_failures"):
            print(
                "      failures: "
                + colors.error(
                    "; ".join(str(x) for x in row["validation_failures"])
                )
            )
        if row.get("error"):
            print(f"      error: {colors.error(row['error'])}")
        print(f"      dir: {colors.path(row.get('sweep_dir'))}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

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

    entries = discover_sweeps(results_root)
    filtered = _apply_filters(
        entries,
        run_id=args.run_id,
        beam=args.beam,
        sky=args.sky,
        latest=bool(args.latest),
        max_results=args.max_results,
    )

    rows = _audit_entries(
        filtered,
        allow_partial=bool(args.allow_partial),
        require_jobs_json=bool(args.require_jobs_json),
    )
    summary = _build_summary(rows)

    if args.json_out:
        print(
            json.dumps(
                {
                    "results_root": str(results_root),
                    "validation_policy": {
                        "allow_partial": bool(args.allow_partial),
                        "require_jobs_json": bool(args.require_jobs_json),
                    },
                    "summary": summary,
                    "sweeps": rows,
                },
                indent=2,
            )
        )
    else:
        colors = CliColors(
            resolve_color_mode(args.color), enabled=not bool(args.json_out)
        )
        _print_text(results_root, rows, colors=colors)

    if args.fail_on_invalid and int(summary["invalid_count"]) > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
