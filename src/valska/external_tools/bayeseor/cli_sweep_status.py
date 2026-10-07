#!/usr/bin/env python3
"""Show health/status summary for a BayesEoR sweep directory."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from valska.cli_format import (
    CliColors,
    add_color_argument,
    resolve_color_mode,
)

from .sweep_health import inspect_sweep_health, sweep_health_to_dict


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="valska-bayeseor-sweep-status",
        description=(
            "Inspect one sweep directory and summarise per-point output health."
        ),
        epilog=(
            "Examples:\n"
            "  valska-bayeseor-sweep-status /path/to/_sweeps/sweep_airy_init\n"
            "  valska-bayeseor-sweep-status /path/to/_sweeps/sweep_airy_init --show-notes\n"
            "  valska-bayeseor-sweep-status /path/to/_sweeps/sweep_airy_init --json"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "sweep_dir",
        type=Path,
        help="Path to sweep directory containing sweep_manifest.json.",
    )
    parser.add_argument(
        "--json",
        dest="json_out",
        action="store_true",
        help="Print machine-readable JSON payload.",
    )
    parser.add_argument(
        "--show-notes",
        action="store_true",
        help="Include per-point note details in text output.",
    )
    add_color_argument(parser)
    return parser


def _format_status(status: object, *, colors: CliColors) -> str:
    text = str(status)
    if text == "ok":
        return colors.success(text)
    if text == "partial":
        return colors.warning(text)
    if text in ("missing", "invalid", "error"):
        return colors.error(text)
    return text


def _print_text(*, health, show_notes: bool, colors: CliColors) -> None:
    print(colors.heading("Sweep status summary:"))
    print(f"  sweep_dir:      {colors.path(health.sweep_dir)}")
    print(f"  sweep_manifest: {colors.path(health.sweep_manifest_path)}")
    if health.run_id is not None:
        print(f"  run_id:         {health.run_id}")
    if health.beam_model is not None:
        print(f"  beam_model:     {health.beam_model}")
    if health.sky_model is not None:
        print(f"  sky_model:      {health.sky_model}")
    print(
        f"  sweep_status:   "
        f"{_format_status(health.sweep_status, colors=colors)}"
    )
    print(f"  points_total:   {health.points_total}")
    print(f"  points_ok:      {colors.success(health.points_ok)}")
    print(f"  points_partial: {colors.warning(health.points_partial)}")
    print(f"  points_missing: {colors.error(health.points_missing)}")

    if health.messages:
        print(colors.heading("  messages:"))
        for msg in health.messages:
            print(f"    - {colors.warning(msg)}")

    print("\n" + colors.heading("Per-point:"))
    if not health.point_rows:
        print("  (none)")
        return

    for row in health.point_rows:
        point_status = _format_status(row.point_status, colors=colors)
        print(
            "  - "
            f"{row.run_label} "
            f"({row.perturb_parameter}={row.perturb_frac:+.3f}) "
            f"=> {point_status}"
        )
        if show_notes and row.notes:
            for note in row.notes:
                print(f"      note: {colors.warning(note)}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        health = inspect_sweep_health(Path(args.sweep_dir))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json_out:
        print(json.dumps(sweep_health_to_dict(health), indent=2))
        return 0

    colors = CliColors(
        resolve_color_mode(args.color), enabled=not bool(args.json_out)
    )
    _print_text(health=health, show_notes=bool(args.show_notes), colors=colors)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
