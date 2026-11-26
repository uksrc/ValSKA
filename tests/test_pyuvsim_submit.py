import json
from pathlib import Path

import pytest

from tests.utils import write_pyuvsim_submit_fixture
from valska.external_tools.pyuvsim import submit_pyuvsim_run
from valska.external_tools.pyuvsim.submit import (
    InvalidArgumentError,
    _merge_jobs_record,
    build_submit_plan,
)


def _mock_sbatch(monkeypatch):
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
        "valska.external_tools.pyuvsim.submit._run_sbatch",
        fake_run_sbatch,
    )
    return submissions


def test_submit_pyuvsim_run_exists():
    """Test for backwards compatibility"""
    from valska.external_tools.pyuvsim import submit_pyuvsim_run

    assert callable(submit_pyuvsim_run)


def test_submit_all_preserves_stage_order_paths_and_jobs_json(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """
    Tests end-to-end behaviour: submission order, script paths,
    command arguments, job IDs and persisted records.
    """

    run_dir = tmp_path / "run"
    run_dir.mkdir()

    write_pyuvsim_submit_fixture(run_dir)
    run_dir = run_dir.resolve()

    submissions = _mock_sbatch(monkeypatch)

    result = submit_pyuvsim_run(
        run_dir,
        sbatch_exe="fake-sbatch",
        dry_run=False,
    )

    # 1. Submissions occurred in expected order

    assert [s["script"].name for s in submissions] == [
        "submit_simulate.sh",
        "submit_beamcheck.sh",
    ]

    assert [s["job_id"] for s in submissions] == [
        "10101",
        "20202",
    ]

    assert all(s["cwd"] == run_dir for s in submissions)
    assert all(s["sbatch_exe"] == "fake-sbatch" for s in submissions)
    assert all(s["dry_run"] is False for s in submissions)

    # 2. Returned commands preserve submission ordering

    assert len(result["commands"]) == 2

    assert "submit_simulate.sh" in result["commands"][0]
    assert "submit_beamcheck.sh" in result["commands"][1]

    # 3. Job metadata is preserved

    jobs = result["jobs"]

    assert "jobs" not in jobs
    assert set(jobs) == {"simulate", "beamcheck"}

    assert jobs["simulate"] == {
        "script": str(run_dir / "submit_simulate.sh"),
        "job_id": "10101",
    }

    assert jobs["beamcheck"] == {
        "script": str(run_dir / "submit_beamcheck.sh"),
        "job_id": "20202",
    }

    # 4. On-disk record matches returned record

    jobs_path = run_dir / "jobs.json"

    assert jobs_path.is_file()

    saved = json.loads(jobs_path.read_text(encoding="utf-8"))

    assert saved["jobs"]["simulate"] == jobs["simulate"]
    assert saved["jobs"]["beamcheck"] == jobs["beamcheck"]

    assert len(saved["history"]) == 1
    assert saved["history"][0]["stage"] == "all"
    assert saved["history"][0]["commands"] == result["commands"]

    assert saved == result


def test_submit_records_simulate_and_beamcheck_jobs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Beamcheck and simulate jobs are both recorded."""

    run_dir = tmp_path

    simulate = run_dir / "submit_simulate.sh"
    beamcheck = run_dir / "submit_beamcheck.sh"

    simulate.write_text("#!/bin/bash\n")
    beamcheck.write_text("#!/bin/bash\n")

    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "artefacts": {
                    "submit_sh_simulate": "submit_simulate.sh",
                    "submit_sh_beamcheck": "submit_beamcheck.sh",
                }
            }
        )
    )

    jobids = iter(["111", "222"])

    monkeypatch.setattr(
        "valska.external_tools.pyuvsim.submit._run_sbatch",
        lambda *args, **kwargs: (next(jobids), "sbatch script.sh"),
    )

    result = submit_pyuvsim_run(run_dir)

    assert result["jobs"]["simulate"]["job_id"] == "111"
    assert result["jobs"]["beamcheck"]["job_id"] == "222"

    assert len(result["commands"]) == 2


def test_submit_without_beamcheck_records_only_simulate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Beamcheck submission is skipped if no artefact exists."""

    run_dir = tmp_path

    (run_dir / "submit_simulate.sh").write_text("#!/bin/bash\n")

    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "artefacts": {
                    "submit_sh_simulate": "submit_simulate.sh",
                }
            }
        )
    )

    monkeypatch.setattr(
        "valska.external_tools.pyuvsim.submit._run_sbatch",
        lambda *args, **kwargs: ("123", "sbatch simulate.sh"),
    )

    result = submit_pyuvsim_run(run_dir)

    assert set(result["jobs"]) == {"simulate"}
    assert len(result["commands"]) == 1


