"""Compatibility wrapper for deprecated module `valska_hera_beam.external_tools.bayeseor.plot_configs`."""

from __future__ import annotations

from valska_hera_beam._compat import warn_import as _warn_import

_warn_import(__name__, "valska.external_tools.bayeseor.plot_configs")

from valska.external_tools.bayeseor.plot_configs import *  # noqa: F401,F403
