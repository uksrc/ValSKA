"""Extends the common external tool ToolInstall for BayesEoR. Runners are unchanged so can be imported from the common runner module."""

from dataclasses import dataclass
from pathlib import Path

from valska.external_tools.common.runner import ToolInstall


@dataclass(frozen=True)
class BayesEoRInstall(ToolInstall):
    """
    Where BayesEoR lives and which script to invoke.

    Notes:
    - For now we assume a BayesEoR clone exists (HPC-friendly).
    - Later, if BayesEoR provides a stable module/entrypoint, we can support that too.
    """

    run_script: Path = Path("scripts/run-analysis.py")
