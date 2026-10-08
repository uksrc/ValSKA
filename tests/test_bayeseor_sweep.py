import json
from pathlib import Path

from valska.external_tools.bayeseor import sweep as sweep_mod
from valska.external_tools.bayeseor.runner import (
    BayesEoRInstall,
    CondaRunner,
)


def _stub_prepare_factory(base_dir: Path):
    def _prepare(**kwargs):
        run_dir = Path(kwargs["run_dir"])
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "config_signal_fit.yaml").write_text(
            "signal_fit: true\n", encoding="utf-8"
        )
        (run_dir / "config_no_signal.yaml").write_text(
            "signal_fit: false\n", encoding="utf-8"
        )
        (run_dir / "manifest.json").write_text("{}", encoding="utf-8")
        return {
            "run_dir": str(run_dir),
            "manifest_json": str(run_dir / "manifest.json"),
        }

    return _prepare


def test_run_fwhm_sweep_array_mode_generates_expected_scripts(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        sweep_mod,
        "prepare_bayeseor_run",
        _stub_prepare_factory(tmp_path),
    )

    result = sweep_mod.run_fwhm_sweep(
        template_yaml=tmp_path / "template.yaml",
        install=BayesEoRInstall(repo_path=tmp_path / "BayesEoR"),
        runner=CondaRunner(
            conda_activate="source /tmp/conda.sh", env_name="bayeseor"
        ),
        results_root=tmp_path / "results",
        beam_model="achromatic_Gaussian",
        sky_model="GSM",
        variant="validation_achromatic_Gaussian",
        run_id="sweep_v3",
        data_path=tmp_path / "input.uvh5",
        perturb_parameter="fwhm_deg",
        perturb_fracs=[
            -0.2,
            -0.1,
            -0.05,
            -0.02,
            -0.01,
            0.0,
            0.01,
            0.02,
            0.05,
            0.1,
            0.2,
        ],
        slurm_cpu={"ntasks": 1, "cpus_per_task": 4},
        slurm_gpu={"ntasks": 1, "cpus_per_task": 4, "gpus_per_task": 1},
        submit_mode="array",
        array_max_cpu=4,
        array_max_gpu=2,
    )

    cpu_script = result.sweep_dir / "submit_cpu_precompute_array.sh"
    gpu_script = result.sweep_dir / "submit_signal_fit_gpu_array.sh"
    assert "#SBATCH --array=0-10%4" in cpu_script.read_text(encoding="utf-8")
    assert "#SBATCH --array=0-10%2" in gpu_script.read_text(encoding="utf-8")

    tasks_json = json.loads(
        (result.sweep_dir / "array_tasks.json").read_text(encoding="utf-8")
    )
    assert len(tasks_json["tasks"]) == 11
    assert tasks_json["tasks"][0]["task_index"] == 0


def test_run_fwhm_sweep_array_submit_all_records_one_cpu_and_two_gpu_jobs(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        sweep_mod,
        "prepare_bayeseor_run",
        _stub_prepare_factory(tmp_path),
    )

    calls: list[tuple[str, str | None]] = []

    def _fake_run_sbatch(
        script: Path,
        *,
        dependency_afterok: str | None = None,
        sbatch_exe: str = "sbatch",
        cwd: Path | None = None,
        dry_run: bool = False,
    ):
        calls.append((script.name, dependency_afterok))
        job_ids = {
            "submit_cpu_precompute_array.sh": "5001",
            "submit_signal_fit_gpu_array.sh": "5002",
            "submit_no_signal_gpu_array.sh": "5003",
        }
        return job_ids[script.name], f"sbatch {script}"

    monkeypatch.setattr(sweep_mod, "_run_sbatch", _fake_run_sbatch)

    result = sweep_mod.run_fwhm_sweep(
        template_yaml=tmp_path / "template.yaml",
        install=BayesEoRInstall(repo_path=tmp_path / "BayesEoR"),
        runner=CondaRunner(
            conda_activate="source /tmp/conda.sh", env_name="bayeseor"
        ),
        results_root=tmp_path / "results",
        beam_model="achromatic_Gaussian",
        sky_model="GSM",
        variant="validation_achromatic_Gaussian",
        run_id="sweep_v3",
        data_path=tmp_path / "input.uvh5",
        perturb_parameter="fwhm_deg",
        perturb_fracs=[0.0] * 11,
        slurm_cpu={"ntasks": 1, "cpus_per_task": 4},
        slurm_gpu={"ntasks": 1, "cpus_per_task": 4, "gpus_per_task": 1},
        submit="all",
        submit_mode="array",
        array_max_cpu=4,
        array_max_gpu=2,
    )

    assert calls == [
        ("submit_cpu_precompute_array.sh", None),
        ("submit_signal_fit_gpu_array.sh", "5001"),
        ("submit_no_signal_gpu_array.sh", "5001"),
    ]
    submit_result = result.submit_results[0]
    assert submit_result["jobs"]["cpu_precompute_array"]["job_id"] == "5001"
    assert submit_result["jobs"]["gpu_array"]["signal_fit"]["job_id"] == "5002"
    assert submit_result["jobs"]["gpu_array"]["no_signal"]["job_id"] == "5003"
    assert submit_result["jobs"]["gpu_array"]["dependency"] == "afterok:5001"
    assert (
        submit_result["jobs"]["gpu_array"]["signal_fit"]["dependency"]
        == "afterok:5001"
    )
    assert (
        submit_result["jobs"]["gpu_array"]["no_signal"]["dependency"]
        == "afterok:5001"
    )

    jobs_json = json.loads(result.sweep_jobs_json.read_text(encoding="utf-8"))
    assert jobs_json["submit_mode"] == "array"
    assert jobs_json["dry_run"] is False
    assert jobs_json["array_max_cpu"] == 4
    assert jobs_json["array_max_gpu"] == 2
    assert jobs_json["jobs"]["cpu_precompute_array"]["command"].startswith(
        "sbatch "
    )


