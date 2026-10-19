"""Slurm submit-script rendering for external tool runs."""

from __future__ import annotations

import shlex
from collections.abc import Mapping
from pathlib import Path, PurePath

from valska.external_tools.common.runner import CondaRunner, ContainerRunner
from valska.external_tools.common.utils import get_int_or_none, get_str_or_none


def _gpu_diag_block(mode: str) -> str:
    if mode != "gpu_run":
        return ""
    return """
echo "===== GPU DIAGNOSTICS (begin) ====="
echo "CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-<unset>}"
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi -L || true
else
  echo "nvidia-smi not found on PATH"
fi
echo "===== GPU DIAGNOSTICS (end) ====="
echo "----------------------------------------"
"""


def _build_sbatch_block(
    *,
    slurm: Mapping[str, object] | None,
    job_name: str,
    out_log_default: Path,
) -> tuple[str, int]:
    """Build the SBATCH header block and return it with the default CPU count."""
    slurm = dict(slurm or {})

    # -------------------------
    # Resource selection
    # -------------------------
    partition = get_str_or_none(slurm, "partition")
    constraint = get_str_or_none(slurm, "constraint")
    qos = get_str_or_none(slurm, "qos")
    account = get_str_or_none(slurm, "account")
    reservation = get_str_or_none(slurm, "reservation")
    # -------------------------
    # Time and memory
    # -------------------------
    time = get_str_or_none(slurm, "time", "12:00:00")
    mem = get_str_or_none(slurm, "mem", "8G")
    mem_per_cpu = get_str_or_none(slurm, "mem_per_cpu")
    mem_per_gpu = get_str_or_none(slurm, "mem_per_gpu")
    # -------------------------
    # CPU/task configuration
    # -------------------------
    nodes = get_int_or_none(slurm, "nodes", 1)
    ntasks = get_int_or_none(slurm, "ntasks", 1)
    ntasks_per_node = get_int_or_none(slurm, "ntasks_per_node", 1)
    cpus_per_task = get_int_or_none(slurm, "cpus_per_task", 4)
    # -------------------------
    # GPU configuration
    # -------------------------
    gpus = get_str_or_none(slurm, "gpus")
    gpus_per_node = get_str_or_none(slurm, "gpus_per_node")
    gpus_per_task = get_int_or_none(slurm, "gpus_per_task")
    gres = get_str_or_none(slurm, "gres")
    # -------------------------
    # Execution control
    # -------------------------
    exclusive = slurm.get("exclusive", None)
    array_spec = get_str_or_none(slurm, "array")

    # -------------------------
    # Output paths
    # -------------------------
    out_log = slurm.get("output", out_log_default)
    if out_log is not None:
        if not isinstance(out_log, str | Path):
            raise TypeError("slurm['output'] must be str or Path if provided")
        out_log = Path(out_log)
    err_log = slurm.get("error", None)
    if err_log is not None:
        if not isinstance(err_log, str | Path):
            raise TypeError("slurm['error'] must be str or Path if provided")
        err_log = Path(err_log)

    # -------------------------
    # Extra SBATCH lines
    # -------------------------
    extra_sbatch = slurm.get("extra_sbatch", [])
    if extra_sbatch is None:
        extra_sbatch = []
    if not isinstance(extra_sbatch, list):
        raise TypeError(
            "slurm['extra_sbatch'] must be a list of strings if provided"
        )

    sbatch_lines: list[str] = [
        "#!/bin/bash",
        f"#SBATCH --job-name={job_name}",
    ]

    if partition:
        sbatch_lines.append(f"#SBATCH --partition={partition}")
    if constraint:
        sbatch_lines.append(f"#SBATCH --constraint={constraint}")
    if qos:
        sbatch_lines.append(f"#SBATCH --qos={qos}")
    if account:
        sbatch_lines.append(f"#SBATCH --account={account}")
    if reservation:
        sbatch_lines.append(f"#SBATCH --reservation={reservation}")
    if time:
        sbatch_lines.append(f"#SBATCH --time={time}")
    if mem:
        sbatch_lines.append(f"#SBATCH --mem={mem}")
    if mem_per_cpu:
        sbatch_lines.append(f"#SBATCH --mem-per-cpu={mem_per_cpu}")
    if mem_per_gpu:
        sbatch_lines.append(f"#SBATCH --mem-per-gpu={mem_per_gpu}")
    if nodes is not None:
        sbatch_lines.append(f"#SBATCH --nodes={nodes}")
    if ntasks is not None:
        sbatch_lines.append(f"#SBATCH --ntasks={ntasks}")
    if ntasks_per_node is not None:
        sbatch_lines.append(f"#SBATCH --ntasks-per-node={ntasks_per_node}")
    if cpus_per_task is not None:
        sbatch_lines.append(f"#SBATCH --cpus-per-task={cpus_per_task}")
    if gpus:
        sbatch_lines.append(f"#SBATCH --gpus={gpus}")
    if gpus_per_node:
        sbatch_lines.append(f"#SBATCH --gpus-per-node={gpus_per_node}")
    if gpus_per_task is not None:
        sbatch_lines.append(f"#SBATCH --gpus-per-task={gpus_per_task}")
    if gres:
        sbatch_lines.append(f"#SBATCH --gres={gres}")
    if exclusive is True:
        sbatch_lines.append("#SBATCH --exclusive")
    if array_spec:
        sbatch_lines.append(f"#SBATCH --array={array_spec}")
    if out_log is not None:
        sbatch_lines.append(f"#SBATCH --output={out_log}")
    if err_log is not None:
        sbatch_lines.append(f"#SBATCH --error={err_log}")

    for line in extra_sbatch:
        s = str(line).strip()
        if not s:
            continue
        if s.startswith("#SBATCH"):
            sbatch_lines.append(s)
        else:
            sbatch_lines.append(f"#SBATCH {s}")

    cpus_default = cpus_per_task if cpus_per_task is not None else 4
    return "\n".join(sbatch_lines), cpus_default


