"""Submission helpers for prepared run directories."""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from valska.external_tools.common.utils import utc_now_iso

_RECORD = Literal["jobs.json", "manifest"]

_JOBID_RE = re.compile(r"Submitted\s+batch\s+job\s+(\d+)\s*$", re.IGNORECASE)


class SubmissionError(RuntimeError):
    """Raised when submission cannot proceed safely or sbatch fails."""


class InvalidArgumentError(SubmissionError):
    """Raised when CLI arguments are invalid for submission."""


class MissingDependencyError(SubmissionError):
    """Raised when required inputs or artefacts are missing."""


class SbatchError(SubmissionError):
    """Raised when sbatch fails or returns unparseable output."""


@dataclass()
class Stage:
    """Holds details about a stage and points to the method which does any setup before submission"""

    name: str
    method: Callable


class StageType(Enum):
    """Container type to inherit for each tool's own StageType class"""


class JobsFile:
    """Fields found in a jobs.json file"""

    # TODO replace this class with a Pydantic model so the whole schema can be verified, not just the fields
    common_fields = [
        "run_dir",
        "manifest",
        "sbatch",
        "dry_run",
        "history",
        "jobs",
        "submitted_utc",
        "stage",
        "commands",
    ]

    # Fields that can be merged and their defaults
    mergeable_fields = [
        ("sbatch", "sbatch"),
        ("dry_run", False),
        ("submitted_utc", ""),
        ("stage", ""),
        ("commands", []),
    ]

    extra_fields: list[tuple[str, ...]] = []


@dataclass
class RunOptions:
    """Common arguments for module run"""

    depend_afterok: str | None = None
    sbatch_exe: str = "sbatch"
    dry_run: bool = False
    force: bool = False
    record: _RECORD = "jobs.json"


