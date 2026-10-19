"""Runner abstractions for executing external tools via conda or containers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ToolInstall:
    """
    Stores where the external tool lives. Object that inherit
    may expand this to other installation properties.
    """

    install_path: Path


@dataclass(frozen=True)
class CondaRunner:
    """
    Run the tool via a named conda environment.

    conda_activate should point to conda.sh (or equivalent) so that
    `conda activate` works inside non-interactive batch shells (slurm).
    """

    conda_activate: (
        str  # e.g. "source /path/to/miniconda3/etc/profile.d/conda.sh"
    )
    env_name: str  # e.g. "bayeseor"

    @property
    def bash_prefix(self) -> str:
        """Return shell lines to activate the conda environment."""
        return f"{self.conda_activate}\nconda activate {self.env_name}\n"

    @property
    def python_exe(self) -> str:
        return "python"


@dataclass(frozen=True)
class ContainerRunner:
    """
    Future: Run the tool inside a container (Apptainer/Singularity).

    This is included now so we don’t need to redesign the API later.
    The only thing that should change is how we construct the command line;
    config rendering and output directory conventions stay identical.

    Example future command:
      apptainer exec --bind <binds> <image.sif> python <run-analysis.py> <config.yaml>
    """

    apptainer_exe: str  # "apptainer" or "singularity"
    image_path: Path
    bind_paths: tuple[Path, ...] = ()

    @property
    def bash_prefix(self) -> str:
        return ""

    @property
    def python_exe(self) -> str:
        return "python  # TODO: container exec wrapper"
