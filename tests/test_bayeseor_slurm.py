from pathlib import Path

from valska.external_tools.bayeseor.runner import (
    BayesEoRInstall,
    CondaRunner,
)
from valska.external_tools.bayeseor.slurm import (
    render_array_submit_script,
    render_submit_script,
)


def _render_script(mode: str) -> str:
    return render_submit_script(
        runner=CondaRunner(
            conda_activate="source /opt/conda/etc/profile.d/conda.sh",
            env_name="bayeseor",
        ),
        install=BayesEoRInstall(repo_path=Path("/opt/BayesEoR")),
        config_yaml=Path("/tmp/config.yaml"),
        run_dir=Path("/tmp/run"),
        slurm={"partition": "a100_gpu", "cpus_per_task": 4, "ntasks": 1},
        mode=mode,
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


def test_render_submit_script_includes_array_directive_when_requested():
    script = render_submit_script(
        runner=CondaRunner(
            conda_activate="source /opt/conda/etc/profile.d/conda.sh",
            env_name="bayeseor",
        ),
        install=BayesEoRInstall(repo_path=Path("/opt/BayesEoR")),
        config_yaml=Path("/tmp/config.yaml"),
        run_dir=Path("/tmp/run"),
        slurm={
            "partition": "a100_gpu",
            "cpus_per_task": 4,
            "ntasks": 1,
            "array": "0-10%4",
        },
        mode="cpu",
    )

    assert "#SBATCH --array=0-10%4" in script


def test_render_array_submit_script_includes_task_lookup_and_array_header():
    script = render_array_submit_script(
        runner=CondaRunner(
            conda_activate="source /opt/conda/etc/profile.d/conda.sh",
            env_name="bayeseor",
        ),
        install=BayesEoRInstall(repo_path=Path("/opt/BayesEoR")),
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
    )

    assert "#SBATCH --array=0-10%4" in script
    assert 'TASKS_JSON="/tmp/sweep/array_tasks.json"' in script
    assert (
        'TASK_INDEX="${SLURM_ARRAY_TASK_ID:?SLURM_ARRAY_TASK_ID must be set for array submission}"'
        in script
    )
    assert 'CONFIG_YAML="$CONFIG_YAML"' not in script
