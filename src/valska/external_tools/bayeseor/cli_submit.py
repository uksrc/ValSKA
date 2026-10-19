"""CLI entrypoint for submitting prepared BayesEoR runs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from valska.external_tools.common.submit import (
    InvalidArgumentError,
    MissingDependencyError,
    SbatchError,
    SubmissionError,
    submit_tool_run,
)
from valska.external_tools.common.utils import utc_now_compact

from ...cli_format import CliColors, add_color_argument, resolve_color_mode
from .submit import (
    BayesEoRRunOptions,
    BayesEoRSubmitPlan,
    _find_completed_cpu_precompute_matrix_dir,
)


def _load_runtime_paths_yaml() -> dict[str, Any]:
    """
    Load config/runtime_paths.yaml from package data if available.

    We deliberately keep this lightweight:
    - If ruamel.yaml isn't available, we return {} and rely on CLI defaults.
    - If the file isn't found (e.g. during some dev layouts), we return {}.
    """
    try:
        # Python 3.9+: importlib.resources.files
        from importlib.resources import files  # type: ignore
    except Exception:
        return {}

    try:
        runtime_path = files("valska").joinpath("config/runtime_paths.yaml")
    except Exception:
        return {}

    try:
        runtime_text = runtime_path.read_text(encoding="utf-8")
    except Exception:
        return {}

    try:
        from ruamel.yaml import YAML  # type: ignore
    except Exception:
        # Submission can still work without YAML; only defaults are missing.
        return {}

    try:
        y = YAML(typ="safe")
        data = y.load(runtime_text) or {}
        if not isinstance(data, dict):
            return {}
        return data
    except Exception:
        return {}


def _runtime_submit_defaults() -> dict[str, Any]:
    """Extract submit defaults from runtime_paths.yaml if available."""
    data = _load_runtime_paths_yaml()
    bayeseor = data.get("bayeseor", {}) if isinstance(data, dict) else {}
    submit = bayeseor.get("submit", {}) if isinstance(bayeseor, dict) else {}

    sbatch_exe = submit.get("sbatch_exe", None)
    record = submit.get("record", None)
    refuse = submit.get("refuse_if_jobs_exist", None)

    defaults: dict[str, Any] = {}
    if isinstance(sbatch_exe, str) and sbatch_exe.strip():
        defaults["sbatch_exe"] = sbatch_exe.strip()
    if isinstance(record, str) and record.strip():
        defaults["record"] = record.strip()
    if isinstance(refuse, bool):
        defaults["refuse_if_jobs_exist"] = refuse

    return defaults


def _build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser for valska-bayeseor-submit."""
    p = argparse.ArgumentParser(
        prog="valska-bayeseor-submit",
        description=(
            "Submit a previously prepared BayesEoR run directory.\n\n"
            "Reads an existing run_dir (manifest.json + submit scripts) and orchestrates sbatch submissions:\n"
            "  - CPU precompute\n"
            "  - GPU runs with afterok dependency on the CPU job\n\n"
            "Records job IDs to jobs.json by default."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )

    p.add_argument(
        "run_dir",
        type=str,
        help="Path to an existing prepared BayesEoR run directory (contains manifest.json).",
    )

    p.add_argument(
        "--stage",
        choices=["cpu", "gpu", "all"],
        default="all",
        help="Which stage(s) to submit. Default: all.",
    )

    p.add_argument(
        "--hypothesis",
        choices=["signal_fit", "no_signal", "both"],
        default="both",
        help="Which GPU hypothesis scripts to submit (only used if stage includes GPU). Default: both.",
    )

    p.add_argument(
        "--depend-afterok",
        dest="depend_afterok",
        default=None,
        help=(
            "Job ID to depend on for GPU submissions when not submitting CPU in this invocation.\n"
            "Example: --stage gpu --depend-afterok 12345"
        ),
    )

    # Defaults for these are filled from runtime_paths.yaml if present.
    p.add_argument(
        "--sbatch-exe",
        default=None,
        help="sbatch executable name/path. Default comes from config/runtime_paths.yaml (bayeseor.submit.sbatch_exe) or 'sbatch'.",
    )

    p.add_argument(
        "--record",
        choices=["jobs.json", "manifest"],
        default=None,
        help="Where to record job IDs. Default comes from config/runtime_paths.yaml (bayeseor.submit.record) or 'jobs.json'.",
    )

    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the sbatch commands that would be executed; do not submit jobs or write jobs.json.",
    )

    p.add_argument(
        "--force",
        action="store_true",
        help="Override guardrails (e.g. allow submission even if jobs.json already exists).",
    )

    # Resubmission convenience:
    # - If jobs.json exists, archive it then proceed (equivalent to --force + archive).
    # Useful when a job hit walltime: MultiNest can resume, and you don't lose the previous job record.
    p.add_argument(
        "--resubmit",
        action="store_true",
        help=(
            "Convenience flag for re-submission: if jobs.json exists, archive it (timestamped) then submit.\n"
            "Equivalent to --force plus archive. Useful if a previous run hit walltime and you want to requeue."
        ),
    )

    p.add_argument(
        "--no-archive-existing-jobs",
        action="store_true",
        help="With --resubmit, do not archive an existing jobs.json (it may be overwritten).",
    )

    p.add_argument(
        "--json",
        dest="json_out",
        action="store_true",
        help="Print the full result object as JSON to stdout (useful for scripting).",
    )
    add_color_argument(p)

    return p


