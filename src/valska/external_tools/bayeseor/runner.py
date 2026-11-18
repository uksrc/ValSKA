"""Extends the common external tool ToolInstall for BayesEoR. Runners are unchanged so can be imported from the common runner module."""

from dataclasses import dataclass
from pathlib import Path
from warnings import warn

from valska.external_tools.common.runner import (
    CondaRunner as CondaRunner,
)
from valska.external_tools.common.runner import (
    ContainerRunner as ContainerRunner,
)
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

    # Backward compatibility to allow repo_path instead of install_path
    def __init__(
        self,
        install_path: Path | None = None,
        repo_path: Path | None = None,
        run_script: Path = Path("scripts/run-analysis.py"),
    ):

        if repo_path is not None:
            warn(
                "'repo_path' is deprecated; use 'install_path' instead.",
                DeprecationWarning,
                stacklevel=2,
            )

        if install_path is None:
            install_path = repo_path

        if install_path is None:
            raise TypeError(
                "Either install_path or repo_path must be supplied"
            )

        object.__setattr__(self, "install_path", Path(install_path))
        object.__setattr__(self, "run_script", run_script)