def test_build_submit_plan_resolves_relative_paths(
    tmp_path: Path,
) -> None:
    """Artefact paths are resolved relative to run_dir."""

    run_dir = tmp_path

    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "artefacts": {
                    "submit_sh_simulate": "scripts/simulate.sh",
                    "submit_sh_beamcheck": "scripts/beamcheck.sh",
                }
            }
        )
    )

    plan = build_submit_plan(run_dir)

    assert (
        plan.simulate_script == (run_dir / "scripts" / "simulate.sh").resolve()
    )

    assert (
        plan.beamcheck_script
        == (run_dir / "scripts" / "beamcheck.sh").resolve()
    )


def test_build_submit_plan_allows_missing_beamcheck(
    tmp_path: Path,
) -> None:
    """Beamcheck artefact is optional."""

    run_dir = tmp_path

    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "artefacts": {
                    "submit_sh_simulate": "submit_simulate.sh",
                }
            }
        )
    )

    plan = build_submit_plan(run_dir)

    assert plan.beamcheck_script is None


def test_submit_all_without_beamcheck_submits_simulate_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """'all' should degrade cleanly to simulate when beamcheck is absent."""

    run_dir = tmp_path / "run"
    run_dir.mkdir()

    (run_dir / "submit_simulate.sh").write_text(
        "#!/bin/bash\n",
        encoding="utf-8",
    )

    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "artefacts": {
                    "submit_sh_simulate": "submit_simulate.sh",
                }
            }
        ),
        encoding="utf-8",
    )

    submissions = _mock_sbatch(monkeypatch)

    result = submit_pyuvsim_run(
        run_dir,
        sbatch_exe="fake-sbatch",
    )

    assert len(submissions) == 1

    assert submissions[0]["script"].name == "submit_simulate.sh"

    assert list(result["jobs"]) == ["simulate"]

    assert len(result["commands"]) == 1

    assert "submit_simulate.sh" in result["commands"][0]


################################################
#### These tests will be common after refactor


def test_submit_refuses_existing_simulate_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Existing simulate job prevents resubmission."""

    run_dir = tmp_path

    (run_dir / "jobs.json").write_text(
        json.dumps(
            {
                "jobs": {
                    "simulate": {
                        "job_id": "999",
                    }
                }
            }
        )
    )

    (run_dir / "submit_simulate.sh").write_text("#!/bin/bash\n")

    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "artefacts": {
                    "submit_sh_simulate": "submit_simulate.sh",
                }
            }
        )
    )

    with pytest.raises(
        InvalidArgumentError,
        match="already recorded",
    ):
        submit_pyuvsim_run(run_dir)


def test_submit_force_allows_resubmission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Force allows existing jobs to be overwritten."""

    run_dir = tmp_path

    (run_dir / "jobs.json").write_text(
        json.dumps({"jobs": {"simulate": {"job_id": "999"}}})
    )

    (run_dir / "submit_simulate.sh").write_text("#!/bin/bash\n")

    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "artefacts": {
                    "submit_sh_simulate": "submit_simulate.sh",
                }
            }
        )
    )

    monkeypatch.setattr(
        "valska.external_tools.pyuvsim.submit._run_sbatch",
        lambda *args, **kwargs: ("123", "sbatch simulate.sh"),
    )

    result = submit_pyuvsim_run(run_dir, force=True)

    assert result["jobs"]["simulate"]["job_id"] == "123"


def test_merge_jobs_appends_history() -> None:
    """New submissions are appended to history."""

    existing = {
        "history": [
            {"stage": "old"},
        ],
    }

    new = {
        "stage": "simulate",
        "jobs": {},
    }

    merged = _merge_jobs_record(existing, new)

    assert len(merged["history"]) == 2
    assert merged["history"][0]["stage"] == "old"
    assert merged["history"][1]["stage"] == "simulate"


def test_merge_jobs_updates_existing_job_records() -> None:
    """New jobs replace existing entries of the same name."""

    existing = {
        "jobs": {
            "simulate": {
                "job_id": "111",
            }
        }
    }

    new = {
        "jobs": {
            "simulate": {
                "job_id": "222",
            }
        }
    }

    merged = _merge_jobs_record(existing, new)

    assert merged["jobs"]["simulate"]["job_id"] == "222"


def test_submit_force_appends_history_without_overwriting(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Forced resubmission should append history entries."""

    run_dir = tmp_path / "run"
    run_dir.mkdir()

    write_pyuvsim_submit_fixture(run_dir)

    _mock_sbatch(monkeypatch)

    first = submit_pyuvsim_run(
        run_dir,
        sbatch_exe="fake-sbatch",
    )

    second = submit_pyuvsim_run(
        run_dir,
        sbatch_exe="fake-sbatch",
        force=True,
    )

    saved = json.loads((run_dir / "jobs.json").read_text(encoding="utf-8"))

    assert len(saved["history"]) == 2

    assert saved["history"][0]["commands"] == first["commands"]

    assert saved["history"][1]["commands"] == second["commands"]

    assert saved["jobs"] == second["jobs"]
