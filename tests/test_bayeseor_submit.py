import json
from pathlib import Path

import pytest

from valska.external_tools.bayeseor import cli_submit
from valska.external_tools.bayeseor.submit import (
    BayesEoRRunOptions,
    BayesEoRSubmitPlan,
)
from valska.external_tools.common.submit import (
    MissingDependencyError,
    submit_tool_run,
)


def _write_submit_fixture(run_dir: Path) -> None:
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


def _write_jobs_json(run_dir: Path, payload: dict) -> None:
    (run_dir / "jobs.json").write_text(json.dumps(payload), encoding="utf-8")


def _write_completed_cpu_outputs(run_dir: Path) -> Path:
    matrix_dir = run_dir / "matrices" / "example_stack"
    matrix_dir.mkdir(parents=True, exist_ok=True)
    (matrix_dir / "Ninv.npz").write_text("placeholder", encoding="utf-8")
    (matrix_dir / "T_Ninv_T.h5").write_text("placeholder", encoding="utf-8")
    return matrix_dir


def test_submit_gpu_uses_recorded_dependency_when_outputs_missing(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_submit_fixture(run_dir)
    _write_jobs_json(
        run_dir,
        {"jobs": {"cpu_precompute": {"job_id": "12345"}}},
    )

    result = submit_tool_run(
        run_dir,
        stage_id="gpu",
        submit_plan=BayesEoRSubmitPlan,
        options=BayesEoRRunOptions(dry_run=True),
    )

    jobs = result.get("jobs")

    assert jobs["jobs"]["gpu"]["dependency"] == "afterok:12345"
    assert jobs["jobs"]["gpu"]["dependency_source"] == "jobs_json"
    assert "--dependency=afterok:12345" in result["commands"][0]
    assert "--dependency=afterok:12345" in result["commands"][1]


def test_submit_gpu_skips_dependency_when_cpu_outputs_verified(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_submit_fixture(run_dir)
    matrix_dir = _write_completed_cpu_outputs(run_dir)
    _write_jobs_json(
        run_dir,
        {"jobs": {"cpu_precompute": {"job_id": "12345"}}},
    )

    result = submit_tool_run(
        run_dir,
        stage_id="gpu",
        submit_plan=BayesEoRSubmitPlan,
        options=BayesEoRRunOptions(dry_run=True),
    )

    jobs = result.get("jobs")

    assert jobs["jobs"]["gpu"]["dependency"] is None
    assert (
        jobs["jobs"]["gpu"]["dependency_source"]
        == "cpu_precompute_outputs_verified"
    )
    assert jobs["jobs"]["gpu"]["cpu_precompute_matrix_dir"] == str(matrix_dir)
    assert "--dependency=" not in result["commands"][0]
    assert "--dependency=" not in result["commands"][1]


def test_submit_gpu_requires_dependency_or_completed_outputs(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_submit_fixture(run_dir)

    with pytest.raises(MissingDependencyError):
        submit_tool_run(
            run_dir,
            stage_id="gpu",
            submit_plan=BayesEoRSubmitPlan,
            options=BayesEoRRunOptions(dry_run=True),
        )


def test_cli_submit_allows_gpu_when_completed_cpu_outputs_exist(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_submit_fixture(run_dir)
    _write_completed_cpu_outputs(run_dir)
    _write_jobs_json(run_dir, {"jobs": {}})

    code = cli_submit.main([str(run_dir), "--stage", "gpu", "--dry-run"])

    assert code == 0