def _render_submit_script_body(
    *,
    tool_name: str,
    sbatch_block: str,
    prefix: str,
    mode: str,
    display_run_dir: str,
    display_config: str,
    inner_cmd: str,
    cpus_default: int,
    timing_file_expr: str,
    setup_block: str = "",
    gpu_diag_block: str = "",
) -> str:
    """Render the common submit-script body used by point and array modes."""

    script = next(
        (
            arg
            for arg in shlex.split(inner_cmd)
            if PurePath(arg).suffix == ".py"
        ),
        None,
    )

    return f"""{sbatch_block}

set -eo pipefail

# -----------------------------------------------------------------------------
# ValSKA-generated {tool_name} submit script
#
# Mode: {mode}
# Config: {display_config}
# Run dir: {display_run_dir}
# -----------------------------------------------------------------------------

{prefix}
{setup_block}

echo "========================================"
echo "ValSKA / {tool_name} Slurm job starting"
echo "========================================"

START_ISO="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "Start time (UTC):  $START_ISO"
echo "Hostname:          $(hostname)"
echo "Working dir:       $(pwd)"
echo "Run dir:           {display_run_dir}"
echo "Config:            {display_config}"
echo '{tool_name} script:  {script}'
echo "Mode:              {mode}"
echo "----------------------------------------"

export OPENBLAS_NUM_THREADS="${{SLURM_CPUS_PER_TASK:-{cpus_default}}}"
export OMP_NUM_THREADS="${{SLURM_CPUS_PER_TASK:-{cpus_default}}}"

echo "OPENBLAS_NUM_THREADS=$OPENBLAS_NUM_THREADS"
echo "OMP_NUM_THREADS=$OMP_NUM_THREADS"
echo "----------------------------------------"

echo "===== Slurm ENVIRONMENT (begin) ====="
env | sort | grep '^SLURM_' || echo "No SLURM_ variables found"
echo "===== Slurm ENVIRONMENT (end) ====="
echo "----------------------------------------"

echo "Python: $(which python || true)"
python -V || true
echo "----------------------------------------"

{gpu_diag_block}

echo "Command:"
echo "  {inner_cmd}"
echo "----------------------------------------"

# -----------------------------------------------------------------------------
# Timing (UTC) - implemented without relying on /usr/bin/time or shell `time`.
# -----------------------------------------------------------------------------
JOBID="${{SLURM_JOB_ID:-unknown}}"
TIMING_FILE="{timing_file_expr}"

echo "Timing file:       $TIMING_FILE"
echo "----------------------------------------"

START_EPOCH="$(date -u +%s)"
START_NS="$(date -u +%s%N || true)"

set +e
{inner_cmd}
RC=$?
set -e

END_EPOCH="$(date -u +%s)"
END_NS="$(date -u +%s%N || true)"
END_ISO="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

ELAPSED_S="$((END_EPOCH - START_EPOCH))"
ELAPSED_NS=""

if [[ "$START_NS" =~ ^[0-9]+$ ]] && [[ "$END_NS" =~ ^[0-9]+$ ]]; then
  ELAPSED_NS="$((END_NS - START_NS))"
fi

{{
  echo "Start time (UTC):  $START_ISO"
  echo "End time (UTC):    $END_ISO"
  echo "Elapsed (s):       $ELAPSED_S"
  if [[ -n "$ELAPSED_NS" ]]; then
    echo "Elapsed (ns):      $ELAPSED_NS"
  fi
  echo "Exit code:         $RC"
}} > "$TIMING_FILE"

echo "End time (UTC):    $END_ISO"
echo "Elapsed (s):       $ELAPSED_S"
if [[ -n "$ELAPSED_NS" ]]; then
  echo "Elapsed (ns):      $ELAPSED_NS"
fi
echo "Exit code:         $RC"

if [[ $RC -ne 0 ]]; then
  echo "ERROR: {tool_name} command failed with exit code $RC"
  exit $RC
fi

echo "----------------------------------------"
echo "ValSKA / {tool_name} Slurm job complete"
echo "========================================"
"""