def test_run_fwhm_sweep_array_submit_all_dry_run_writes_jobs_json_and_placeholder_dependency(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        sweep_mod,
        "prepare_bayeseor_run",
        _stub_prepare_factory(tmp_path),
    )

    result = sweep_mod.run_fwhm_sweep(
        template_yaml=tmp_path / "template.yaml",
        install=BayesEoRInstall(repo_path=tmp_path / "BayesEoR"),
        runner=CondaRunner(
            conda_activate="source /tmp/conda.sh", env_name="bayeseor"
        ),
        results_root=tmp_path / "results",
        beam_model="achromatic_Gaussian",
        sky_model="GSM",
        variant="validation_achromatic_Gaussian",
        run_id="sweep_v3",
        data_path=tmp_path / "input.uvh5",
        perturb_parameter="fwhm_deg",
        perturb_fracs=[0.0] * 11,
        slurm_cpu={"ntasks": 1, "cpus_per_task": 4},
        slurm_gpu={"ntasks": 1, "cpus_per_task": 4, "gpus_per_task": 1},
        submit="all",
        submit_mode="array",
        array_max_cpu=4,
        array_max_gpu=2,
        submit_dry_run=True,
    )

    assert result.sweep_jobs_json is not None
    assert result.sweep_jobs_json.exists()
    assert "error" not in result.submit_results[0]

    jobs_json = json.loads(result.sweep_jobs_json.read_text(encoding="utf-8"))
    cpu_job = jobs_json["jobs"]["cpu_precompute_array"]
    gpu_jobs = jobs_json["jobs"]["gpu_array"]
    dependency = f"afterok:{sweep_mod._DRY_RUN_CPU_ARRAY_JOB_ID}"

    assert jobs_json["submit_mode"] == "array"
    assert jobs_json["dry_run"] is True
    assert jobs_json["array_max_cpu"] == 4
    assert jobs_json["array_max_gpu"] == 2
    assert cpu_job["job_id"] == sweep_mod._DRY_RUN_CPU_ARRAY_JOB_ID
    assert cpu_job["job_id_is_placeholder"] is True
    assert (
        gpu_jobs["signal_fit"]["job_id"]
        == sweep_mod._DRY_RUN_SIGNAL_FIT_GPU_ARRAY_JOB_ID
    )
    assert (
        gpu_jobs["no_signal"]["job_id"]
        == sweep_mod._DRY_RUN_NO_SIGNAL_GPU_ARRAY_JOB_ID
    )
    assert gpu_jobs["dependency"] == dependency
    assert gpu_jobs["signal_fit"]["dependency"] == dependency
    assert gpu_jobs["no_signal"]["dependency"] == dependency
    assert dependency in gpu_jobs["signal_fit"]["command"]
    assert dependency in gpu_jobs["no_signal"]["command"]

    sweep_manifest = json.loads(
        result.sweep_manifest_json.read_text(encoding="utf-8")
    )
    assert "error" not in sweep_manifest["submit_results"][0]

    cpu_script = result.sweep_dir / "submit_cpu_precompute_array.sh"
    signal_script = result.sweep_dir / "submit_signal_fit_gpu_array.sh"
    no_signal_script = result.sweep_dir / "submit_no_signal_gpu_array.sh"
    assert "#SBATCH --array=0-10%4" in cpu_script.read_text(encoding="utf-8")
    assert "#SBATCH --array=0-10%2" in signal_script.read_text(
        encoding="utf-8"
    )
    assert "#SBATCH --array=0-10%2" in no_signal_script.read_text(
        encoding="utf-8"
    )


def test_run_fwhm_sweep_array_gpu_requires_known_cpu_dependency(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        sweep_mod,
        "prepare_bayeseor_run",
        _stub_prepare_factory(tmp_path),
    )

    result = sweep_mod.run_fwhm_sweep(
        template_yaml=tmp_path / "template.yaml",
        install=BayesEoRInstall(repo_path=tmp_path / "BayesEoR"),
        runner=CondaRunner(
            conda_activate="source /tmp/conda.sh", env_name="bayeseor"
        ),
        results_root=tmp_path / "results",
        beam_model="achromatic_Gaussian",
        sky_model="GSM",
        variant="validation_achromatic_Gaussian",
        run_id="sweep_v3",
        data_path=tmp_path / "input.uvh5",
        perturb_parameter="fwhm_deg",
        perturb_fracs=[0.0] * 11,
        slurm_cpu={"ntasks": 1, "cpus_per_task": 4},
        slurm_gpu={"ntasks": 1, "cpus_per_task": 4, "gpus_per_task": 1},
        submit="gpu",
        submit_mode="array",
        array_max_cpu=4,
        array_max_gpu=2,
    )

    assert "error" in result.submit_results[0]
    assert (
        "GPU array submission requested but no CPU array dependency is known"
        in result.submit_results[0]["error"]
    )
