"""Compatibility wrapper."""

from valska.external_tools.common.slurm import (
    render_array_submit_script,
    render_submit_script,
)

__all__ = [
    "render_array_submit_script",
    "render_submit_script",
]
