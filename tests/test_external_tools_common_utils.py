"""Tests for shared external-tool utility helpers."""

import json

import pytest

from valska.external_tools.common import utils


def test_archive_timestamped_renames_existing_file(
    tmp_path, monkeypatch
) -> None:
    source = tmp_path / "jobs.json"
    source.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(utils, "utc_now_compact", lambda: "20260916T120000Z")

    archived = utils.archive_timestamped(source)

    assert archived is not None
    assert archived == tmp_path / "jobs_20260916T120000Z.json"
    assert archived.read_text(encoding="utf-8") == "{}"
    assert not source.exists()


def test_archive_timestamped_returns_none_for_missing_file(tmp_path) -> None:
    assert utils.archive_timestamped(tmp_path / "missing.json") is None


@pytest.mark.parametrize(
    ("task_count", "max_parallel", "expected"),
    [(1, None, "0-0"), (11, None, "0-10"), (11, 2, "0-10%2")],
)
def test_array_spec(task_count, max_parallel, expected) -> None:
    assert utils.array_spec(task_count, max_parallel) == expected


@pytest.mark.parametrize(
    ("task_count", "max_parallel"), [(0, None), (-1, None), (2, 0), (2, -1)]
)
def test_array_spec_rejects_non_positive_values(
    task_count, max_parallel
) -> None:
    with pytest.raises(ValueError):
        utils.array_spec(task_count, max_parallel)


def test_json_object_round_trip(tmp_path) -> None:
    path = tmp_path / "record.json"
    payload = {"jobs": {"cpu": {"job_id": "42"}}}

    assert utils.write_json_object(path, payload) == path
    assert utils.load_json_object(path) == payload


def test_load_json_object_handles_missing_and_non_object_data(
    tmp_path,
) -> None:
    missing = tmp_path / "missing.json"
    sequence = tmp_path / "sequence.json"
    sequence.write_text(json.dumps([1, 2]), encoding="utf-8")

    assert utils.load_json_object(missing) is None
    assert utils.load_json_object(sequence) is None


@pytest.mark.parametrize("value", [42, "42", " 42 "])
def test_is_numeric_job_id_accepts_numeric_values(value) -> None:
    assert utils.is_numeric_job_id(value)


@pytest.mark.parametrize("value", [None, "", "job-x", "DRY_RUN_JOB_ID"])
def test_is_numeric_job_id_rejects_non_numeric_values(value) -> None:
    assert not utils.is_numeric_job_id(value)


def test_extract_numeric_job_id_reads_nested_record() -> None:
    record = {"jobs": {"cpu": {"job_id": " 42 "}}}

    assert (
        utils.extract_numeric_job_id(record, "jobs", "cpu", "job_id") == "42"
    )


@pytest.mark.parametrize(
    "record",
    [
        None,
        {},
        {"jobs": []},
        {"jobs": {"cpu": {}}},
        {"jobs": {"cpu": {"job_id": "dry-run"}}},
    ],
)
def test_extract_numeric_job_id_rejects_missing_or_non_numeric_values(
    record,
) -> None:
    assert (
        utils.extract_numeric_job_id(record, "jobs", "cpu", "job_id") is None
    )
