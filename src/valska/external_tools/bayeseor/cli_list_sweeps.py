#!/usr/bin/env python3
"""List available ValSKA BayesEoR sweep directories."""

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


def _safe_load_manifest(manifest_path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _entry_from_manifest(manifest_path: Path) -> dict[str, Any]:
    manifest = _safe_load_manifest(manifest_path)
    sweep_dir = manifest_path.parent.resolve()

    run_id = manifest.get("run_id")
    beam_model = manifest.get("beam_model")
    sky_model = manifest.get("sky_model")
    created_utc = manifest.get("created_utc")

    if not run_id:
        parts = sweep_dir.parts
        if "_sweeps" in parts:
            idx = parts.index("_sweeps")
            if idx + 1 < len(parts):
                run_id = parts[idx + 1]

    return {
        "sweep_dir": str(sweep_dir),
        "run_id": str(run_id) if run_id else None,
        "beam_model": str(beam_model) if beam_model else None,
        "sky_model": str(sky_model) if sky_model else None,
        "created_utc": str(created_utc) if created_utc else None,
    }


def discover_sweeps(results_root: Path) -> list[dict[str, Any]]:
    search_root = results_root / "bayeseor"
    manifests = sorted(search_root.rglob("sweep_manifest.json"))
    return [_entry_from_manifest(path) for path in manifests]


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
        prog="valska-bayeseor-list-sweeps",
        description=(
            "Discover BayesEoR sweep directories by locating "
            "sweep_manifest.json under <results_root>/bayeseor."
        ),
        epilog=(
            "Examples:\n"
            "  valska-bayeseor-list-sweeps\n"
            "  valska-bayeseor-list-sweeps --beam airy_diam14m --sky GSM_plus_GLEAM\n"
            "  valska-bayeseor-list-sweeps --latest --json"
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
        help="Return only the latest sweep after applying filters.",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=None,
        help="Limit number of returned sweeps.",
    )
    parser.add_argument(
        "--json",
        dest="json_out",
        action="store_true",
        help="Print machine-readable JSON payload.",
    )
    add_color_argument(parser)
    return parser


def _print_text(
    results_root: Path, entries: list[dict[str, Any]], *, colors: CliColors
) -> None:
    print(f"{colors.heading('Results root:')} {colors.path(results_root)}")
    print(colors.heading("Sweep directories:"))
    if not entries:
        print("  (none found)")
        return

    for item in entries:
        print(f"  - {colors.path(item['sweep_dir'])}")
        print(f"      run_id: {item.get('run_id')}")
        if item.get("beam_model") is not None:
            print(f"      beam: {item['beam_model']}")
        if item.get("sky_model") is not None:
            print(f"      sky: {item['sky_model']}")
        if item.get("created_utc") is not None:
            print(f"      created_utc: {item['created_utc']}")


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

    if args.json_out:
        payload = {
            "results_root": str(results_root),
            "count": len(filtered),
            "sweeps": filtered,
        }
        print(json.dumps(payload, indent=2))
        return 0

    colors = CliColors(
        resolve_color_mode(args.color), enabled=not bool(args.json_out)
    )
    _print_text(results_root, filtered, colors=colors)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
