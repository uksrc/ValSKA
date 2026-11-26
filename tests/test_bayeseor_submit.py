import json
from pathlib import Path

import pytest

from tests.utils import (
    mock_sbatch,
    write_bayeseor_completed_cpu_outputs,
    write_bayeseor_submit_fixture,
    write_jobs_json,
)
from valska.external_tools.bayeseor import cli_submit
from valska.external_tools.bayeseor.submit import (
    BayesEoRRunOptions,
    BayesEoRSubmitPlan,
)
from valska.external_tools.common.submit import (
    MissingDependencyError,
    submit_tool_run,
)


def test_submit_bayeseor_run_exists():
    """Test for backwards compatibility"""
    from valska.external_tools.bayeseor import submit_bayeseor_run

    assert callable(submit_bayeseor_run)


def test_submit_all_preserves_stage_order_paths_and_jobs_json(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """
    Tests end-to-end behavior: submission order, script paths, command arguments,
    job IDs, and persisted records.
    """
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    write_bayeseor_submit_fixture(run_dir)

    run_dir = run_dir.resolve()

    submissions = mock_sbatch(monkeypatch, "bayeseor")

    result = submit_tool_run(
        run_dir,
        stage_id="all",
        submit_plan=BayesEoRSubmitPlan,
        options=BayesEoRRunOptions(
            hypothesis="both",
            depend_afterok=None,
            sbatch_exe="fake-sbatch",
            dry_run=False,
            force=False,
            record="jobs.json",
        ),
    )

    # 1. CPU is submitted first; both GPU jobs depend on its job ID.
    assert [s["script"].name for s in submissions] == [
        "submit_cpu_precompute.sh",
        "submit_signal_fit_gpu_run.sh",
        "submit_no_signal_gpu_run.sh",
    ]

    assert [s["job_id"] for s in submissions] == [
        "10101",
        "20202",
        "30303",
    ]

    assert [s["dependency_afterok"] for s in submissions] == [
        None,
        "10101",
        "10101",
    ]

    assert all(s["cwd"] == run_dir for s in submissions)
    assert all(s["sbatch_exe"] == "fake-sbatch" for s in submissions)
    assert all(s["dry_run"] is False for s in submissions)

    # 2. The returned commands preserve stage ordering and dependencies.
    assert len(result["commands"]) == 3
    assert "submit_cpu_precompute.sh" in result["commands"][0]
    assert "submit_signal_fit_gpu_run.sh" in result["commands"][1]
    assert "submit_no_signal_gpu_run.sh" in result["commands"][2]

    assert "--dependency=afterok:10101" in result["commands"][1]
    assert "--dependency=afterok:10101" in result["commands"][2]

    # 3. Script paths and module-specific metadata are preserved.
    jobs = result["jobs"]

    # Check that jobs structure is set up correctly and not nested
    assert "jobs" not in result["jobs"]

    assert set(jobs) == {"cpu_precompute", "gpu"}

    assert jobs["cpu_precompute"] == {
        "script": str(run_dir / "submit_cpu_precompute.sh"),
        "job_id": "10101",
        "cpu_precompute_driver_hypothesis": "signal_fit",
    }

    assert jobs["gpu"] == {
        "dependency": "afterok:10101",
        "dependency_source": "same_invocation_cpu",
        "signal_fit": {
            "script": str(run_dir / "submit_signal_fit_gpu_run.sh"),
            "job_id": "20202",
        },
        "no_signal": {
            "script": str(run_dir / "submit_no_signal_gpu_run.sh"),
            "job_id": "30303",
        },
    }

    assert result["hypothesis"] == "both"

    # 4. The on-disk record agrees with the returned record.
    jobs_path = run_dir / "jobs.json"
    assert jobs_path.is_file()

    saved = json.loads(jobs_path.read_text(encoding="utf-8"))

    assert saved["jobs"]["cpu_precompute"] == jobs["cpu_precompute"]
    assert saved["jobs"]["gpu"] == jobs["gpu"]
    assert saved["hypothesis"] == result["hypothesis"]

    assert len(saved["history"]) == 1
    assert saved["history"][0]["stage"] == "all"
    assert saved["history"][0]["commands"] == result["commands"]

    # The shared pipeline should have recorded all three submissions.
    assert saved == result


def test_submit_gpu_uses_recorded_dependency_when_outputs_missing(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    write_bayeseor_submit_fixture(run_dir)
    write_jobs_json(
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

    assert jobs["gpu"]["dependency"] == "afterok:12345"
    assert jobs["gpu"]["dependency_source"] == "jobs_json"
    assert "--dependency=afterok:12345" in result["commands"][0]
    assert "--dependency=afterok:12345" in result["commands"][1]


def test_submit_gpu_skips_dependency_when_cpu_outputs_verified(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    write_bayeseor_submit_fixture(run_dir)
    matrix_dir = write_bayeseor_completed_cpu_outputs(run_dir)
    write_jobs_json(
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

    assert jobs["gpu"]["dependency"] is None
    assert (
        jobs["gpu"]["dependency_source"] == "cpu_precompute_outputs_verified"
    )
    assert jobs["gpu"]["cpu_precompute_matrix_dir"] == str(matrix_dir)
    assert "--dependency=" not in result["commands"][0]
    assert "--dependency=" not in result["commands"][1]


def test_submit_gpu_requires_dependency_or_completed_outputs(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    write_bayeseor_submit_fixture(run_dir)

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
    write_bayeseor_submit_fixture(run_dir)
    write_bayeseor_completed_cpu_outputs(run_dir)
    write_jobs_json(run_dir, {"jobs": {}})

    code = cli_submit.main([str(run_dir), "--stage", "gpu", "--dry-run"])

    assert code == 0


@pytest.mark.parametrize(
    "hypothesis",
    ["both", "signal_fit", "no_signal"],
)
def test_submit_records_hypothesis(tmp_path, hypothesis, monkeypatch):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    write_bayeseor_submit_fixture(run_dir)
    write_bayeseor_completed_cpu_outputs(run_dir)

    _ = mock_sbatch(monkeypatch, "bayeseor")

    result = submit_tool_run(
        run_dir,
        stage_id="gpu",
        submit_plan=BayesEoRSubmitPlan,
        options=BayesEoRRunOptions(
            hypothesis=hypothesis,
            sbatch_exe="fake-sbatch",
        ),
    )

    # Check the explicitly supplied option reaches the result.
    assert result["hypothesis"] == hypothesis

    # Check it is also present in the persisted jobs record.
    saved = json.loads((run_dir / "jobs.json").read_text(encoding="utf-8"))
    assert saved["hypothesis"] == hypothesis


def test_submit_gpu_uses_cpu_job_from_previous_invocation(
    tmp_path,
    monkeypatch,
):
    """Ensures separate invocations preserve CPU records, resolve dependencies,
    and append history."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    write_bayeseor_submit_fixture(run_dir)

    submissions = mock_sbatch(monkeypatch, "bayeseor")

    # First invocation: CPU only.
    cpu_result = submit_tool_run(
        run_dir,
        stage_id="cpu",
        submit_plan=BayesEoRSubmitPlan,
        options=BayesEoRRunOptions(
            hypothesis="both",
            sbatch_exe="fake-sbatch",
        ),
    )

    assert cpu_result["jobs"]["cpu_precompute"]["job_id"] == "10101"
    assert len(submissions) == 1

    # Second invocation: GPU only, using the persisted CPU job ID.
    gpu_result = submit_tool_run(
        run_dir,
        stage_id="gpu",
        submit_plan=BayesEoRSubmitPlan,
        options=BayesEoRRunOptions(
            hypothesis="both",
            sbatch_exe="fake-sbatch",
        ),
    )

    assert len(submissions) == 3
    assert [s["dependency_afterok"] for s in submissions] == [
        None,
        "10101",
        "10101",
    ]

    jobs = gpu_result["jobs"]
    assert jobs["cpu_precompute"]["job_id"] == "10101"
    assert jobs["gpu"]["dependency"] == "afterok:10101"
    assert jobs["gpu"]["dependency_source"] == "jobs_json"
    assert jobs["gpu"]["signal_fit"]["job_id"] == "20202"
    assert jobs["gpu"]["no_signal"]["job_id"] == "30303"

    saved = json.loads((run_dir / "jobs.json").read_text(encoding="utf-8"))
    assert saved["jobs"] == jobs
    assert len(saved["history"]) == 2
    assert saved["history"][0]["stage"] == "cpu"
    assert saved["history"][1]["stage"] == "gpu"


def test_bayeseor_run_options_defaults():
    """Quick test to check defaults are passed as expected"""

    options = BayesEoRRunOptions()

    assert options.hypothesis == "both"
    assert options.sbatch_exe == "sbatch"
    assert options.dry_run is False
    assert options.force is False
    assert options.record == "jobs.json"

    assert options.output_fields == {
        "sbatch_exe": "sbatch",
        "dry_run": "dry_run",
        "hypothesis": "hypothesis",
    }
