"""Access bundled BayesEoR analysis plot configuration examples."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

_PACKAGE = "valska.external_tools.bayeseor.plot_configs"
_ACTIVE_CONFIG_NAME = "plot.yaml"
_REFERENCE_CONFIG_NAME = "default_analysis_plot.yaml"


def get_default_analysis_plot_config_path() -> Path:
    """Return the packaged reference analysis plot configuration path."""
    return Path(
        str(resources.files(_PACKAGE).joinpath(_REFERENCE_CONFIG_NAME))
    )


def resolve_analysis_plot_config_path(
    explicit_path: str | Path | None = None,
) -> Path | None:
    """Resolve the analysis plot config path used by report commands.

    Precedence is:

    1. Explicit ``--plot-config`` path.
    2. ``./plot.yaml`` in the current working directory.
    3. Packaged ``plot_configs/plot.yaml``.
    4. ``None``, which means use built-in dataclass defaults.
    """
    if explicit_path is not None:
        return Path(explicit_path).expanduser()

    cwd_candidate = Path(_ACTIVE_CONFIG_NAME)
    if cwd_candidate.exists():
        return cwd_candidate

    packaged = resources.files(_PACKAGE).joinpath(_ACTIVE_CONFIG_NAME)
    if packaged.is_file():
        return Path(str(packaged))

    return None


__all__ = [
    "get_default_analysis_plot_config_path",
    "resolve_analysis_plot_config_path",
]