def _build_submit_settings(
    *,
    command: str,
    runner: CondaRunner | ContainerRunner,
    slurm: Mapping[str, object],
    run_dir: Path,
    mode: str,
    tool_name: str,
) -> tuple[str, str]:
    """Build the job name, setup prefix and srun command."""

    # -------------------------
    # Job identification
    # -------------------------
    job_name_prefix = (
        get_str_or_none(slurm, "job_name_prefix", tool_name.lower())
        or tool_name.lower()
    )
    job_name = (
        get_str_or_none(slurm, "job_name")
        or f"{job_name_prefix}-{run_dir.name}-{mode}"
    )
    mpi = get_str_or_none(slurm, "mpi", "pmi2") or "pmi2"

    # Use ntasks default for srun if ntasks was None
    ntasks_for_srun = get_int_or_none(slurm, "ntasks", 1) or 1
    srun_prefix = f'srun --mpi={mpi} -n "${{SLURM_NTASKS:-{ntasks_for_srun}}}"'

    inner_cmd = f"{srun_prefix} {runner.python_exe} {command}"

    return job_name, inner_cmd


def render_submit_script(
    *,
    command: str,
    runner: CondaRunner | ContainerRunner,
    config_yaml: Path,
    run_dir: Path,
    slurm: Mapping[str, object] | None = None,
    mode: str = "cpu",
    tool_name: str,
) -> str:
    """
    Render a Slurm submit script for an external tool run.

    This function aims to be HPC-friendly and debugging-friendly:

    - emits clear "what am I running" information
    - prints SLURM_* environment variables (helpful when diagnosing scheduling issues)
    - uses ``srun --mpi=<mpi> -n "$SLURM_NTASKS"`` by default to match common site setups

    Parameters
    ----------
    runner
        How the tool is executed (currently conda; container support later).
    install
        Where the tool lives and how to locate its run script.
    config_yaml
        Path to the rendered toll config YAML to run.
    run_dir
        Run directory containing configs/logs/manifests.
    slurm
        Slurm settings map. Usually derived from runtime_paths.yaml defaults plus CLI overrides.

        **Any key set to ``None`` (or not present) will be omitted from the
        generated script.** This allows cluster-specific suppression of
        directives that are not supported or not needed.

        Supported keys (all optional)::

            Job identification:
              - ``job_name``: Full job name (overrides prefix-based naming)
              - ``job_name_prefix``: Prefix for auto-generated job name
                (default: "bayeseor")
            Resource selection:
              - ``partition``: Partition/queue name (omit for constraint-based scheduling)
              - ``constraint``: Node feature constraint (e.g., "A100", "skylake")
              - ``qos``: Quality of service
              - ``account``: Account/project to charge
              - ``reservation``: Reservation name
            Time and memory:
              - ``time``: Wall time limit (default: "12:00:00")
              - ``mem``: Memory per node (default: "8G")
              - ``mem_per_cpu``: Memory per CPU (mutually exclusive with ``mem``)
              - ``mem_per_gpu``: Memory per GPU
            CPU/task configuration:
              - ``nodes``: Number of nodes (default: 1)
              - ``ntasks``: Total number of tasks (default: 1)
              - ``ntasks_per_node``: Tasks per node (default: 1)
              - ``cpus_per_task``: CPUs per task (default: 4)
            GPU configuration:
              - ``gpus``: Total GPUs (e.g., ``2`` or ``"a100:2"``)
              - ``gpus_per_node``: GPUs per node
              - ``gpus_per_task``: GPUs per task (common for single-GPU jobs)
              - ``gres``: Generic resources (e.g., ``"gpu:1"``, ``"gpu:a100:2"``)
            Execution control:
              - ``mpi``: MPI type for srun (default: "pmi2")
              - ``exclusive``: Request exclusive node access (True emits ``--exclusive``)
            Output:
              - ``output``: Stdout log path (default: ``run_dir/slurm-{mode}-%j.out``)
              - ``error``: Stderr log path (if separate from stdout)
            Extensibility:
              - ``extra_sbatch``: Additional ``#SBATCH`` lines
                (without the ``"#SBATCH "`` prefix)

    mode
        Execution mode (just for BayesEoR module for now):

        - ``"cpu"``: precompute instrument transfer matrices (BayesEoR ``--cpu``)
        - ``"gpu_run"``: run sampling assuming precompute exists
          (BayesEoR ``--gpu --run``)

    Notes on timing
    ---------------
    We intentionally do NOT rely on ``/usr/bin/time`` or shell ``time``, since
    some compute-node images do not provide them. Timing is implemented using
    only:

    - ``date`` (UTC timestamps + epoch seconds)

    This should work essentially everywhere.

    Notes on cluster portability
    ----------------------------
    Different HPC sites have different scheduling policies:

    - Some use ``--partition``, others use ``--constraint``
    - Some require ``--account``, others don't
    - GPU syntax varies: ``--gpus-per-task`` vs ``--gres=gpu:N``

    Set unsupported/unwanted directives to None in your runtime_paths.yaml
    to omit them from generated scripts.
    """
    slurm = dict(slurm or {})

    if mode not in {"cpu", "gpu_run"}:
        raise ValueError("mode must be one of: 'cpu', 'gpu_run'")

    job_name, inner_cmd = _build_submit_settings(
        command=command,
        runner=runner,
        slurm=slurm,
        run_dir=run_dir,
        mode=mode,
        tool_name=tool_name,
    )

    sbatch_block, cpus_default = _build_sbatch_block(
        slurm=slurm,
        job_name=job_name,
        out_log_default=run_dir / f"slurm-{mode}-%j.out",
    )

    return _render_submit_script_body(
        tool_name=tool_name,
        sbatch_block=sbatch_block,
        prefix=runner.bash_prefix,
        mode=mode,
        display_run_dir=str(run_dir),
        display_config=str(config_yaml),
        inner_cmd=inner_cmd,
        cpus_default=cpus_default,
        timing_file_expr=f"{run_dir}/timing-{mode}-${{JOBID}}.txt",
        gpu_diag_block=_gpu_diag_block(mode),
    )


