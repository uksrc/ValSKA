"""Utils for testing"""

import json
from pathlib import Path

import numpy
from scipy.constants import c as speed_of_light
from scipy.special import j1

from tests.mocks import MockChain


def mock_read_chains(*args, **kwargs):
    """
    Mock method to replace anesthetic read_chains()
    """
    return MockChain(args[0])


def make_gaussian_data(
    theta,
    sigma=2.0,
    amplitude=1.0,
    centre=0.0,
):
    """Make Gaussian data"""
    return amplitude * numpy.exp(-((theta - centre) ** 2) / (2 * sigma**2))


def make_airy_data(
    freq_hz,
    theta,
    amplitude=1.0,
    centre=0.0,
    diameter=5.0,
):
    """Make Airy data"""

    lam = speed_of_light / freq_hz

    x = numpy.pi * diameter * numpy.sin(theta - centre) / lam
    beam = numpy.ones_like(x)
    mask = numpy.abs(x) > 1e-12

    beam[mask] = (2 * j1(x[mask]) / x[mask]) ** 2

    return amplitude * beam


def write_pyuvsim_config(tmp_path, config_text):
    """Write pyuvsim config file"""
    path = tmp_path / "config.yaml"
    path.write_text(config_text)
    return path


def write_bayeseor_submit_fixture(run_dir: Path) -> None:
    scripts = {
        "submit_cpu_precompute.sh": "#!/bin/bash\n",
        "submit_signal_fit_gpu_run.sh": "#!/bin/bash\n",
        "submit_no_signal_gpu_run.sh": "#!/bin/bash\n",
    }
    for name, content in scripts.items():
        path = run_dir / name
        path.write_text(content, encoding="utf-8")
        path.chmod(0o750)

    manifest = {
        "artefacts": {
            "submit_sh_cpu_precompute": "submit_cpu_precompute.sh",
            "submit_sh_signal_fit_gpu_run": "submit_signal_fit_gpu_run.sh",
            "submit_sh_no_signal_gpu_run": "submit_no_signal_gpu_run.sh",
        },
        "bayeseor": {"cpu_precompute_driver_hypothesis": "signal_fit"},
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )


def write_pyuvsim_submit_fixture(run_dir: Path) -> None:
    scripts = {
        "submit_simulate.sh": "#!/bin/bash\n",
        "submit_beamcheck.sh": "#!/bin/bash\n",
    }
    for name, content in scripts.items():
        path = run_dir / name
        path.write_text(content, encoding="utf-8")
        path.chmod(0o750)

    manifest = {
        "artefacts": {
            "submit_sh_simulate": "submit_simulate.sh",
            "submit_sh_beamcheck": "submit_beamcheck.sh",
        },
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )


def mock_sbatch(monkeypatch, tool_name):
    """Mock sbatch submission to Slurm"""

    job_ids = iter(["10101", "20202", "30303", "40404"])
    submissions = []

    def fake_run_sbatch(
        script,
        *,
        dependency_afterok=None,
        sbatch_exe="sbatch",
        cwd=None,
        dry_run=False,
    ):
        jobid = next(job_ids)
        submissions.append(
            {
                "script": Path(script),
                "job_id": jobid,
                "dependency_afterok": dependency_afterok,
                "sbatch_exe": sbatch_exe,
                "cwd": Path(cwd),
                "dry_run": dry_run,
            }
        )

        command = f"{sbatch_exe} {script}"
        if dependency_afterok is not None:
            command += f" --dependency=afterok:{dependency_afterok}"

        return jobid, command

    monkeypatch.setattr(
        f"valska.external_tools.{tool_name}.submit.run_sbatch",
        fake_run_sbatch,
    )
    return submissions


def write_jobs_json(run_dir: Path, payload: dict) -> None:
    (run_dir / "jobs.json").write_text(json.dumps(payload), encoding="utf-8")


def write_bayeseor_completed_cpu_outputs(run_dir: Path) -> Path:
    matrix_dir = run_dir / "matrices" / "example_stack"
    matrix_dir.mkdir(parents=True, exist_ok=True)
    (matrix_dir / "Ninv.npz").write_text("placeholder", encoding="utf-8")
    (matrix_dir / "T_Ninv_T.h5").write_text("placeholder", encoding="utf-8")
    return matrix_dir
