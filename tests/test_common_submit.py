import json

import pytest

from tests.utils import (
    mock_sbatch,
    write_bayeseor_submit_fixture,
    write_pyuvsim_submit_fixture,
)
from valska.external_tools.bayeseor.submit import (
    BayesEoRRunOptions,
    BayesEoRSubmitPlan,
)
from valska.external_tools.common.submit import (
    InvalidArgumentError,
    submit_tool_run,
)

# Define write submit scripts for each tool under test
_WRITE_FIXTURE = {
    "bayeseor": write_bayeseor_submit_fixture,
    "pyuvsim": write_pyuvsim_submit_fixture,
}


def write_submit_fixture(tool_name, run_dir):
    _WRITE_FIXTURE[tool_name](run_dir)


@pytest.mark.parametrize(
    "tool_name, submit_plan, options_cls, stage_id",
    [
        ("bayeseor", BayesEoRSubmitPlan, BayesEoRRunOptions, "cpu"),
        # (PyuvSimSubmitPlan, PyuvSimRunOptions, 1),
    ],
)
def test_dry_run_does_not_write_jobs_file(
    tmp_path, tool_name, submit_plan, options_cls, stage_id
):
    """Dry-run returns result but does not persist jobs.json."""

    run_dir = tmp_path
    (run_dir / "manifest.json").write_text("{}")
    write_submit_fixture(tool_name, run_dir)

    result = submit_tool_run(
        run_dir,
        stage_id=stage_id,
        submit_plan=submit_plan,
        options=options_cls(dry_run=True),
    )

    assert not (run_dir / "jobs.json").exists()

    assert result["dry_run"] is True
    assert "jobs" in result
    assert result["jobs"]

    for record in result["jobs"].values():
        if isinstance(record, dict) and "job_id" in record:
            assert record["job_id"] is None


