#!/usr/bin/env python3
"""Cleanup utility for BayesEoR sweep artefacts."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from valska.cli_format import (
    CliColors,
    add_color_argument,
    resolve_color_mode,
)
from valska.external_tools.common.utils import utc_now_compact
from valska.utils import get_default_path_manager

from .cli_list_sweeps import discover_sweeps
from .sweep_health import SweepPointHealth, inspect_sweep_health

_RUN_STATUS = {"ok", "partial", "missing", "any"}
_LOG_GLOBS = ["slurm-*.out", "*.log", "*.err", "*.stdout", "*.stderr"]
_TEMP_FILE_GLOBS = ["*.tmp", "*.bak", "*.old", "*.swp"]
_TEMP_NAMES = {"__pycache__", ".ipynb_checkpoints", "tmp", "temp", "scratch"}


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


def _is_older_than_days(
    path: Path, days: float | None, *, now_ts: float
) -> bool:
    if days is None:
        return True
    cutoff_seconds = float(days) * 86400.0
    age_seconds = now_ts - path.stat().st_mtime
    return age_seconds >= cutoff_seconds


def _safe_rel(path: Path, *, root: Path) -> Path:
    try:
        return path.resolve().relative_to(root.resolve())
    except Exception:
        return Path(path.name)


def _collect_log_candidates(run_dir: Path) -> list[Path]:
    out: list[Path] = []
    for pattern in _LOG_GLOBS:
        out.extend(p for p in run_dir.rglob(pattern) if p.is_file())
    return sorted(set(out))


def _collect_temp_candidates(run_dir: Path) -> list[Path]:
    out: list[Path] = []
    for pattern in _TEMP_FILE_GLOBS:
        out.extend(p for p in run_dir.rglob(pattern) if p.is_file())

    for p in run_dir.rglob("*"):
        if p.name in _TEMP_NAMES:
            out.append(p)

    return sorted(set(out))


def _plan_run_dir_candidate(
    *,
    row: SweepPointHealth,
    run_status: str,
    older_than_days: float | None,
    now_ts: float,
) -> tuple[bool, str]:
    if run_status not in _RUN_STATUS:
        return False, f"invalid run_status: {run_status}"

    if run_status != "any" and row.point_status != run_status:
        return (
            False,
            f"point_status={row.point_status} does not match {run_status}",
        )

    run_dir = Path(row.run_dir)
    if not run_dir.exists():
        return False, "run_dir missing"

    if not _is_older_than_days(run_dir, older_than_days, now_ts=now_ts):
        return False, "newer than older-than-days threshold"

    return True, "eligible"


def _move_to_trash(path: Path, *, trash_root: Path, rel_root: Path) -> Path:
    rel = _safe_rel(path, root=rel_root)
    target = trash_root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        suffix = utc_now_compact()
        target = target.with_name(f"{target.name}.{suffix}")
    shutil.move(str(path), str(target))
    return target


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="valska-bayeseor-cleanup",
        description=(
            "Cleanup BayesEoR sweep artefacts across discovered sweeps. "
            "Defaults to dry-run preview unless --execute is provided."
        ),
        epilog=(
            "Examples:\n"
            "  valska-bayeseor-cleanup --prune-logs\n"
            "  valska-bayeseor-cleanup --prune-temp --older-than-days 14\n"
            "  valska-bayeseor-cleanup --prune-runs --run-status missing --execute --confirm-runs DELETE\n"
            "  valska-bayeseor-cleanup --all --execute --confirm-runs DELETE --json"
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
    parser.add_argument("--run-id", type=str, default=None)
    parser.add_argument("--beam", type=str, default=None)
    parser.add_argument("--sky", type=str, default=None)
    parser.add_argument("--latest", action="store_true")
    parser.add_argument("--max-results", type=int, default=None)

    parser.add_argument("--prune-logs", action="store_true")
    parser.add_argument("--prune-temp", action="store_true")
    parser.add_argument("--prune-runs", action="store_true")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Enable all prune scopes: logs, temp, and runs.",
    )

    parser.add_argument(
        "--run-status",
        choices=sorted(_RUN_STATUS),
        default="missing",
        help=(
            "Run deletion status filter for --prune-runs (default: missing)."
        ),
    )
    parser.add_argument(
        "--older-than-days",
        type=float,
        default=None,
        help="Only include candidates older than this many days.",
    )

    parser.add_argument(
        "--execute",
        action="store_true",
        help="Apply cleanup actions (default is dry-run preview).",
    )
    parser.add_argument(
        "--confirm-runs",
        type=str,
        default="",
        help="Required literal token for --prune-runs with --execute: DELETE",
    )
    parser.add_argument(
        "--hard-delete",
        action="store_true",
        help="Permanently delete instead of moving to trash.",
    )
    parser.add_argument(
        "--trash-root",
        type=Path,
        default=None,
        help=(
            "Trash root for non-hard-delete mode "
            "(default: <results_root>/bayeseor/_trash_cleanup/<UTCSTAMP>)."
        ),
    )
    parser.add_argument(
        "--fail-on-error",
        action="store_true",
        help="Exit with code 1 if any action fails.",
    )
    parser.add_argument(
        "--json",
        dest="json_out",
        action="store_true",
        help="Print machine-readable JSON payload.",
    )
    add_color_argument(parser)
    return parser


def _format_status(status: object, *, colors: CliColors) -> str:
    text = str(status)
    if text in ("planned", "moved", "deleted"):
        return colors.success(text)
    if text == "skipped":
        return colors.warning(text)
    if text == "error":
        return colors.error(text)
    return text


def _print_text(payload: dict[str, Any], *, colors: CliColors) -> None:
    summary = payload["summary"]
    print(colors.heading("Sweep cleanup summary:"))
    mode = "execute" if payload["execute"] else "dry-run"
    print(
        "  mode:              "
        f"{colors.warning(mode) if payload['execute'] else colors.success(mode)}"
    )
    print(f"  results_root:      {colors.path(payload['results_root'])}")
    print(f"  sweeps_discovered: {summary['sweeps_discovered']}")
    print(f"  sweeps_targeted:   {summary['sweeps_targeted']}")
    print(f"  candidates_total:  {summary['candidates_total']}")
    print(f"  planned:           {colors.success(summary['planned_count'])}")
    print(f"  moved:             {colors.success(summary['moved_count'])}")
    print(f"  deleted:           {colors.success(summary['deleted_count'])}")
    print(f"  skipped:           {colors.warning(summary['skipped_count'])}")
    print(f"  errors:            {colors.error(summary['error_count'])}")

    if payload.get("trash_root") is not None:
        print(f"  trash_root:        {colors.path(payload['trash_root'])}")

    print("\n" + colors.heading("Actions:"))
    if not payload["actions"]:
        print("  (none)")
        return

    for row in payload["actions"]:
        line = (
            f"  - {row['scope']}: "
            f"{_format_status(row['status'], colors=colors)} "
            f"-> {colors.path(row['path'])}"
        )
        if row.get("target_path"):
            line += f" -> {colors.path(row['target_path'])}"
        print(line)
        if row.get("reason"):
            print(f"      reason: {colors.warning(row['reason'])}")


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

    prune_logs = bool(args.prune_logs)
    prune_temp = bool(args.prune_temp)
    prune_runs = bool(args.prune_runs)
    if args.all:
        prune_logs = True
        prune_temp = True
        prune_runs = True

    if not (prune_logs or prune_temp or prune_runs):
        print(
            "ERROR: no prune scope selected. Use --prune-logs/--prune-temp/--prune-runs or --all.",
            file=sys.stderr,
        )
        return 2

    if (
        args.execute
        and prune_runs
        and str(args.confirm_runs).strip() != "DELETE"
    ):
        print(
            "ERROR: --prune-runs with --execute requires --confirm-runs DELETE",
            file=sys.stderr,
        )
        return 2

    execute = bool(args.execute)

    trash_root: Path | None = None
    if execute and not bool(args.hard_delete):
        if args.trash_root is not None:
            trash_root = Path(args.trash_root).expanduser().resolve()
        else:
            trash_root = (
                results_root
                / "bayeseor"
                / "_trash_cleanup"
                / utc_now_compact()
            ).resolve()

    entries = discover_sweeps(results_root)
    filtered = _apply_filters(
        entries,
        run_id=args.run_id,
        beam=args.beam,
        sky=args.sky,
        latest=bool(args.latest),
        max_results=args.max_results,
    )

    now_ts = datetime.now(UTC).timestamp()
    actions: list[dict[str, Any]] = []

    planned = 0
    moved = 0
    deleted = 0
    skipped = 0
    errors = 0

    run_dirs_selected_for_removal: set[Path] = set()

    for item in filtered:
        sweep_dir = Path(str(item["sweep_dir"]))
        try:
            health = inspect_sweep_health(sweep_dir)
        except Exception as exc:
            errors += 1
            actions.append(
                {
                    "scope": "sweep",
                    "status": "error",
                    "path": str(sweep_dir),
                    "target_path": None,
                    "reason": str(exc),
                    "run_id": item.get("run_id"),
                }
            )
            continue

        for row in health.point_rows:
            run_dir = Path(row.run_dir)
            if not run_dir.exists():
                continue

            if prune_runs:
                include, reason = _plan_run_dir_candidate(
                    row=row,
                    run_status=str(args.run_status),
                    older_than_days=args.older_than_days,
                    now_ts=now_ts,
                )
                if include:
                    run_dirs_selected_for_removal.add(run_dir.resolve())
                    actions.append(
                        {
                            "scope": "run_dir",
                            "status": "planned" if not execute else None,
                            "path": str(run_dir),
                            "target_path": None,
                            "reason": f"point_status={row.point_status}",
                            "run_id": health.run_id,
                            "run_label": row.run_label,
                            "point_status": row.point_status,
                        }
                    )
                    planned += 1
                else:
                    skipped += 1
                    actions.append(
                        {
                            "scope": "run_dir",
                            "status": "skipped",
                            "path": str(run_dir),
                            "target_path": None,
                            "reason": reason,
                            "run_id": health.run_id,
                            "run_label": row.run_label,
                            "point_status": row.point_status,
                        }
                    )

    for item in filtered:
        sweep_dir = Path(str(item["sweep_dir"]))
        try:
            health = inspect_sweep_health(sweep_dir)
        except Exception:
            continue

        for row in health.point_rows:
            run_dir = Path(row.run_dir)
            if not run_dir.exists():
                continue
            if run_dir.resolve() in run_dirs_selected_for_removal:
                continue

            if prune_logs:
                for p in _collect_log_candidates(run_dir):
                    if not _is_older_than_days(
                        p, args.older_than_days, now_ts=now_ts
                    ):
                        continue
                    planned += 1
                    actions.append(
                        {
                            "scope": "log",
                            "status": "planned" if not execute else None,
                            "path": str(p),
                            "target_path": None,
                            "reason": None,
                            "run_id": health.run_id,
                            "run_label": row.run_label,
                            "point_status": row.point_status,
                        }
                    )

            if prune_temp:
                for p in _collect_temp_candidates(run_dir):
                    if not _is_older_than_days(
                        p, args.older_than_days, now_ts=now_ts
                    ):
                        continue
                    planned += 1
                    actions.append(
                        {
                            "scope": "temp",
                            "status": "planned" if not execute else None,
                            "path": str(p),
                            "target_path": None,
                            "reason": None,
                            "run_id": health.run_id,
                            "run_label": row.run_label,
                            "point_status": row.point_status,
                        }
                    )

    if execute:
        for action in actions:
            if (
                action.get("status") == "skipped"
                or action.get("status") == "error"
            ):
                continue
            p = Path(str(action["path"]))
            if not p.exists():
                action["status"] = "skipped"
                action["reason"] = "already missing"
                skipped += 1
                continue

            try:
                if bool(args.hard_delete):
                    if p.is_dir():
                        shutil.rmtree(p)
                    else:
                        p.unlink()
                    action["status"] = "deleted"
                    deleted += 1
                else:
                    assert trash_root is not None
                    target = _move_to_trash(
                        p,
                        trash_root=trash_root,
                        rel_root=(results_root / "bayeseor"),
                    )
                    action["status"] = "moved"
                    action["target_path"] = str(target)
                    moved += 1
            except Exception as exc:
                action["status"] = "error"
                action["reason"] = str(exc)
                errors += 1

    payload = {
        "results_root": str(results_root),
        "execute": execute,
        "hard_delete": bool(args.hard_delete),
        "trash_root": str(trash_root) if trash_root is not None else None,
        "settings": {
            "run_id": args.run_id,
            "beam": args.beam,
            "sky": args.sky,
            "latest": bool(args.latest),
            "max_results": args.max_results,
            "prune_logs": prune_logs,
            "prune_temp": prune_temp,
            "prune_runs": prune_runs,
            "run_status": str(args.run_status),
            "older_than_days": args.older_than_days,
        },
        "summary": {
            "sweeps_discovered": len(entries),
            "sweeps_targeted": len(filtered),
            "candidates_total": len(actions),
            "planned_count": planned,
            "moved_count": moved,
            "deleted_count": deleted,
            "skipped_count": skipped,
            "error_count": errors,
        },
        "actions": actions,
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