def _archive_jobs_json(run_dir: Path) -> Path | None:
    """Archive jobs.json with a UTC timestamp suffix."""
    jobs_path = run_dir / "jobs.json"
    if not jobs_path.exists():
        return None
    archived = run_dir / f"jobs_{utc_now_compact()}.json"
    jobs_path.rename(archived)
    return archived


def _load_jobs_json(path: Path) -> dict[str, Any] | None:
    """
    Best-effort load of jobs.json. Returns None if missing or unreadable.
    """
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _has_cpu_job(existing: dict[str, Any] | None) -> bool:
    """Return True if jobs.json already records a CPU precompute job."""
    if not isinstance(existing, dict):
        return False
    jobs = existing.get("jobs")
    if not isinstance(jobs, dict):
        return False
    cpu = jobs.get("cpu_precompute")
    return isinstance(cpu, dict) and bool(cpu.get("job_id"))


def _has_gpu_jobs(existing: dict[str, Any] | None) -> bool:
    """Return True if jobs.json already records any GPU job."""
    if not isinstance(existing, dict):
        return False
    jobs = existing.get("jobs")
    if not isinstance(jobs, dict):
        return False
    gpu = jobs.get("gpu")
    if not isinstance(gpu, dict):
        return False
    sf = gpu.get("signal_fit")
    ns = gpu.get("no_signal")
    sf_ok = isinstance(sf, dict) and bool(sf.get("job_id"))
    ns_ok = isinstance(ns, dict) and bool(ns.get("job_id"))
    return sf_ok or ns_ok


