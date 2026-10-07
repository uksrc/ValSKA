"""Utility helpers shared by external-tool integrations."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    """Return the current UTC time in ISO 8601 format."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_now_compact() -> str:
    """Return a compact current UTC timestamp suitable for filenames."""
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def archive_timestamped(path: Path) -> Path | None:
    """Rename an existing file by appending a compact UTC timestamp."""
    if not path.exists():
        return None
    archived = path.with_name(f"{path.stem}_{utc_now_compact()}{path.suffix}")
    path.rename(archived)
    return archived


def load_json_object(path: Path) -> dict[str, Any] | None:
    """Load a JSON object, returning ``None`` for absent or non-object data."""
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def write_json_object(path: Path, payload: dict[str, Any]) -> Path:
    """Write a JSON object and return its path."""
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def array_spec(task_count: int, max_parallel: int | None = None) -> str:
    """Format a zero-based task-array range with an optional throttle."""
    if task_count <= 0:
        raise ValueError("task_count must be positive for array submission")
    if max_parallel is not None and max_parallel <= 0:
        raise ValueError("array throttle must be a positive integer")
    spec = f"0-{task_count - 1}"
    if max_parallel is not None:
        spec += f"%{max_parallel}"
    return spec


def is_numeric_job_id(value: Any) -> bool:
    """Return whether a value represents a non-empty numeric job ID."""
    return value is not None and str(value).strip().isdigit()


def extract_numeric_job_id(
    record: dict[str, Any] | None, *keys: str
) -> str | None:
    """Read a nested numeric job ID from a mapping."""
    value: Any = record
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return str(value).strip() if is_numeric_job_id(value) else None
