from pathlib import Path

import pytest

from valska.external_tools.pyuvsim.runner import (
    CondaRunner,
    pyuvsimInstall,
)
from valska.external_tools.pyuvsim.slurm import render_submit_script


def _render_script(mode: str) -> str:
    return render_submit_script(
        runner=CondaRunner(
            conda_activate="source /opt/conda/etc/profile.d/conda.sh",
            env_name="pyuvsim",
        ),
        install=pyuvsimInstall(install_path=Path("/opt/pyuvsim")),
        config_yaml=Path("/tmp/config.yaml"),
        run_dir=Path("/tmp/run"),
        slurm={"partition": "standard", "cpus_per_task": 4, "ntasks": 1},
        mode=mode,
    )


def test_render_submit_script_fails_if_not_simulate():
    with pytest.raises(ValueError):
        _render_script("cpu")


def test_render_submit_script_returns_script(simulate_script):
    assert simulate_script.startswith("#!/bin/bash")
    assert "#SBATCH" in simulate_script


def test_render_submit_script_has_specified_conda_setup(simulate_script):
    assert (
        "source /opt/conda/etc/profile.d/conda.sh\nconda activate pyuvsim"
        in simulate_script
    )


def test_render_submit_script_has_specified_partition(simulate_script):
    assert "#SBATCH --partition=standard" in simulate_script


def test_render_submit_script_preserves_slurm_directives():
    script = render_submit_script(
        runner=CondaRunner(
            conda_activate="source /opt/conda/etc/profile.d/conda.sh",
            env_name="pyuvsim",
        ),
        install=pyuvsimInstall(install_path=Path("/opt/pyuvsim")),
        config_yaml=Path("/tmp/config.yaml"),
        run_dir=Path("/tmp/run"),
        slurm={
            "partition": "standard",
            "account": "my_project",
            "time": "02:00:00",
            "nodes": 2,
            "ntasks": 8,
            "cpus_per_task": 16,
        },
        mode="simulate",
    )

    assert "#SBATCH --partition=standard" in script
    assert "#SBATCH --account=my_project" in script
    assert "#SBATCH --time=02:00:00" in script
    assert "#SBATCH --nodes=2" in script
    assert "#SBATCH --ntasks=8" in script
    assert "#SBATCH --cpus-per-task=16" in script


def test_render_submit_script_omits_none_slurm_options():
    script = render_submit_script(
        runner=CondaRunner(
            conda_activate="source /opt/conda/etc/profile.d/conda.sh",
            env_name="pyuvsim",
        ),
        install=None,
        config_yaml=Path("/tmp/config.yaml"),
        run_dir=Path("/tmp/run"),
        slurm={
            "partition": None,
            "account": None,
            "time": "01:00:00",
        },
        mode="simulate",
    )

    assert "#SBATCH --partition=" not in script
    assert "#SBATCH --account=" not in script
    assert "#SBATCH --time=01:00:00" in script


def test_render_submit_script_uses_timing_file():
    script = _render_script("simulate")

    assert 'TIMING_FILE="/tmp/run/timing-simulate-${JOBID}.txt"' in script


def test_render_submit_script_embeds_pyuvsim_command():
    script = _render_script("simulate")

    assert "pyuvsim.uvsim.run_uvsim" in script
    assert "config.yaml" in script
    assert 'mpirun -n "${SLURM_NTASKS:-1}"' in script


def test_render_submit_script_exports_thread_settings():
    script = _render_script("simulate")

    assert "OPENBLAS_NUM_THREADS" in script
    assert "OMP_NUM_THREADS" in script


def test_render_submit_script_records_install_path():
    script = _render_script("simulate")

    assert "pyuvsim install:   /opt/pyuvsim" in script


def test_render_submit_script_contains_import_check():
    script = _render_script("simulate")

    assert 'python -c "import pyuvsim; import pyuvsim.uvsim"' in script


def test_render_submit_script_preserves_extra_sbatch():
    script = render_submit_script(
        runner=CondaRunner(
            conda_activate="source /opt/conda/etc/profile.d/conda.sh",
            env_name="pyuvsim",
        ),
        install=None,
        config_yaml=Path("/tmp/config.yaml"),
        run_dir=Path("/tmp/run"),
        slurm={
            "extra_sbatch": [
                "--mail-user=test@example.com",
                "#SBATCH --mail-type=END",
            ]
        },
        mode="simulate",
    )

    assert "#SBATCH --mail-user=test@example.com" in script
    assert "#SBATCH --mail-type=END" in script