def _print_summary(result: dict[str, Any], *, colors: CliColors) -> None:
    """Print a readable submission summary."""
    run_dir = result.get("run_dir", "")
    dry_run = bool(result.get("dry_run", False))

    print(f"Run dir: {colors.path(run_dir)}")
    dry_run_text = (
        colors.warning(dry_run) if dry_run else colors.success(dry_run)
    )
    print(f"Dry run: {dry_run_text}")

    print("\n" + colors.heading("Commands:"))
    for cmd in result.get("commands", []):
        print(f"  {cmd}")

    jobs = result.get("jobs", {}) or {}
    if not jobs:
        print("\n" + colors.warning("No jobs recorded."))
        return

    print("\n" + colors.heading("Job IDs:"))
    cpu = jobs.get("cpu_precompute")
    if isinstance(cpu, dict):
        jid = cpu.get("job_id")
        value = (
            colors.success(jid)
            if jid is not None
            else colors.warning("(dry-run)")
        )
        print(f"  CPU precompute: {value}")

    gpu = jobs.get("gpu")
    if isinstance(gpu, dict):
        dep = gpu.get("dependency")
        if dep:
            print(f"  GPU dependency: {dep}")

        sf = gpu.get("signal_fit")
        if isinstance(sf, dict):
            sf_id = sf.get("job_id")
            value = (
                colors.success(sf_id)
                if sf_id is not None
                else colors.warning("(dry-run)")
            )
            print(f"  signal_fit: {value}")

        ns = gpu.get("no_signal")
        if isinstance(ns, dict):
            ns_id = ns.get("job_id")
            value = (
                colors.success(ns_id)
                if ns_id is not None
                else colors.warning("(dry-run)")
            )
            print(f"  no_signal: {value}")

    if not dry_run:
        print("\n" + colors.heading("Recorded:"))
        print(f"  {colors.path(Path(run_dir) / 'jobs.json')}")

    print("\n" + colors.heading("Next steps:"))
    print("  - Check `squeue -u $USER` to see submitted jobs.")
    print(
        "  - Inspect logs referenced by the submit scripts in the run directory."
    )
    print(
        "  - If a job hits walltime, you can requeue with `--resubmit` (MultiNest should resume)."
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for valska-bayeseor-submit."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    colors = CliColors(
        resolve_color_mode(args.color), enabled=not bool(args.json_out)
    )

    run_dir = Path(args.run_dir).expanduser().resolve()
    jobs_path = run_dir / "jobs.json"

    # Apply runtime_paths.yaml defaults unless user explicitly provided CLI values.
    rt = _runtime_submit_defaults()

    sbatch_exe = (
        args.sbatch_exe
        if args.sbatch_exe is not None
        else rt.get("sbatch_exe", "sbatch")
    )
    record = (
        args.record
        if args.record is not None
        else rt.get("record", "jobs.json")
    )

    # Guardrail policy: default from YAML, but user can override with --force/--resubmit.
    refuse_if_jobs_exist = rt.get("refuse_if_jobs_exist", True)
    force = bool(args.force)

    # Load existing jobs.json (if any) so guardrails can be stage-aware.
    existing = _load_jobs_json(jobs_path)
    cpu_exists = _has_cpu_job(existing)
    gpu_exists = _has_gpu_jobs(existing)

    # Resubmit convenience: archive jobs.json + proceed.
    if args.resubmit:
        force = True
        if not args.no_archive_existing_jobs:
            try:
                archived = _archive_jobs_json(run_dir)
                if archived is not None and not args.dry_run:
                    print(
                        "Archived existing jobs.json -> "
                        f"{colors.path(archived)}"
                    )
                # After archiving, treat as no existing jobs record.
                existing = None
                cpu_exists = False
                gpu_exists = False
            except Exception as e:
                print(
                    f"ERROR: Failed to archive existing jobs.json: {e}",
                    file=sys.stderr,
                )
                return 1

    # Stage-aware guardrails.
    #
    # Normal, intended workflow is:
    #   1) submit --stage cpu  -> creates/updates jobs.json with cpu_precompute.job_id
    #   2) submit --stage gpu  -> reads cpu_precompute.job_id and appends gpu job ids
    #
    # Therefore:
    # - If stage=cpu and cpu job already recorded, refuse unless --force/--resubmit.
    # - If stage=gpu and gpu jobs already recorded, refuse unless --force/--resubmit.
    # - If stage=all and any jobs already recorded, refuse unless --force/--resubmit.
    #
    # Additionally, for the normal CPU->GPU progression, we auto-enable `force` when
    # jobs.json exists and contains a CPU job but no GPU jobs, so the submit layer is
    # allowed to read the recorded CPU job id and proceed without the user needing --force.
    if refuse_if_jobs_exist and not force and jobs_path.exists():
        if args.stage == "cpu":
            if cpu_exists:
                print(
                    "ERROR: jobs.json already records a CPU precompute job; refusing to submit CPU again.\n"
                    "Use --force to override, or --resubmit to archive and requeue.",
                    file=sys.stderr,
                )
                return 2
            # If jobs.json exists but does not record CPU, be conservative and refuse unless forced.
            print(
                "ERROR: jobs.json already exists; refusing to submit to avoid accidental double submission.\n"
                "Use --force to override, or --resubmit to archive and requeue.",
                file=sys.stderr,
            )
            return 2

        if args.stage == "gpu":
            if gpu_exists:
                print(
                    "ERROR: jobs.json already records GPU job IDs; refusing to submit GPU again.\n"
                    "Use --force to override, or --resubmit to archive and requeue.",
                    file=sys.stderr,
                )
                return 2
            if cpu_exists:
                # This is the normal continuation case; allow it and permit the submit layer to read CPU job id.
                force = True
            elif (
                args.depend_afterok is not None
                or _find_completed_cpu_precompute_matrix_dir(run_dir)
                is not None
            ):
                # Allow the submit layer to proceed when the user supplies an
                # explicit dependency or when CPU matrix outputs are already present.
                force = True
            else:
                # If we can't see a recorded CPU job id or completed CPU outputs,
                # refuse by default because GPU dependencies are unclear.
                print(
                    "ERROR: jobs.json exists but does not record a CPU precompute job id; refusing to submit GPU.\n"
                    "Either submit CPU first, pass --depend-afterok <JOBID>, wait for CPU precompute outputs to exist under run_dir/matrices/, or use --force/--resubmit as appropriate.",
                    file=sys.stderr,
                )
                return 2

        if args.stage == "all":
            print(
                "ERROR: jobs.json already exists; refusing to submit to avoid accidental double submission.\n"
                "Use --force to override, or --resubmit to archive and requeue.",
                file=sys.stderr,
            )
            return 2

    try:
        result = submit_tool_run(
            run_dir,
            stage_id=args.stage,
            submit_plan=BayesEoRSubmitPlan,
            options=BayesEoRRunOptions(
                hypothesis=args.hypothesis,
                depend_afterok=args.depend_afterok,
                sbatch_exe=sbatch_exe,
                dry_run=args.dry_run,
                force=force,
                record=record,
            ),
        )
    except MissingDependencyError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 3
    except SbatchError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 4
    except InvalidArgumentError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    except SubmissionError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130

    if args.json_out:
        print(json.dumps(result, indent=2))
    else:
        _print_summary(result, colors=colors)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