@pytest.mark.parametrize(
    "tool_name, submit_plan, options_cls, n_jobs",
    [
        ("bayeseor", BayesEoRSubmitPlan, BayesEoRRunOptions, 3),
        # (PyuvSimSubmitPlan, PyuvSimRunOptions, 1),
    ],
)
def test_submit_all_refuses_duplicate_submission(
    tmp_path,
    monkeypatch,
    tool_name,
    submit_plan,
    options_cls,
    n_jobs,
):
    """Ensures the persisted records protect against accidental resubmission."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    write_submit_fixture(tool_name, run_dir)

    submissions = mock_sbatch(monkeypatch, tool_name)

    submit_tool_run(
        run_dir,
        stage_id="all",
        submit_plan=submit_plan,
        options=options_cls(sbatch_exe="fake-sbatch"),
    )

    assert len(submissions) == n_jobs

    jobs_path = run_dir / "jobs.json"
    before = json.loads(jobs_path.read_text(encoding="utf-8"))

    with pytest.raises(
        InvalidArgumentError,
        match="already recorded in jobs.json",
    ):
        submit_tool_run(
            run_dir,
            stage_id="all",
            submit_plan=submit_plan,
            options=options_cls(sbatch_exe="fake-sbatch"),
        )

    # No further external submissions occurred.
    assert len(submissions) == n_jobs

    # The rejected invocation must not change the persisted record.
    after = json.loads(jobs_path.read_text(encoding="utf-8"))
    assert after == before


@pytest.mark.parametrize(
    "tool_name, submit_plan, options_cls, tool_options",
    [
        (
            "bayeseor",
            BayesEoRSubmitPlan,
            BayesEoRRunOptions,
            {"hypothesis": "signal_fit"},
        ),
        # ("pyuvsim", PyuvSimSubmitPlan, PyuvSimRunOptions, {}),
    ],
)
def test_submit_records_common_and_tool_specific_options(
    tmp_path, tool_name, submit_plan, options_cls, tool_options
):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    write_submit_fixture(tool_name, run_dir)

    options = options_cls(
        sbatch_exe="fake-sbatch",
        dry_run=True,
        **tool_options,
    )

    result = submit_tool_run(
        run_dir,
        stage_id="all",
        submit_plan=submit_plan,
        options=options,
    )

    assert "jobs" in result
    assert isinstance(result["jobs"], dict)
    assert len(result["jobs"]) > 0
    assert result["stage"] == "all"
    assert result["sbatch"] == "fake-sbatch"
    assert result["dry_run"] is True
    for key, value in tool_options.items():
        assert result[key] == value


@pytest.mark.parametrize(
    "tool_name, submit_plan, options_cls, stage_ids, num_jobs",
    [
        (
            "bayeseor",
            BayesEoRSubmitPlan,
            BayesEoRRunOptions,
            ["cpu", "gpu"],
            [1, 1],
        ),
        # (PyuvSimSubmitPlan, PyuvSimRunOptions, 1),
    ],
)
def test_history_entries_do_not_accumulate_previous_jobs(
    tmp_path,
    monkeypatch,
    tool_name,
    submit_plan,
    options_cls,
    stage_ids,
    num_jobs,
):
    """
    Tests that the history keeps separate invocations separately and does not
    accumulate all previous invocations each time
    """
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    write_submit_fixture(tool_name, run_dir)

    _ = mock_sbatch(monkeypatch, tool_name)

    # Invoke the tool for each stage in stage_ids
    for stage in stage_ids:
        submit_tool_run(
            run_dir,
            stage_id=stage,
            submit_plan=submit_plan,
            options=options_cls(
                sbatch_exe="fake-sbatch",
            ),
        )

    saved = json.loads((run_dir / "jobs.json").read_text())

    assert "history" in saved
    assert len(saved["history"]) == len(stage_ids)

    assert all("jobs" in entry for entry in saved["history"])

    for i, stage in enumerate(stage_ids):
        assert saved["history"][i]["stage"] == stage
        assert len(saved["history"][i]["jobs"]) == num_jobs[i]


@pytest.mark.parametrize(
    "tool_name, submit_plan, options_cls",
    [
        (
            "bayeseor",
            BayesEoRSubmitPlan,
            BayesEoRRunOptions,
        ),
        # ("pyuvsim", PyuvSimSubmitPlan, PyuvSimRunOptions),
    ],
)
def test_force_allows_resubmission_and_appends_history(
    tmp_path,
    monkeypatch,
    tool_name,
    submit_plan,
    options_cls,
):
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    write_submit_fixture(tool_name, run_dir)

    submissions = mock_sbatch(monkeypatch, tool_name)

    first = submit_tool_run(
        run_dir,
        stage_id="cpu",
        submit_plan=submit_plan,
        options=options_cls(
            sbatch_exe="fake-sbatch",
        ),
    )

    second = submit_tool_run(
        run_dir,
        stage_id="cpu",
        submit_plan=submit_plan,
        options=options_cls(
            sbatch_exe="fake-sbatch",
            force=True,
        ),
    )

    saved = json.loads((run_dir / "jobs.json").read_text(encoding="utf-8"))

    assert len(saved["history"]) == 2

    assert saved["history"][0]["commands"] == first["commands"]
    assert saved["history"][1]["commands"] == second["commands"]

    assert saved["jobs"] == second["jobs"]

    assert len(submissions) > 0


@pytest.mark.parametrize(
    "tool_name, submit_plan, options_cls",
    [
        (
            "bayeseor",
            BayesEoRSubmitPlan,
            BayesEoRRunOptions,
        ),
        # ("pyuvsim", PyuvSimSubmitPlan, PyuvSimRunOptions),
    ],
)
def test_submit_invalid_stage_raises(
    tmp_path,
    tool_name,
    submit_plan,
    options_cls,
):
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    write_submit_fixture(tool_name, run_dir)

    with pytest.raises(InvalidArgumentError):
        submit_tool_run(
            run_dir,
            stage_id="not_a_stage",
            submit_plan=submit_plan,
            options=options_cls(),
        )


@pytest.mark.parametrize(
    "tool_name, submit_plan, options_cls",
    [
        (
            "bayeseor",
            BayesEoRSubmitPlan,
            BayesEoRRunOptions,
        ),
        # ("pyuvsim", PyuvSimSubmitPlan, PyuvSimRunOptions),
    ],
)
def test_manifest_record_name_is_rejected(
    tmp_path,
    tool_name,
    submit_plan,
    options_cls,
):
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    write_submit_fixture(tool_name, run_dir)

    with pytest.raises(InvalidArgumentError):
        submit_tool_run(
            run_dir,
            stage_id="all",
            submit_plan=submit_plan,
            options=options_cls(
                record="manifest",
            ),
        )