def render_array_submit_script(
    *,
    command: str,
    runner: CondaRunner | ContainerRunner,
    sweep_dir: Path,
    tasks_json: Path,
    config_key: str,
    tool_name: str,
    slurm: Mapping[str, object] | None = None,
    mode: str = "cpu",
    # job_name_suffix: str="",
) -> str:
    """Render a sweep-level Slurm array submit script."""

    if mode not in {"cpu", "gpu_run"}:
        raise ValueError("mode must be one of: 'cpu', 'gpu_run'")

    slurm = dict(slurm or {})

    # TODO: This bit needs to be made common or moved into the module.
    # could add optional job_name_suffix to the arguments:
    # job_name_suffix: str | None = None
    # or specify which mode the sweep is over.
    mode_suffix = mode
    if mode == "gpu_run":
        mode_suffix = f"{mode}-{config_key.removesuffix('_config')}"

    job_name, inner_cmd = _build_submit_settings(
        command=command,
        runner=runner,
        slurm=slurm,
        run_dir=sweep_dir,
        mode=mode_suffix,
        tool_name=tool_name,
    )

    sbatch_block, cpus_default = _build_sbatch_block(
        slurm=slurm,
        job_name=job_name,
        out_log_default=sweep_dir / f"slurm-{mode}-%A_%a.out",
    )

    # This embeds a Python script in a shell heredoc to load the sweep manifest,
    # select the task corresponding to SLURM_ARRAY_TASK_ID, and export task
    # details as shell variables.
    # This logic is currently coupled to the generated Slurm script and assumes a
    # particular manifest structure.
    # TODO: Refactor sweep task loading into a shared helper and validate the manifest
    # with pydantic

    setup_block = f"""
TASKS_JSON="{tasks_json}"
TASK_INDEX="${{SLURM_ARRAY_TASK_ID:?SLURM_ARRAY_TASK_ID must be set for array submission}}"
eval "$({runner.python_exe} - "$TASKS_JSON" "$TASK_INDEX" "{config_key}" <<'PY'
import json
import shlex
import sys
from pathlib import Path

tasks = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if isinstance(tasks, dict):
    tasks = tasks.get("tasks", [])
task = tasks[int(sys.argv[2])]
config_key = sys.argv[3]
print(f"RUN_LABEL={{shlex.quote(task['run_label'])}}")
print(f"RUN_DIR={{shlex.quote(task['run_dir'])}}")
print(f"CONFIG_YAML={{shlex.quote(task[config_key])}}")
print(f"TASK_INDEX={{task['task_index']}}")
PY
)"
cd "$RUN_DIR"
"""

    timing_expr = (
        f"$RUN_DIR/timing-{mode}-${{SLURM_ARRAY_JOB_ID:-${{JOBID}}}}_"
        "${SLURM_ARRAY_TASK_ID:-0}.txt"
    )
    return _render_submit_script_body(
        tool_name=tool_name,
        sbatch_block=sbatch_block,
        prefix=runner.bash_prefix,
        mode=mode,
        display_run_dir="$RUN_DIR",
        display_config="$CONFIG_YAML",
        inner_cmd=inner_cmd,
        cpus_default=cpus_default,
        timing_file_expr=timing_expr,
        setup_block=setup_block,
        gpu_diag_block=_gpu_diag_block(mode),
    )
