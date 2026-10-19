"""Shared sweep health inspection for BayesEoR sweep directories."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SweepPointHealth:
    """Health summary for a single sweep point."""

    run_label: str
    perturb_parameter: str
    perturb_frac: float
    run_dir: str
    manifest_exists: bool
    jobs_exists: bool
    signal_chain_exists: bool
    no_signal_chain_exists: bool
    signal_stats_exists: bool
    no_signal_stats_exists: bool
    point_status: str
    notes: list[str]


@dataclass(frozen=True)
class SweepHealth:
    """Sweep-level health summary derived from sweep_manifest.json and point outputs."""

    sweep_dir: Path
    sweep_manifest_path: Path
    run_id: str | None
    beam_model: str | None
    sky_model: str | None
    created_utc: str | None
    points_total: int
    points_ok: int
    points_partial: int
    points_missing: int
    point_rows: list[SweepPointHealth]
    sweep_status: str
    messages: list[str]


def _safe_load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON is not an object: {path}")
    return payload


def _find_single_nested_dir(hypothesis_output_dir: Path) -> Path | None:
    if not hypothesis_output_dir.exists():
        return None
    dirs = sorted(p for p in hypothesis_output_dir.iterdir() if p.is_dir())
    if not dirs:
        return None
    if len(dirs) == 1:
        return dirs[0]
    return max(dirs, key=lambda p: p.stat().st_mtime)


def _bool_status(*, chain_exists: bool, stats_exists: bool) -> str:
    if chain_exists and stats_exists:
        return "ok"
    if chain_exists or stats_exists:
        return "partial"
    return "missing"


def inspect_sweep_health(sweep_dir: Path) -> SweepHealth:
    """Inspect a sweep directory and summarise point/sweep health."""
    sweep_dir = Path(sweep_dir).expanduser().resolve()
    manifest_path = sweep_dir / "sweep_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing sweep manifest: {manifest_path}")

    manifest = _safe_load_json(manifest_path)
    points = manifest.get("points", [])
    if not isinstance(points, list):
        raise ValueError("sweep_manifest.json has non-list 'points'")

    rows: list[SweepPointHealth] = []
    messages: list[str] = []

    n_ok = 0
    n_partial = 0
    n_missing = 0

    for idx, point in enumerate(points):
        if not isinstance(point, dict):
            messages.append(f"point[{idx}] is not an object")
            continue

        run_label = str(point.get("run_label", ""))
        perturb_parameter = str(point.get("perturb_parameter", "unknown"))
        perturb_frac = float(point.get("perturb_frac", 0.0))
        run_dir = Path(str(point.get("run_dir", ""))).expanduser().resolve()

        manifest_json = run_dir / "manifest.json"
        jobs_json = run_dir / "jobs.json"

        signal_dir = _find_single_nested_dir(run_dir / "output" / "signal_fit")
        no_signal_dir = _find_single_nested_dir(
            run_dir / "output" / "no_signal"
        )

        signal_chain = signal_dir / "data-.txt" if signal_dir else None
        no_signal_chain = (
            no_signal_dir / "data-.txt" if no_signal_dir else None
        )
        signal_stats = signal_dir / "data-stats.dat" if signal_dir else None
        no_signal_stats = (
            no_signal_dir / "data-stats.dat" if no_signal_dir else None
        )

        signal_chain_exists = bool(signal_chain and signal_chain.exists())
        no_signal_chain_exists = bool(
            no_signal_chain and no_signal_chain.exists()
        )
        signal_stats_exists = bool(signal_stats and signal_stats.exists())
        no_signal_stats_exists = bool(
            no_signal_stats and no_signal_stats.exists()
        )

        signal_status = _bool_status(
            chain_exists=signal_chain_exists,
            stats_exists=signal_stats_exists,
        )
        no_signal_status = _bool_status(
            chain_exists=no_signal_chain_exists,
            stats_exists=no_signal_stats_exists,
        )

        notes: list[str] = []
        if not manifest_json.exists():
            notes.append("missing point manifest.json")
        if not jobs_json.exists():
            notes.append("missing jobs.json")
        if signal_status != "ok":
            notes.append(f"signal_fit outputs {signal_status}")
        if no_signal_status != "ok":
            notes.append(f"no_signal outputs {no_signal_status}")

        if signal_status == "ok" and no_signal_status == "ok":
            point_status = "ok"
            n_ok += 1
        elif signal_status == "missing" and no_signal_status == "missing":
            point_status = "missing"
            n_missing += 1
        else:
            point_status = "partial"
            n_partial += 1

        rows.append(
            SweepPointHealth(
                run_label=run_label,
                perturb_parameter=perturb_parameter,
                perturb_frac=perturb_frac,
                run_dir=str(run_dir),
                manifest_exists=manifest_json.exists(),
                jobs_exists=jobs_json.exists(),
                signal_chain_exists=signal_chain_exists,
                no_signal_chain_exists=no_signal_chain_exists,
                signal_stats_exists=signal_stats_exists,
                no_signal_stats_exists=no_signal_stats_exists,
                point_status=point_status,
                notes=notes,
            )
        )

    rows.sort(key=lambda row: row.perturb_frac)

    if rows and n_ok == len(rows):
        sweep_status = "ok"
    elif rows and n_ok == 0 and n_partial == 0:
        sweep_status = "missing"
    else:
        sweep_status = "partial"

    if not rows:
        messages.append("sweep has no points")

    return SweepHealth(
        sweep_dir=sweep_dir,
        sweep_manifest_path=manifest_path,
        run_id=str(manifest.get("run_id")) if manifest.get("run_id") else None,
        beam_model=str(manifest.get("beam_model"))
        if manifest.get("beam_model")
        else None,
        sky_model=str(manifest.get("sky_model"))
        if manifest.get("sky_model")
        else None,
        created_utc=str(manifest.get("created_utc"))
        if manifest.get("created_utc")
        else None,
        points_total=len(rows),
        points_ok=n_ok,
        points_partial=n_partial,
        points_missing=n_missing,
        point_rows=rows,
        sweep_status=sweep_status,
        messages=messages,
    )


def sweep_health_to_dict(health: SweepHealth) -> dict[str, Any]:
    """Convert :class:`SweepHealth` dataclass to JSON-serializable dict."""
    payload = asdict(health)
    payload["sweep_dir"] = str(health.sweep_dir)
    payload["sweep_manifest_path"] = str(health.sweep_manifest_path)
    return payload


def validation_exit_code(
    health: SweepHealth,
    *,
    allow_partial: bool,
    require_jobs_json: bool,
) -> tuple[int, list[str]]:
    """Return process exit code and validation failures for a sweep health state."""
    failures: list[str] = []

    if health.points_total == 0:
        failures.append("No points present in sweep manifest")

    if health.sweep_status == "missing":
        failures.append("All sweep points are missing run outputs")

    if not allow_partial and health.sweep_status != "ok":
        failures.append(
            f"Sweep status is '{health.sweep_status}' (expected 'ok')"
        )

    if require_jobs_json:
        missing_jobs = [
            row.run_label for row in health.point_rows if not row.jobs_exists
        ]
        if missing_jobs:
            failures.append(
                "Missing jobs.json for points: " + ", ".join(missing_jobs)
            )

    return (0 if not failures else 1, failures)
