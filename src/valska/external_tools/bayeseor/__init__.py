"""
BayesEoR integration helpers.

Primary entry points:
- prepare_bayeseor_run: render a BayesEoR config + SLURM submit script into a ValSKA results dir.
- submit_bayeseor_run: submit a prepared BayesEoR run directory to SLURM.
- get_template_path: access shipped validation templates.
"""

from ..common.runner import CondaRunner, ContainerRunner, ToolInstall
from .chain_utils import (
    build_group_labels,
    build_pp_groups_from_paths,
    filter_chain_pairs,
    filter_chain_pairs_absolute_range,
)
from .constants import TOOL_NAME
from .report import generate_sweep_report
from .setup import prepare_bayeseor_run
from .sweep_health import inspect_sweep_health
from .templates import get_template_path, list_templates
from .valska_bayeseor_plotting import (
    BayesEoRPlotConfig,
    load_bayeseor_analysis_outputs,
    plot_bayeseor_power_spectra_and_posteriors,
)

__all__ = [
    "prepare_bayeseor_run",
    "generate_sweep_report",
    "inspect_sweep_health",
    "get_template_path",
    "list_templates",
    "ToolInstall",
    "CondaRunner",
    "ContainerRunner",
    "TOOL_NAME",
    "BayesEoRPlotConfig",
    "load_bayeseor_analysis_outputs",
    "plot_bayeseor_power_spectra_and_posteriors",
    "build_group_labels",
    "build_pp_groups_from_paths",
    "filter_chain_pairs",
    "filter_chain_pairs_absolute_range",
]
