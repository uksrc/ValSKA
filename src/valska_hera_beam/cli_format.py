"""Compatibility wrapper for deprecated module `valska_hera_beam.cli_format`."""

from __future__ import annotations

from valska_hera_beam._compat import warn_import as _warn_import

_warn_import(__name__, "valska.cli_format")

from valska.cli_format import *  # noqa: F401,F403
