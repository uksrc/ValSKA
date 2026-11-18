"""Compatibility wrapper for deprecated module `valska_hera_beam.external_tools.bayeseor.slurm`."""

from __future__ import annotations

from valska_hera_beam._compat import warn_import as _warn_import

_warn_import(__name__, "valska.external_tools.bayeseor.slurm")

from valska.external_tools.bayeseor.slurm import *  # noqa: F401,F403