@dataclass()
class SubmitPlan[OptionsType: RunOptions]:
    """Resolved paths, config, and methods needed to submit a prepared run."""

    run_dir: Path
    stage_id: str  # (this can include "all" which is actually two stages)
    options: OptionsType  # (each module may have its own options class)
    # These are the resolved stage objects in a list:
    requested_stages: list[Stage] = field(init=False)
    manifest_path: Path = field(init=False)
    jobs_path: Path = field(init=False)
    jobs_file: JobsFile = field(init=False)

    def __post_init__(self):
        self.manifest_path = self.run_dir / "manifest.json"
        self.jobs_path = self.run_dir / "jobs.json"

    def resolve_stages(self, stage: str) -> list[Stage]:
        """
        This method is overridden within each module
        to resolve the specific stages for that module.
        """
        raise NotImplementedError

    def load_manifest(self) -> dict[str, Any]:
        """
        Load and parse manifest.json from a prepared run directory.

        Parameters
        ----------
        run_dir
            Prepared run directory containing manifest.json.

        Returns
        -------
        dict
            Parsed manifest content.
        """
        if not self.manifest_path.exists():
            raise MissingDependencyError(
                f"Missing manifest.json in run_dir: {self.run_dir}"
            )
        try:
            return json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except Exception as e:  # pragma: no cover
            raise MissingDependencyError(
                f"Failed to parse manifest.json: {self.manifest_path}\n{e}"
            ) from e

    def load_jobs(self) -> dict[str, Any] | None:
        p = self.jobs_path
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except Exception as e:  # pragma: no cover
            raise SubmissionError(
                f"Failed to parse existing jobs.json: {p}\n{e}"
            ) from e

    def merge_jobs_record(
        self,
        new_result: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Merge a new submission result into an existing jobs.json record.

        - Keeps stable top-level metadata (run_dir, manifest)
        - Updates "jobs" by stage (e.g. cpu_precompute, gpu)
        - Appends to "history" so we don't lose what happened
        """
        merged: dict[str, Any] = {}

        # Start from existing, then overlay stable fields from new_result
        existing = self.load_jobs()
        if isinstance(existing, dict):
            merged.update(existing)

        # Always set these from new_result to reflect latest invocation context
        for k in ("run_dir", "manifest"):
            if k in new_result:
                merged[k] = new_result[k]

        # Keep a full submission history (append-only)
        hist = merged.get("history")
        if not isinstance(hist, list):
            hist = []
        # store a compact record (not including any existing "history")
        hist_entry = {k: v for k, v in new_result.items() if k != "history"}
        hist.append(hist_entry)
        merged["history"] = hist

        # Merge jobs by stage
        merged_jobs = merged.get("jobs")
        if not isinstance(merged_jobs, dict):
            merged_jobs = {}

        new_jobs = new_result.get("jobs")
        if isinstance(new_jobs, dict):
            for requested_stage in self.requested_stages:
                stage_jobs = new_jobs.get(requested_stage.name)
                if isinstance(stage_jobs, dict):
                    merged_jobs[requested_stage.name] = stage_jobs

        merged["jobs"] = merged_jobs

        mergeable_fields = (
            self.jobs_file.mergeable_fields + self.jobs_file.extra_fields
        )

        for jobs_field, default in mergeable_fields:
            merged[jobs_field] = new_result.get(
                jobs_field, merged.get(jobs_field, default)
            )

        return merged

    def write_jobs(self, jobs: dict[str, Any]) -> Path:
        p = self.jobs_path
        p.write_text(json.dumps(jobs, indent=2), encoding="utf-8")
        return p

    def normalise_path(self, p: Path | None) -> Path | None:
        if p is None:
            return None
        return (
            (self.run_dir / p).resolve()
            if not p.is_absolute()
            else p.resolve()
        )

    def check_jobs_not_running(self, force):
        """To be implemented by each tool"""


def get_path_from_artefacts(
    artefacts: dict[str, Any], key: str, required: bool = True
) -> Path | None:
    p = artefacts.get(key)
    if p is None:
        if required:
            raise MissingDependencyError(
                f"manifest artefact missing required key: {key}"
            )
        return None
    return Path(str(p)).expanduser()


def ensure_script_exists(path: Path, label: str) -> None:
    if not path.exists():
        raise MissingDependencyError(f"Missing {label} script: {path}")
    if not path.is_file():
        raise MissingDependencyError(f"{label} script is not a file: {path}")


def run_sbatch(
    script: Path,
    *,
    dependency_afterok: str | None = None,
    sbatch_exe: str = "sbatch",
    cwd: Path | None = None,
    dry_run: bool = False,
) -> tuple[str | None, str]:
    """
    Returns (job_id, command_str). If dry_run=True, job_id is None.
    """
    cmd: list[str] = [sbatch_exe]
    if dependency_afterok:
        cmd.append(f"--dependency=afterok:{dependency_afterok}")
    cmd.append(str(script))

    cmd_str = " ".join(cmd)

    if dry_run:
        return None, cmd_str

    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd is not None else None,
        capture_output=True,
        text=True,
    )

    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()

    if proc.returncode != 0:
        raise SbatchError(
            "sbatch failed.\n"
            f"Command: {cmd_str}\n"
            f"Return code: {proc.returncode}\n"
            f"stdout:\n{out}\n"
            f"stderr:\n{err}\n"
        )

    m = _JOBID_RE.search(out)
    if not m:
        raise SbatchError(
            "Could not parse job id from sbatch stdout.\n"
            f"Command: {cmd_str}\n"
            f"stdout:\n{out}\n"
            f"stderr:\n{err}\n"
        )

    return m.group(1), cmd_str


# Declaring OptionsType here allows a module specific SubmitPlan
# to use its own specific options class that expands RunOptions.
def submit_tool_run[OptionsType: RunOptions](
    run_dir: Path,
    *,
    stage_id: str,
    submit_plan: type[SubmitPlan[OptionsType]],
    options: OptionsType,
) -> dict[str, Any]:
    """
    Submit external tool prepared scripts for a run_dir.

    Parameters
    ----------
    run_dir
        Prepared run directory.
    stage
        Which stage(s) to submit: e.g. "cpu", "gpu", or "all".
    options
        run options containing common + module specific options:
        depend_afterok: Optional sbatch job id to depend on for GPU submissions.
        sbatch_exe: sbatch executable to invoke.
        dry_run: If True, do not submit jobs; return the commands that would run.
        force: If True, allow resubmission even if jobs.json indicates prior submissions.
        record: Where to record submission metadata. Currently only "jobs.json" is supported.

    Returns
    -------
    dict
        A jobs.json-style record of the submission (merged if not dry_run).

    Notes on jobs.json recording
    ----------------------------
    jobs.json is treated as a durable record that may be updated across invocations:
      - stage=cpu creates/updates jobs.cpu_precompute
      - stage=gpu appends/updates jobs.gpu
      - stage=all updates both

    We also keep a submission 'history' list so previous job ids are not lost.
    """

    plan = submit_plan(run_dir.expanduser().resolve(), stage_id, options)

    ensure_script_exists(plan.manifest_path, "manifest.json")

    if options.record == "manifest":
        raise InvalidArgumentError(
            "record='manifest' is not enabled in the MVP to avoid mutating provenance. "
            "Use record='jobs.json' (default)."
        )

    plan.check_jobs_not_running(options.force)

    result: dict[str, Any] = {
        "run_dir": str(plan.run_dir),
        "manifest": str(plan.manifest_path),
        "submitted_utc": utc_now_iso(),
        "sbatch": options.sbatch_exe,
        "dry_run": bool(options.dry_run),
        "stage": stage_id,
        "commands": [],
        "jobs": plan.load_jobs(),
    }

    # add tool specific extra fields to result
    for extra_field, default in plan.jobs_file.extra_fields:
        result[extra_field] = default

    # Stage specific code here
    # Each requested stage is a stage object.
    for requested_stage in plan.requested_stages:
        result, jobid, cmd = requested_stage.method(plan, result)

    if not options.dry_run:
        merged = plan.merge_jobs_record(result)
        plan.write_jobs(merged)
        return merged

    return result
