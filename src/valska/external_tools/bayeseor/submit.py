"""Submission helpers for BayesEoR prepared run directories."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from valska.external_tools.common.submit import (
    InvalidArgumentError,
    JobsFile,
    MissingDependencyError,
    RunOptions,
    Stage,
    StageType,
    SubmitPlan,
    ensure_script_exists,
    get_path_from_artefacts,
    run_sbatch,
)

_AFTEROK_RE = re.compile(r"afterok:(\d+)")
_CPU_MATRIX_MARKERS: dict[str, tuple[str, ...]] = {
    "Ninv": ("Ninv.h5", "Ninv.npz"),
    "T_Ninv_T": ("T_Ninv_T.h5", "T_Ninv_T.npz"),
}

_HYP = Literal["signal_fit", "no_signal", "both"]


class BayesEoRStage(Stage):
    """Inherits the Stage class which contains info about a stage and points to the setup method"""


class BayesEoRStageType(StageType):
    @staticmethod
    def cpu_precompute_setup(
        plan: BayesEoRSubmitPlan,
        result: dict[str, Any],
    ):
        ensure_script_exists(plan.cpu_script, "CPU precompute")

        jobs = result.get("jobs") or {"jobs": {}}

        # --------------------
        # CPU submission
        # --------------------
        jobid, cmd = run_sbatch(
            plan.cpu_script,
            dependency_afterok=None,
            sbatch_exe=plan.options.sbatch_exe,
            cwd=plan.run_dir,
            dry_run=plan.options.dry_run,
        )
        result["commands"].append(cmd)

        jobs["jobs"]["cpu_precompute"] = {
            "script": str(plan.cpu_script),
            "job_id": jobid,
            "cpu_precompute_driver_hypothesis": plan.cpu_precompute_driver_hypothesis,
        }
        result["jobs"] = jobs

        return result, jobid, cmd

    @staticmethod
    def gpu_setup(
        plan: BayesEoRSubmitPlan,
        result: dict[str, Any],
    ):
        # --------------------
        # GPU submission
        # --------------------

        jobs = result.get("jobs") or {"jobs": {}}

        cpu_jobs = jobs.get("jobs") or {}
        cpu_job = cpu_jobs.get("cpu_precompute")

        cpu_jobid = (
            cpu_job.get("job_id", "") if isinstance(cpu_job, dict) else ""
        )

        dep: str | None = None
        dependency_source: str | None = None
        verified_matrix_dir: Path | None = None

        # First check whether stage=all - this means CPU and GPU were submitted
        # together and GPU should depend on CPU with ID as recorded in jobs.json
        if plan.stage_id == "all" and cpu_jobid:
            dep = cpu_jobid
            dependency_source = "same_invocation_cpu"
        # Otherwise check for explicit dependency with manually entered CPU ID
        elif plan.options.depend_afterok is not None:
            dep = _safe_int_jobid(plan.options.depend_afterok)
            if dep is None:
                raise InvalidArgumentError(
                    "--depend-afterok must be a numeric SLURM job id."
                )
            dependency_source = "explicit_depend_afterok"
        elif plan.options.dry_run and plan.stage_id == "all":
            dep = "<CPU_JOBID>"
            dependency_source = "dry_run_placeholder"
        # Otherwise CPU job must have been submitted separately before GPU
        else:
            verified_matrix_dir = _find_completed_cpu_precompute_matrix_dir(
                plan.run_dir
            )
            # Either it could have finished already, in which case outputs will be
            # available
            if verified_matrix_dir is not None:
                dependency_source = "cpu_precompute_outputs_verified"
            # OR it could still be running - in that case, depend on its job ID
            else:
                dep = _extract_cpu_jobid_from_existing(plan.load_jobs())
                if dep is not None:
                    dependency_source = "jobs_json"

        if dep is None:
            if verified_matrix_dir is None:
                raise MissingDependencyError(
                    "GPU submission requested but neither a reusable CPU dependency "
                    "job id nor completed CPU precompute outputs are available. "
                    "Either submit CPU in the same invocation (--stage all), "
                    "or pass --depend-afterok <JOBID>, "
                    "or ensure jobs.json exists with a recorded cpu_precompute.job_id "
                    "(or an existing jobs.gpu.dependency like 'afterok:<JOBID>'), "
                    "or rerun CPU so BayesEoR writes the required matrix stack under "
                    "run_dir/matrices/."
                )

        gpu_jobs: dict[str, Any] = {
            "dependency": f"afterok:{dep}" if dep is not None else None,
            "dependency_source": dependency_source,
        }
        if verified_matrix_dir is not None:
            gpu_jobs["cpu_precompute_matrix_dir"] = str(verified_matrix_dir)

        if plan.options.hypothesis in ("signal_fit", "both"):
            if plan.gpu_signal_fit_script is None:
                raise MissingDependencyError(
                    "manifest does not contain a signal_fit GPU submit script artefact "
                    "(submit_sh_signal_fit_gpu_run)."
                )
            ensure_script_exists(plan.gpu_signal_fit_script, "signal_fit GPU")
            jobid, cmd = run_sbatch(
                plan.gpu_signal_fit_script,
                dependency_afterok=dep,
                sbatch_exe=plan.options.sbatch_exe,
                cwd=plan.run_dir,
                dry_run=plan.options.dry_run,
            )
            result["commands"].append(cmd)
            gpu_jobs["signal_fit"] = {
                "script": str(plan.gpu_signal_fit_script),
                "job_id": jobid,
            }

        if plan.options.hypothesis in ("no_signal", "both"):
            if plan.gpu_no_signal_script is None:
                raise MissingDependencyError(
                    "manifest does not contain a no_signal GPU submit script artefact "
                    "(submit_sh_no_signal_gpu_run)."
                )
            ensure_script_exists(plan.gpu_no_signal_script, "no_signal GPU")
            jobid, cmd = run_sbatch(
                plan.gpu_no_signal_script,
                dependency_afterok=dep,
                sbatch_exe=plan.options.sbatch_exe,
                cwd=plan.run_dir,
                dry_run=plan.options.dry_run,
            )
            result["commands"].append(cmd)
            gpu_jobs["no_signal"] = {
                "script": str(plan.gpu_no_signal_script),
                "job_id": jobid,
            }

        jobs["jobs"]["gpu"] = gpu_jobs
        result["jobs"] = jobs

        return result, jobid, cmd

    CPU = BayesEoRStage(name="cpu_precompute", method=cpu_precompute_setup)
    GPU = BayesEoRStage(name="gpu", method=gpu_setup)


class BayesEoRJobsFile(JobsFile):
    extra_fields = [("hypothesis", "")]


@dataclass
class BayesEoRRunOptions(RunOptions):
    hypothesis: _HYP = "both"


@dataclass()
class BayesEoRSubmitPlan(SubmitPlan[BayesEoRRunOptions]):
    """Resolved paths needed to submit a prepared BayesEoR run."""

    cpu_script: Path = field(init=False)
    gpu_signal_fit_script: Path | None = field(init=False)
    gpu_no_signal_script: Path | None = field(init=False)
    cpu_precompute_driver_hypothesis: str | None = field(init=False)

    def __post_init__(self):
        super().__post_init__()

        self.requested_stages = self.resolve_stages(self.stage_id)

        self.jobs_file = BayesEoRJobsFile()

        artefacts = self.load_manifest().get("artefacts", {})
        if not isinstance(artefacts, dict):
            raise MissingDependencyError(
                "manifest['artefacts'] is missing or not a dict"
            )

        cpu_script = get_path_from_artefacts(
            artefacts, "submit_sh_cpu_precompute", required=True
        )
        gpu_signal = get_path_from_artefacts(
            artefacts, "submit_sh_signal_fit_gpu_run", required=False
        )
        gpu_nosig = get_path_from_artefacts(
            artefacts, "submit_sh_no_signal_gpu_run", required=False
        )

        self.cpu_precompute_driver_hypothesis = (
            self.load_manifest()
            .get("bayeseor", {})
            .get("cpu_precompute_driver_hypothesis", None)
            if isinstance(self.load_manifest().get("bayeseor", {}), dict)
            else None
        )

        self.cpu_script = self.normalise_path(cpu_script)  # type: ignore[assignment]
        self.gpu_signal_fit_script = self.normalise_path(gpu_signal)
        self.gpu_no_signal_script = self.normalise_path(gpu_nosig)

    def resolve_stages(self, stage: str) -> list[Stage]:
        """Resolve BayesEoR stages"""

        # These are the possible stages for this module
        stages = {
            "cpu": [BayesEoRStageType.CPU],
            "gpu": [BayesEoRStageType.GPU],
            "all": [BayesEoRStageType.CPU, BayesEoRStageType.GPU],
        }

        try:
            return [stage_type.value for stage_type in stages[stage]]
        except KeyError:
            raise InvalidArgumentError(
                f"Unknown BayesEoR submission stage: {stage}"
            )

    def check_jobs_not_running(self, force):
        existing_jobs = self.load_jobs()

        # Second-line guardrail: refuse re-submission of a stage if that stage is already recorded,
        # unless force=True. (cli_submit.py also enforces guardrails; this protects programmatic calls.)
        if existing_jobs is not None and not force:
            jobs = (
                existing_jobs.get("jobs")
                if isinstance(existing_jobs, dict)
                else None
            )
            if isinstance(jobs, dict):
                if (
                    BayesEoRStageType.CPU in self.requested_stages
                    and isinstance(jobs.get("cpu_precompute"), dict)
                    and jobs["cpu_precompute"].get("job_id")
                ):
                    raise InvalidArgumentError(
                        f"CPU precompute already recorded in jobs.json for {self.run_dir}. "
                        "Refusing to submit CPU again. Use --force or --resubmit."
                    )
                if (
                    BayesEoRStageType.GPU in self.requested_stages
                    and isinstance(jobs.get("gpu"), dict)
                ):
                    gpu = jobs["gpu"]
                    sf = gpu.get("signal_fit")
                    ns = gpu.get("no_signal")
                    if (isinstance(sf, dict) and sf.get("job_id")) or (
                        isinstance(ns, dict) and ns.get("job_id")
                    ):
                        raise InvalidArgumentError(
                            f"GPU jobs already recorded in jobs.json for {self.run_dir}. "
                            "Refusing to submit GPU again. Use --force or --resubmit."
                        )


def _safe_int_jobid(x: Any) -> str | None:
    if x is None:
        return None
    s = str(x).strip()
    return s if s.isdigit() else None


def _extract_cpu_jobid_from_existing(
    existing: dict[str, Any] | None,
) -> str | None:
    """
    Try to locate a CPU job id from an existing jobs.json structure.
    """
    if not isinstance(existing, dict):
        return None
    jobs = existing.get("jobs")
    if isinstance(jobs, dict):
        cpu = jobs.get("cpu_precompute")
        if isinstance(cpu, dict):
            jid = _safe_int_jobid(cpu.get("job_id"))
            if jid:
                return jid
        gpu = jobs.get("gpu")
        if isinstance(gpu, dict):
            dep = gpu.get("dependency")
            if isinstance(dep, str):
                m = _AFTEROK_RE.search(dep)
                if m:
                    return m.group(1)
    return None


def _find_completed_cpu_precompute_matrix_dir(run_dir: Path) -> Path | None:
    """
    Return a matrix-stack directory when CPU precompute outputs appear complete.

    BayesEoR GPU runs require the CPU-built matrix stack, most importantly the
    ``Ninv`` and ``T_Ninv_T`` artefacts. For the standard ValSKA-generated
    configs these are written beneath ``run_dir/matrices/...``.

    We treat CPU precompute as reusable only when both markers are present in
    the same matrix directory.
    """
    matrices_root = run_dir / "matrices"
    if not matrices_root.exists():
        return None

    candidate_dirs: list[set[Path]] = []
    for filenames in _CPU_MATRIX_MARKERS.values():
        dirs_for_marker: set[Path] = set()
        for filename in filenames:
            dirs_for_marker.update(
                p.parent for p in matrices_root.rglob(filename)
            )
        if not dirs_for_marker:
            return None
        candidate_dirs.append(dirs_for_marker)

    common_dirs = set.intersection(*candidate_dirs)
    if not common_dirs:
        return None

    return max(common_dirs, key=lambda p: p.stat().st_mtime)
