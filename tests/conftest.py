from pathlib import Path

import pytest

from tests.test_pyuvsim_slurm import _render_script
from valska.external_tools.bayeseor.bayeseor_direct_plotting import (
    BeamAnalysisPlotter,
)
from valska.utils import PathManager

from .constants import EOR_PS, NOISE_RATIO


@pytest.fixture(scope="session")
def base_dir(tmp_path_factory):
    """Repository-local ephemeral base directory for tests."""
    return tmp_path_factory.mktemp("valska_tests")


@pytest.fixture(scope="session")
def chains_dir(base_dir: Path):
    d = base_dir / "chains"
    d.mkdir(exist_ok=True)
    return d


@pytest.fixture(scope="session")
def data_dir(base_dir: Path):
    d = base_dir / "data"
    d.mkdir(exist_ok=True)
    return d


@pytest.fixture(scope="session")
def results_dir(base_dir: Path):
    d = base_dir / "results"
    d.mkdir(exist_ok=True)
    return d


@pytest.fixture(scope="session")
def results_root(base_dir: Path):
    """Controlled results_root for tests to avoid picking up global/site config."""
    return base_dir


@pytest.fixture(scope="package", name="path_manager")
def path_manager_fixture(
    base_dir, chains_dir, data_dir, results_dir, results_root
):
    """
    PathManager constructed from pytest-managed temp dirs.
    """
    path_manager = PathManager(
        base_dir=base_dir,
        chains_dir=chains_dir,
        data_dir=data_dir,
        results_dir=results_dir,
        results_root=results_root,
    )

    yield path_manager


# Should we change this to session scope?
@pytest.fixture(scope="package", name="beam_analysis")
def beam_analysis_fixture(chains_dir):
    """
    BeamAnalysisPlotter using the ephemeral chains_dir fixture.
    """
    paths = {
        "Test1": "test/directory1/",
        "Test2": "test/directory2/",
        "Test3": "test/directory3/",
        "Test4": "test/directory4/",
    }

    beam_analysis_plotter = BeamAnalysisPlotter(
        base_chains_dir=chains_dir,
        paths=paths,
        eor_ps=EOR_PS,
        noise_ratio=NOISE_RATIO,
    )

    yield beam_analysis_plotter


# relevant for pyuvsim tests
@pytest.fixture(scope="session")
def simulate_script():
    return _render_script("simulate")
