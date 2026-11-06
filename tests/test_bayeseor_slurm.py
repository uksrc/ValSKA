from pathlib import Path

import pytest

from valska.external_tools.bayeseor.constants import TOOL_NAME
from valska.external_tools.common.runner import CondaRunner
from valska.external_tools.common.slurm import (
    render_array_submit_script,
    render_submit_script,
)


def _render_script(mode: str) -> str:
    return render_submit_script(
        runner=CondaRunner(
            conda_activate="source /opt/conda/etc/profile.d/conda.sh",
            env_name="bayeseor",
        ),
        config_yaml=Path("/tmp/config.yaml"),
        run_dir=Path("/tmp/run"),
        slurm={"partition": "a100_gpu", "cpus_per_task": 4, "ntasks": 1},
        mode=mode,
        command="sample command",
        tool_name=TOOL_NAME,
    )


def test_render_submit_script_gpu_run_includes_non_blocking_gpu_diagnostics():
    script = _render_script("gpu_run")

    assert 'echo "Hostname:          $(hostname)"' in script
    assert (
        'echo "CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-<unset>}"'
        in script
    )
    assert "if command -v nvidia-smi >/dev/null 2>&1; then" in script
    assert "nvidia-smi -L || true" in script
    assert 'echo "nvidia-smi not found on PATH"' in script


def test_render_submit_script_cpu_omits_gpu_diagnostics():
    script = _render_script("cpu")

    assert "CUDA_VISIBLE_DEVICES" not in script
    assert "nvidia-smi -L || true" not in script


def test_render_submit_script_includes_execution_details():
    script = _render_script("cpu")

    assert "source /opt/conda/etc/profile.d/conda.sh" in script
    assert "conda activate bayeseor" in script
    assert "sample command" in script

    assert "/tmp/run" in script
    assert "/tmp/config.yaml" in script

    assert "timing-cpu-${JOBID}.txt" in script
    assert "SLURM_JOB_ID" in script


def test_render_submit_script_preserves_slurm_directives():
    script = render_submit_script(
        runner=CondaRunner(
            conda_activate="source /opt/conda/etc/profile.d/conda.sh",
            env_name="bayeseor",
        ),
        config_yaml=Path("/tmp/config.yaml"),
        run_dir=Path("/tmp/run"),
        slurm={
            "partition": "a100_gpu",
            "account": "my_project",
            "time": "02:00:00",
            "nodes": 1,
            "ntasks": 2,
            "cpus_per_task": 4,
            "gpus_per_task": 1,
        },
        mode="gpu_run",
        command="sample command",
        tool_name=TOOL_NAME,
    )

    assert "#SBATCH --partition=a100_gpu" in script
    assert "#SBATCH --account=my_project" in script
    assert "#SBATCH --time=02:00:00" in script
    assert "#SBATCH --nodes=1" in script
    assert "#SBATCH --ntasks=2" in script
    assert "#SBATCH --cpus-per-task=4" in script
    assert "#SBATCH --gpus-per-task=1" in script

    assert "#SBATCH --output=/tmp/run/slurm-gpu_run-%j.out" in script


def test_render_submit_script_omits_none_slurm_options():
    script = render_submit_script(
        runner=CondaRunner(
            conda_activate="source /opt/conda/etc/profile.d/conda.sh",
            env_name="bayeseor",
        ),
        config_yaml=Path("/tmp/config.yaml"),
        run_dir=Path("/tmp/run"),
        slurm={
            "partition": None,
            "account": None,
            "time": "02:00:00",
            "cpus_per_task": 4,
        },
        mode="cpu",
        command="sample command",
        tool_name=TOOL_NAME,
    )

    assert "#SBATCH --partition=" not in script
    assert "#SBATCH --account=" not in script
    assert "#SBATCH --time=02:00:00" in script
    assert "#SBATCH --cpus-per-task=4" in script


def test_render_submit_script_includes_array_directive_when_requested():
    script = render_submit_script(
        runner=CondaRunner(
            conda_activate="source /opt/conda/etc/profile.d/conda.sh",
            env_name="bayeseor",
        ),
        command="test command",
        config_yaml=Path("/tmp/config.yaml"),
        run_dir=Path("/tmp/run"),
        slurm={
            "partition": "a100_gpu",
            "cpus_per_task": 4,
            "ntasks": 1,
            "array": "0-10%4",
        },
        mode="cpu",
        tool_name=TOOL_NAME,
    )

    assert "#SBATCH --array=0-10%4" in script


