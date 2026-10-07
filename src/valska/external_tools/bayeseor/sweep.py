"""Sweep orchestration for BayesEoR perturbation studies."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from valska.external_tools.common.utils import (
    archive_timestamped,
    array_spec,
    extract_numeric_job_id,
    is_numeric_job_id,
    load_json_object,
    utc_now_compact,
    utc_now_iso,
    write_json_object,
)

from .runner import BayesEoRInstall, CondaRunner, ContainerRunner
from .setup import prepare_bayeseor_run
from .slurm import render_array_submit_script
from .submit import (
    InvalidArgumentError,
    MissingDependencyError,
    SubmissionError,
    _run_sbatch,
    submit_bayeseor_run,
)

_STAGE = Literal["none", "cpu", "gpu", "all"]
_HYP = Literal["signal_fit", "no_signal", "both"]
_PERT = Literal["fwhm_deg", "antenna_diameter"]
_SUBMIT_MODE = Literal["per-point", "array"]

_DRY_RUN_CPU_ARRAY_JOB_ID = "DRY_RUN_CPU_ARRAY_JOB_ID"
_DRY_RUN_SIGNAL_FIT_GPU_ARRAY_JOB_ID = "DRY_RUN_SIGNAL_FIT_GPU_ARRAY_JOB_ID"
_DRY_RUN_NO_SIGNAL_GPU_ARRAY_JOB_ID = "DRY_RUN_NO_SIGNAL_GPU_ARRAY_JOB_ID"


def _format_run_label_from_fwhm_frac(frac: float) -> str:
    """
    Must match cli_prepare.py formatting so directory layout is predictable.
    """
    s = f"{frac:+.1e}"
    if s.startswith("+"):
        s = s[1:]
    return f"fwhm_{s}"


def _format_run_label_from_antenna_diameter_frac(frac: float) -> str:
    """
    Must match cli_prepare.py formatting so directory layout is predictable.
    """
    s = f"{frac:+.1e}"
    if s.startswith("+"):
        s = s[1:]
    return f"antdiam_{s}"


def _format_run_label(*, perturb_parameter: _PERT, frac: float) -> str:
    if perturb_parameter == "fwhm_deg":
        return _format_run_label_from_fwhm_frac(frac)
    return _format_run_label_from_antenna_diameter_frac(frac)


def _default_fwhm_fracs() -> list[float]:
    return [-0.10, -0.05, -0.02, -0.01, 0.0, 0.01, 0.02, 0.05, 0.10]


def sweep_root(
    results_root: Path, beam_model: str, sky_model: str, run_id: str
) -> Path:
    """
    Central sweep output location.

    Layout:
      <results_root>/bayeseor/<beam_model>/<sky_model>/_sweeps/<run_id>/
    """
    return (
        results_root / "bayeseor" / beam_model / sky_model / "_sweeps" / run_id
    )


def sweep_point_dir(
    results_root: Path,
    beam_model: str,
    sky_model: str,
    run_id: str,
    *,
    variant: str,
    run_label: str,
) -> Path:
    """
    Per-point run directory for sweeps.

    Layout:
      <results_root>/bayeseor/<beam_model>/<sky_model>/_sweeps/<run_id>/<variant>/<run_label>/
    """
    return (
        sweep_root(results_root, beam_model, sky_model, run_id)
        / variant
        / run_label
    )


def _jobs_path(run_dir: Path) -> Path:
    return run_dir / "jobs.json"


def _sweep_jobs_path(sweep_dir: Path) -> Path:
    return sweep_dir / "jobs.json"


def archive_jobs_json(run_dir: Path) -> Path | None:
    """
    Archive run_dir/jobs.json -> run_dir/jobs_<UTCSTAMP>.json

    Returns the archived path if an archive was created, else None.
    """
    jp = _jobs_path(run_dir)
    if not jp.exists():
        return None
    return archive_timestamped(jp)


def archive_sweep_jobs_json(sweep_dir: Path) -> Path | None:
    """Archive sweep_dir/jobs.json -> sweep_dir/jobs_<UTCSTAMP>.json."""
    jp = _sweep_jobs_path(sweep_dir)
    return archive_timestamped(jp)


def _merge_sweep_jobs_record(
    existing: dict[str, Any] | None,
    new_result: dict[str, Any],
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    if isinstance(existing, dict):
        merged.update(existing)

    for key in (
        "sweep_dir",
        "manifest",
        "submit_mode",
        "array_tasks_json",
        "scripts",
        "array_throttles",
        "array_max_cpu",
        "array_max_gpu",
    ):
        if key in new_result:
            merged[key] = new_result[key]

    hist = merged.get("history")
    if not isinstance(hist, list):
        hist = []
    hist.append({k: v for k, v in new_result.items() if k != "history"})
    merged["history"] = hist

    merged_jobs = merged.get("jobs")
    if not isinstance(merged_jobs, dict):
        merged_jobs = {}
    new_jobs = new_result.get("jobs")
    if isinstance(new_jobs, dict):
        if isinstance(new_jobs.get("cpu_precompute_array"), dict):
            merged_jobs["cpu_precompute_array"] = new_jobs[
                "cpu_precompute_array"
            ]
        if isinstance(new_jobs.get("gpu_array"), dict):
            merged_jobs["gpu_array"] = new_jobs["gpu_array"]
    merged["jobs"] = merged_jobs

    for key in (
        "submitted_utc",
        "stage",
        "hypothesis",
        "commands",
        "dry_run",
    ):
        if key in new_result:
            merged[key] = new_result[key]
    return merged


def _array_tasks_payload(points: list[SweepPoint]) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for index, point in enumerate(points):
        tasks.append(
            {
                "task_index": index,
                "run_label": point.run_label,
                "run_dir": str(point.run_dir),
                "cpu_config": str(point.run_dir / "config_signal_fit.yaml"),
                "signal_fit_config": str(
                    point.run_dir / "config_signal_fit.yaml"
                ),
                "no_signal_config": str(
                    point.run_dir / "config_no_signal.yaml"
                ),
            }
        )
    return tasks


def _write_array_tasks_json(sweep_dir: Path, points: list[SweepPoint]) -> Path:
    out_path = sweep_dir / "array_tasks.json"
    payload = _array_tasks_payload(points)
    write_json_object(out_path, {"tasks": payload})
    return out_path


def _render_and_write_array_scripts(
    *,
    sweep_dir: Path,
    tasks_json: Path,
    runner: CondaRunner | ContainerRunner,
    install: BayesEoRInstall,
    slurm_cpu: dict[str, object],
    slurm_gpu: dict[str, object],
    task_count: int,
    array_max_cpu: int | None,
    array_max_gpu: int | None,
) -> dict[str, Path]:
    cpu_script = sweep_dir / "submit_cpu_precompute_array.sh"
    signal_script = sweep_dir / "submit_signal_fit_gpu_array.sh"
    no_signal_script = sweep_dir / "submit_no_signal_gpu_array.sh"

    slurm_cpu_array = dict(slurm_cpu)
    slurm_cpu_array.setdefault("array", array_spec(task_count, array_max_cpu))
    slurm_cpu_array.setdefault(
        "output", sweep_dir / "slurm-cpu-array-%A_%a.out"
    )

    slurm_gpu_array = dict(slurm_gpu)
    slurm_gpu_array.setdefault("array", array_spec(task_count, array_max_gpu))
    slurm_gpu_array.setdefault(
        "output", sweep_dir / "slurm-gpu-array-%A_%a.out"
    )

    cpu_script.write_text(
        render_array_submit_script(
            runner=runner,
            install=install,
            sweep_dir=sweep_dir,
            tasks_json=tasks_json,
            config_key="cpu_config",
            slurm=slurm_cpu_array,
            mode="cpu",
        ),
        encoding="utf-8",
    )
    signal_script.write_text(
        render_array_submit_script(
            runner=runner,
            install=install,
            sweep_dir=sweep_dir,
            tasks_json=tasks_json,
            config_key="signal_fit_config",
            slurm=slurm_gpu_array,
            mode="gpu_run",
        ),
        encoding="utf-8",
    )
    no_signal_script.write_text(
        render_array_submit_script(
            runner=runner,
            install=install,
            sweep_dir=sweep_dir,
            tasks_json=tasks_json,
            config_key="no_signal_config",
            slurm=slurm_gpu_array,
            mode="gpu_run",
        ),
        encoding="utf-8",
    )
    for script in (cpu_script, signal_script, no_signal_script):
        script.chmod(0o750)

    return {
        "cpu": cpu_script,
        "signal_fit": signal_script,
        "no_signal": no_signal_script,
    }


def _submit_sweep_array(
    *,
    sweep_dir: Path,
    sweep_manifest_path: Path,
    scripts: dict[str, Path],
    tasks_json: Path,
    task_count: int,
    submit: _STAGE,
    hypothesis: _HYP,
    depend_afterok: str | None,
    sbatch_exe: str,
    submit_dry_run: bool,
    force: bool,
    resubmit: bool,
    array_max_cpu: int | None,
    array_max_gpu: int | None,
) -> dict[str, Any]:
    existing = load_json_object(_sweep_jobs_path(sweep_dir))
    cpu_dependency_from_existing = extract_numeric_job_id(
        existing, "jobs", "cpu_precompute_array", "job_id"
    )
    archived: Path | None = None

    if existing is not None and not (force or resubmit):
        jobs = existing.get("jobs") if isinstance(existing, dict) else None
        if isinstance(jobs, dict):
            if (
                submit in ("cpu", "all")
                and isinstance(jobs.get("cpu_precompute_array"), dict)
                and is_numeric_job_id(
                    jobs["cpu_precompute_array"].get("job_id")
                )
            ):
                raise InvalidArgumentError(
                    f"CPU array job already recorded in jobs.json for {sweep_dir}. "
                    "Refusing to submit CPU again. Use --force or --resubmit."
                )
            if submit in ("gpu", "all") and isinstance(
                jobs.get("gpu_array"), dict
            ):
                gpu = jobs["gpu_array"]
                sf = gpu.get("signal_fit")
                ns = gpu.get("no_signal")
                if (
                    isinstance(sf, dict)
                    and is_numeric_job_id(sf.get("job_id"))
                ) or (
                    isinstance(ns, dict)
                    and is_numeric_job_id(ns.get("job_id"))
                ):
                    raise InvalidArgumentError(
                        f"GPU array jobs already recorded in jobs.json for {sweep_dir}. "
                        "Refusing to submit GPU again. Use --force or --resubmit."
                    )

    if resubmit and not submit_dry_run:
        archived = archive_sweep_jobs_json(sweep_dir)

    result: dict[str, Any] = {
        "sweep_dir": str(sweep_dir),
        "manifest": str(sweep_manifest_path),
        "jobs_json": str(_sweep_jobs_path(sweep_dir)),
        "submit_mode": "array",
        "submitted_utc": utc_now_iso(),
        "dry_run": bool(submit_dry_run),
        "stage": submit,
        "hypothesis": hypothesis,
        "commands": [],
        "jobs": {},
        "array_tasks_json": str(tasks_json),
        "scripts": {k: str(v) for k, v in scripts.items()},
        "array_max_cpu": array_max_cpu,
        "array_max_gpu": array_max_gpu,
        "array_throttles": {
            "cpu": array_max_cpu,
            "gpu": array_max_gpu,
            "task_count": task_count,
        },
    }

    cpu_jobid: str | None = None
    if submit in ("cpu", "all"):
        cpu_jobid, cmd = _run_sbatch(
            scripts["cpu"],
            sbatch_exe=sbatch_exe,
            cwd=sweep_dir,
            dry_run=submit_dry_run,
        )
        if submit_dry_run and cpu_jobid is None:
            cpu_jobid = _DRY_RUN_CPU_ARRAY_JOB_ID
        result["commands"].append(cmd)
        result["jobs"]["cpu_precompute_array"] = {
            "script": str(scripts["cpu"]),
            "command": cmd,
            "job_id": cpu_jobid,
            "job_id_is_placeholder": bool(submit_dry_run),
            "array": array_spec(task_count, array_max_cpu),
            "task_count": task_count,
            "task_file": str(tasks_json),
            "dependency": None,
        }

    if submit in ("gpu", "all"):
        dep: str | None = None
        dependency_source: str | None = None
        if cpu_jobid is not None:
            dep = cpu_jobid
            dependency_source = "same_invocation_cpu_array"
        elif depend_afterok is not None:
            dep = str(depend_afterok).strip()
            if not dep.isdigit():
                raise InvalidArgumentError(
                    "--depend-afterok must be a numeric SLURM job id."
                )
            dependency_source = "explicit_depend_afterok"
        elif cpu_dependency_from_existing is not None:
            dep = cpu_dependency_from_existing
            dependency_source = "sweep_jobs_json"
        else:
            raise MissingDependencyError(
                "GPU array submission requested but no CPU array dependency is known. "
                "Either submit CPU in the same invocation (--submit all --submit-mode array), "
                "or rerun with --depend-afterok <JOBID>, "
                "or ensure sweep-level jobs.json records a cpu_precompute_array.job_id."
            )

        gpu_jobs: dict[str, Any] = {
            "dependency": f"afterok:{dep}",
            "dependency_source": dependency_source,
            "array": array_spec(task_count, array_max_gpu),
            "task_count": task_count,
            "task_file": str(tasks_json),
        }

        if hypothesis in ("signal_fit", "both"):
            jobid, cmd = _run_sbatch(
                scripts["signal_fit"],
                dependency_afterok=dep,
                sbatch_exe=sbatch_exe,
                cwd=sweep_dir,
                dry_run=submit_dry_run,
            )
            if submit_dry_run and jobid is None:
                jobid = _DRY_RUN_SIGNAL_FIT_GPU_ARRAY_JOB_ID
            result["commands"].append(cmd)
            gpu_jobs["signal_fit"] = {
                "script": str(scripts["signal_fit"]),
                "command": cmd,
                "job_id": jobid,
                "job_id_is_placeholder": bool(submit_dry_run),
                "dependency": f"afterok:{dep}",
            }

        if hypothesis in ("no_signal", "both"):
            jobid, cmd = _run_sbatch(
                scripts["no_signal"],
                dependency_afterok=dep,
                sbatch_exe=sbatch_exe,
                cwd=sweep_dir,
                dry_run=submit_dry_run,
            )
            if submit_dry_run and jobid is None:
                jobid = _DRY_RUN_NO_SIGNAL_GPU_ARRAY_JOB_ID
            result["commands"].append(cmd)
            gpu_jobs["no_signal"] = {
                "script": str(scripts["no_signal"]),
                "command": cmd,
                "job_id": jobid,
                "job_id_is_placeholder": bool(submit_dry_run),
                "dependency": f"afterok:{dep}",
            }

        result["jobs"]["gpu_array"] = gpu_jobs

    if archived is not None:
        result["archived_jobs_json"] = str(archived)

    merged = _merge_sweep_jobs_record(existing, result)
    write_json_object(_sweep_jobs_path(sweep_dir), merged)

    return result


@dataclass(frozen=True)
class SweepPoint:
    """Metadata for a single sweep point."""

    perturb_parameter: _PERT
    perturb_frac: float
    run_label: str
    run_dir: Path
    manifest_json: Path

    @property
    def fwhm_perturb_frac(self) -> float | None:
        """Backward-compatible alias for legacy FWHM-only callers."""
        if self.perturb_parameter == "fwhm_deg":
            return self.perturb_frac
        return None


@dataclass(frozen=True)
class SweepResult:
    """Summary of a completed sweep run (prepare + optional submit)."""

    results_root: Path
    beam_model: str
    sky_model: str
    variant: str
    run_id: str
    perturb_parameter: _PERT
    data_path: Path
    data_path_source: str | None
    data_root_key: str | None
    created_utc: str
    sweep_dir: Path
    sweep_manifest_json: Path
    template_yaml: Path
    points: list[SweepPoint]
    submit_results: list[dict[str, Any]]
    submit_mode: _SUBMIT_MODE = "per-point"
    sweep_jobs_json: Path | None = None
    array_tasks_json: Path | None = None


def write_sweep_manifest(
    *,
    results_root: Path,
    beam_model: str,
    sky_model: str,
    variant: str,
    run_id: str,
    perturb_parameter: _PERT,
    data_path: Path,
    template_yaml: Path,
    sweep_dir: Path,
    points: list[SweepPoint],
    data_path_source: str | None = None,
    data_root_key: str | None = None,
    submit_results: list[dict[str, Any]] | None = None,
    submit_mode: _SUBMIT_MODE = "per-point",
    array_tasks_json: Path | None = None,
    sweep_jobs_json: Path | None = None,
    submission: dict[str, Any] | None = None,
) -> Path:
    """
    Write sweep_manifest.json under the sweep directory.

    Parameters
    ----------
    results_root, beam_model, sky_model, variant, run_id
        Identify the sweep location and taxonomy.
    data_path
        Data path used for the sweep.
    template_yaml
        Template used for the sweep points.
    sweep_dir
        Target sweep directory.
    points
        Prepared sweep points.
    submit_results
        Optional submission results to include.

    Returns
    -------
    Path
        Path to the written sweep_manifest.json.
    """
    sweep_dir.mkdir(parents=True, exist_ok=True)
    out_path = sweep_dir / "sweep_manifest.json"

    payload: dict[str, Any] = {
        "results_root": str(results_root),
        "beam_model": beam_model,
        "sky_model": sky_model,
        "variant": variant,
        "run_id": run_id,
        "perturb_parameter": perturb_parameter,
        "data_path": str(data_path),
        "data_path_source": data_path_source,
        "data_root_key": data_root_key,
        "template_yaml": str(template_yaml),
        "submit_mode": submit_mode,
        "created_utc": utc_now_iso(),
        "sweep_dir": str(sweep_dir),
        "points": [
            {
                "perturb_parameter": p.perturb_parameter,
                "perturb_frac": p.perturb_frac,
                "fwhm_perturb_frac": p.perturb_frac
                if p.perturb_parameter == "fwhm_deg"
                else None,
                "antenna_diameter_perturb_frac": p.perturb_frac
                if p.perturb_parameter == "antenna_diameter"
                else None,
                "run_label": p.run_label,
                "run_dir": str(p.run_dir),
                "manifest_json": str(p.manifest_json),
                "jobs_json": str(p.run_dir / "jobs.json")
                if (p.run_dir / "jobs.json").exists()
                else None,
            }
            for p in points
        ],
    }

    if submit_results is not None:
        payload["submit_results"] = submit_results
    if array_tasks_json is not None:
        payload["array_tasks_json"] = str(array_tasks_json)
    if sweep_jobs_json is not None:
        payload["sweep_jobs_json"] = str(sweep_jobs_json)
    if submission is not None:
        payload["submission"] = submission

    return write_json_object(out_path, payload)


def run_fwhm_sweep(
    *,
    # Prepare inputs
    template_yaml: Path,
    install: BayesEoRInstall,
    runner: CondaRunner | ContainerRunner,
    results_root: Path,
    beam_model: str,
    sky_model: str,
    variant: str,
    run_id: str,
    data_path: Path,
    data_path_source: str | None = None,
    data_root_key: str | None = None,
    slurm_cpu: dict[str, object] | None = None,
    slurm_gpu: dict[str, object] | None = None,
    overrides: dict[str, str] | None = None,
    perturb_parameter: _PERT = "fwhm_deg",
    perturb_fracs: Iterable[float] | None = None,
    fwhm_fracs: Iterable[float] | None = None,
    unique: bool = False,
    # Optional submit inputs
    submit: _STAGE = "none",
    hypothesis: _HYP = "both",
    depend_afterok: str | None = None,
    sbatch_exe: str = "sbatch",
    submit_dry_run: bool = False,
    force: bool = False,
    resubmit: bool = False,
    record: Literal["jobs.json", "manifest"] = "jobs.json",
    submit_mode: _SUBMIT_MODE = "per-point",
    array_max_cpu: int | None = None,
    array_max_gpu: int | None = None,
    # Dry-run for the sweep as a whole (no prepare, no submit)
    dry_run: bool = False,
) -> SweepResult:
    """
    Orchestrate a sweep over multiple perturbation values.

    Parameters
    ----------
    template_yaml
        BayesEoR template YAML to render.
    install
        BayesEoR installation metadata.
    runner
        Runner configuration (conda or container).
    results_root
        Root directory for results.
    beam_model, sky_model, variant, run_id
        Taxonomy fields and sweep identifier.
    data_path
        Input data path.
    slurm_cpu, slurm_gpu
        SLURM settings for CPU and GPU stages.
    overrides
        Template overrides applied to each run.
    perturb_parameter
        Which config key to perturb: ``fwhm_deg`` or ``antenna_diameter``.
    perturb_fracs
        Iterable of perturbation fractions to apply to ``perturb_parameter``.
    fwhm_fracs
        Backward-compatible alias for ``perturb_fracs`` when using
        ``perturb_parameter='fwhm_deg'``.
    unique
        If True, append a UTC timestamp to each run directory.
    submit
        Stage(s) to submit after prepare ("none", "cpu", "gpu", "all").
    hypothesis
        Which GPU hypothesis to submit ("signal_fit", "no_signal", "both").
    depend_afterok
        Optional sbatch job id to depend on for GPU submissions.
    sbatch_exe
        sbatch executable to invoke.
    submit_dry_run
        If True, do not submit; return the commands that would run.
    force
        If True, allow resubmission even if jobs.json indicates prior submissions.
    resubmit
        If True, archive jobs.json before submitting.
    record
        Where to record submission metadata. Currently only "jobs.json" is supported.
    dry_run
        If True, do not prepare or submit; only compute intended run paths.

    Returns
    -------
    SweepResult
        Summary of the sweep, including prepared points and submit results.

    Sweep directory layout
    ----------------------
    For sweeps we intentionally colocate all points so they can be archived/removed as a unit:

      <results_root>/bayeseor/<beam_model>/<sky_model>/_sweeps/<run_id>/<variant>/<run_label>/

    Behaviour
    ---------
    - Prepares one run_dir per perturbation frac (stable unless unique=True).
    - Optionally submits per run_dir via submit_bayeseor_run with stage cpu/gpu/all.
    - Writes/updates sweep_manifest.json under:
        <results_root>/bayeseor/<beam_model>/<sky_model>/_sweeps/<run_id>/

    Resubmission behaviour
    ----------------------
    - If resubmit=True and submit_dry_run=False, for each point we archive jobs.json
      (if present) to jobs_<timestamp>.json before submitting.
    - This enables "GPU-only resubmit across sweep" safely:
        submit="gpu", resubmit=True
    """
    results_root = Path(results_root).expanduser().resolve()
    data_path = Path(data_path).expanduser().resolve()
    template_yaml = Path(template_yaml).expanduser().resolve()

    beam_model = str(beam_model).strip()
    sky_model = str(sky_model).strip()
    variant = str(variant).strip()
    if not beam_model:
        raise ValueError("beam_model must be a non-empty string")
    if not sky_model:
        raise ValueError("sky_model must be a non-empty string")
    if not variant:
        raise ValueError("variant must be a non-empty string")
    if perturb_parameter not in {"fwhm_deg", "antenna_diameter"}:
        raise ValueError(
            "perturb_parameter must be one of: 'fwhm_deg', 'antenna_diameter'."
        )
    if perturb_fracs is not None and fwhm_fracs is not None:
        raise ValueError(
            "Provide either perturb_fracs or fwhm_fracs, not both."
        )

    fracs_in = perturb_fracs if perturb_fracs is not None else fwhm_fracs
    fracs = list(_default_fwhm_fracs() if fracs_in is None else fracs_in)
    if not fracs:
        raise ValueError("No perturbation fractions provided for sweep.")

    sweep_dir = sweep_root(results_root, beam_model, sky_model, run_id)
    sweep_manifest_path = sweep_dir / "sweep_manifest.json"

    points: list[SweepPoint] = []
    submit_results: list[dict[str, Any]] = []

    # --------------------
    # Dry-run: compute intended run_dirs only
    # --------------------
    if dry_run:
        for frac in fracs:
            run_label = _format_run_label(
                perturb_parameter=perturb_parameter, frac=float(frac)
            )
            base = sweep_point_dir(
                results_root,
                beam_model,
                sky_model,
                run_id,
                variant=variant,
                run_label=run_label,
            )
            run_dir = base / utc_now_compact() if unique else base
            manifest_json = run_dir / "manifest.json"
            points.append(
                SweepPoint(
                    perturb_parameter=perturb_parameter,
                    perturb_frac=float(frac),
                    run_label=run_label,
                    run_dir=run_dir,
                    manifest_json=manifest_json,
                )
            )

        return SweepResult(
            results_root=results_root,
            beam_model=beam_model,
            sky_model=sky_model,
            variant=variant,
            run_id=run_id,
            perturb_parameter=perturb_parameter,
            data_path=data_path,
            data_path_source=data_path_source,
            data_root_key=data_root_key,
            created_utc=utc_now_iso(),
            sweep_dir=sweep_dir,
            sweep_manifest_json=sweep_manifest_path,
            template_yaml=template_yaml,
            points=points,
            submit_results=[],
            submit_mode=submit_mode,
        )

    # --------------------
    # Prepare each point
    # --------------------
    for frac in fracs:
        frac_f = float(frac)
        run_label = _format_run_label(
            perturb_parameter=perturb_parameter, frac=frac_f
        )

        base_run_dir = sweep_point_dir(
            results_root,
            beam_model,
            sky_model,
            run_id,
            variant=variant,
            run_label=run_label,
        )
        run_dir = base_run_dir / utc_now_compact() if unique else base_run_dir

        out = prepare_bayeseor_run(
            template_yaml=template_yaml,
            install=install,
            runner=runner,
            results_root=results_root,
            beam_model=beam_model,
            sky_model=sky_model,
            variant=variant,
            run_label=run_label,
            run_id=run_id,  # recorded provenance; run_dir is explicit sweep layout
            run_dir=run_dir,  # explicit: sweep layout
            unique=False,  # unique already handled above (if desired)
            data_path=data_path,
            data_path_source=data_path_source,
            data_root_key=data_root_key,
            overrides=overrides or {},
            slurm_cpu=slurm_cpu or {},
            slurm_gpu=slurm_gpu or {},
            fwhm_perturb_frac=frac_f
            if perturb_parameter == "fwhm_deg"
            else None,
            antenna_diameter_perturb_frac=frac_f
            if perturb_parameter == "antenna_diameter"
            else None,
            hypothesis="both",
        )

        prepared_run_dir = Path(str(out["run_dir"])).expanduser().resolve()
        manifest_json = Path(str(out["manifest_json"])).expanduser().resolve()

        points.append(
            SweepPoint(
                perturb_parameter=perturb_parameter,
                perturb_frac=frac_f,
                run_label=run_label,
                run_dir=prepared_run_dir,
                manifest_json=manifest_json,
            )
        )

    # --------------------
    # Submit stage(s) per point if requested
    # --------------------
    array_tasks_json: Path | None = None
    sweep_jobs_json: Path | None = None

    if submit_mode == "array":
        sweep_dir.mkdir(parents=True, exist_ok=True)
        array_tasks_json = _write_array_tasks_json(sweep_dir, points)
        _render_and_write_array_scripts(
            sweep_dir=sweep_dir,
            tasks_json=array_tasks_json,
            runner=runner,
            install=install,
            slurm_cpu=slurm_cpu or {},
            slurm_gpu=slurm_gpu or {},
            task_count=len(points),
            array_max_cpu=array_max_cpu,
            array_max_gpu=array_max_gpu,
        )
        sweep_jobs_json = _sweep_jobs_path(sweep_dir)

    if submit != "none":
        if submit_mode == "array":
            scripts = {
                "cpu": sweep_dir / "submit_cpu_precompute_array.sh",
                "signal_fit": sweep_dir / "submit_signal_fit_gpu_array.sh",
                "no_signal": sweep_dir / "submit_no_signal_gpu_array.sh",
            }
            try:
                submit_results.append(
                    _submit_sweep_array(
                        sweep_dir=sweep_dir,
                        sweep_manifest_path=sweep_manifest_path,
                        scripts=scripts,
                        tasks_json=array_tasks_json
                        if array_tasks_json is not None
                        else sweep_dir / "array_tasks.json",
                        task_count=len(points),
                        submit=submit,
                        hypothesis=hypothesis,
                        depend_afterok=depend_afterok,
                        sbatch_exe=sbatch_exe,
                        submit_dry_run=submit_dry_run,
                        force=force,
                        resubmit=resubmit,
                        array_max_cpu=array_max_cpu,
                        array_max_gpu=array_max_gpu,
                    )
                )
            except SubmissionError as e:
                submit_results.append(
                    {
                        "sweep_dir": str(sweep_dir),
                        "error": str(e),
                        "stage": submit,
                        "hypothesis": hypothesis,
                        "dry_run": bool(submit_dry_run),
                        "submit_mode": submit_mode,
                    }
                )
        else:
            for p in points:
                archived: Path | None = None

                # If resubmitting, archive per-run jobs.json first (unless submit_dry_run).
                if resubmit and not submit_dry_run:
                    try:
                        archived = archive_jobs_json(p.run_dir)
                    except Exception as e:
                        submit_results.append(
                            {
                                "run_dir": str(p.run_dir),
                                "error": f"Failed to archive jobs.json: {e}",
                                "stage": submit,
                                "hypothesis": hypothesis,
                                "dry_run": bool(submit_dry_run),
                            }
                        )
                        continue

                try:
                    submit_force = bool(force or resubmit)

                    res = submit_bayeseor_run(
                        p.run_dir,
                        stage="all" if submit == "all" else submit,  # type: ignore[arg-type]
                        hypothesis=hypothesis,
                        depend_afterok=depend_afterok,
                        sbatch_exe=sbatch_exe,
                        dry_run=submit_dry_run,
                        force=submit_force,
                        record=record,
                    )

                    if archived is not None:
                        res = dict(res)
                        res["archived_jobs_json"] = str(archived)

                    submit_results.append(res)

                except SubmissionError as e:
                    submit_results.append(
                        {
                            "run_dir": str(p.run_dir),
                            "error": str(e),
                            "stage": submit,
                            "hypothesis": hypothesis,
                            "dry_run": bool(submit_dry_run),
                            "archived_jobs_json": str(archived)
                            if archived is not None
                            else None,
                        }
                    )

    # --------------------
    # Write sweep manifest
    # --------------------
    write_sweep_manifest(
        results_root=results_root,
        beam_model=beam_model,
        sky_model=sky_model,
        variant=variant,
        run_id=run_id,
        perturb_parameter=perturb_parameter,
        data_path=data_path,
        data_path_source=data_path_source,
        data_root_key=data_root_key,
        template_yaml=template_yaml,
        sweep_dir=sweep_dir,
        points=points,
        submit_results=submit_results if submit_results else None,
        submit_mode=submit_mode,
        array_tasks_json=array_tasks_json,
        sweep_jobs_json=sweep_jobs_json,
        submission=(
            submit_results[0]
            if submit_mode == "array" and submit_results
            else None
        ),
    )

    return SweepResult(
        results_root=results_root,
        beam_model=beam_model,
        sky_model=sky_model,
        variant=variant,
        run_id=run_id,
        perturb_parameter=perturb_parameter,
        data_path=data_path,
        data_path_source=data_path_source,
        data_root_key=data_root_key,
        created_utc=utc_now_iso(),
        sweep_dir=sweep_dir,
        sweep_manifest_json=sweep_manifest_path,
        template_yaml=template_yaml,
        points=points,
        submit_results=submit_results,
        submit_mode=submit_mode,
        sweep_jobs_json=sweep_jobs_json,
        array_tasks_json=array_tasks_json,
    )