def test_render_array_submit_script_includes_task_lookup_and_array_header():
    script = render_array_submit_script(
        command="test command",
        runner=CondaRunner(
            conda_activate="source /opt/conda/etc/profile.d/conda.sh",
            env_name="bayeseor",
        ),
        sweep_dir=Path("/tmp/sweep"),
        tasks_json=Path("/tmp/sweep/array_tasks.json"),
        config_key="cpu_config",
        slurm={
            "partition": "a100_gpu",
            "cpus_per_task": 4,
            "ntasks": 1,
            "array": "0-10%4",
        },
        mode="cpu",
        tool_name=TOOL_NAME,
    )

    # Slurm array configuration
    assert "#SBATCH --array=0-10%4" in script
    assert "#SBATCH --output=/tmp/sweep/slurm-cpu-%A_%a.out" in script

    # Manifest loading
    assert 'TASKS_JSON="/tmp/sweep/array_tasks.json"' in script
    assert (
        'TASK_INDEX="${SLURM_ARRAY_TASK_ID:?SLURM_ARRAY_TASK_ID must be set for array submission}"'
        in script
    )

    # Embedded Python task selection
    assert "json.loads(Path(sys.argv[1]).read_text" in script
    assert 'tasks = tasks.get("tasks", [])' in script
    assert "task = tasks[int(sys.argv[2])]" in script
    assert "config_key = sys.argv[3]" in script

    # Export task information safely
    assert "shlex.quote(task['run_label'])" in script
    assert "shlex.quote(task['run_dir'])" in script
    assert "shlex.quote(task[config_key])" in script

    # Change to the selected run directory
    assert 'cd "$RUN_DIR"' in script

    # The selected config is used by the execution body
    assert 'CONFIG_YAML="$CONFIG_YAML"' not in script
    assert "display_config" not in script


def test_render_array_submit_script_uses_array_specific_timing_file():
    script = render_array_submit_script(
        command="test command",
        runner=CondaRunner(
            conda_activate="source /opt/conda/etc/profile.d/conda.sh",
            env_name="bayeseor",
        ),
        sweep_dir=Path("/tmp/sweep"),
        tasks_json=Path("/tmp/sweep/array_tasks.json"),
        config_key="cpu_config",
        slurm={},
        mode="cpu",
        tool_name=TOOL_NAME,
    )

    assert (
        "$RUN_DIR/timing-cpu-${SLURM_ARRAY_JOB_ID:-${JOBID}}_"
        "${SLURM_ARRAY_TASK_ID:-0}.txt"
    ) in script


@pytest.mark.parametrize("mode", ["invalid", "GPU", "", "cuda"])
def test_render_submit_script_rejects_invalid_mode(mode):
    runner = CondaRunner(
        conda_activate="source /opt/conda/etc/profile.d/conda.sh",
        env_name="bayeseor",
    )

    with pytest.raises(ValueError, match="mode must be one of"):
        render_submit_script(
            command="test command",
            runner=runner,
            config_yaml=Path("/tmp/config.yaml"),
            run_dir=Path("/tmp/run"),
            slurm={},
            mode=mode,
            tool_name=TOOL_NAME,
        )


@pytest.mark.parametrize("mode", ["invalid", "GPU", "", "cuda"])
def test_render_array_submit_script_rejects_invalid_mode(mode):
    runner = CondaRunner(
        conda_activate="source /opt/conda/etc/profile.d/conda.sh",
        env_name="bayeseor",
    )

    with pytest.raises(ValueError, match="mode must be one of"):
        render_array_submit_script(
            command="test command",
            runner=runner,
            tasks_json=Path("/tmp/sweep/array_tasks.json"),
            config_key="cpu_config",
            sweep_dir=Path("/tmp/sweep"),
            slurm={},
            mode=mode,
            tool_name=TOOL_NAME,
        )


def test_render_submit_script_includes_inner_command():

    runner = CondaRunner(
        conda_activate="source /opt/conda/etc/profile.d/conda.sh",
        env_name="bayeseor",
    )
    command = "bayeseor run"

    script = render_submit_script(
        runner=runner,
        config_yaml=Path("/tmp/config.yaml"),
        run_dir=Path("/tmp/run"),
        slurm={
            "partition": "a100_gpu",
            "cpus_per_task": 4,
            "ntasks": 1,
        },
        mode="cpu",
        command=command,
        tool_name=TOOL_NAME,
    )

    srun_prefix = 'srun --mpi=pmi2 -n "${SLURM_NTASKS:-1}"'
    expected_inner_cmd = f"{srun_prefix} {runner.python_exe} {command}"

    assert expected_inner_cmd in script
    assert "/tmp/config.yaml" in script


def test_render_array_submit_script_includes_inner_command():
    runner = CondaRunner(
        conda_activate="source /opt/conda/etc/profile.d/conda.sh",
        env_name="bayeseor",
    )
    command = "bayeseor run"

    script = render_array_submit_script(
        runner=runner,
        tasks_json=Path("/tmp/sweep/array_tasks.json"),
        config_key="cpu_config",
        sweep_dir=Path("/tmp/sweep"),
        slurm={
            "partition": "a100_gpu",
            "cpus_per_task": 4,
            "ntasks": 1,
        },
        mode="cpu",
        command=command,
        tool_name=TOOL_NAME,
    )

    srun_prefix = 'srun --mpi=pmi2 -n "${SLURM_NTASKS:-1}"'
    expected_inner_cmd = f"{srun_prefix} {runner.python_exe} {command}"

    assert expected_inner_cmd in script
    assert "$CONFIG_YAML" in script
    assert 'cd "$RUN_DIR"' in script
