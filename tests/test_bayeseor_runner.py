from pathlib import Path

import pytest

from valska.external_tools.bayeseor.runner import BayesEoRInstall


def test_bayeseor_install_accepts_repo_path():
    """Test that BayesEoRInstall is backwards compatible"""

    with pytest.warns(
        DeprecationWarning,
        match="'repo_path' is deprecated; use 'install_path' instead.",
    ):
        install = BayesEoRInstall(repo_path=Path("/tmp/bayeseor"))

    assert install.install_path == Path("/tmp/bayeseor")
    assert install.repo_path == Path("/tmp/bayeseor")


def test_bayeseor_install_repo_path_alias():
    """Test that BayesEoRInstall is backwards compatible"""
    install = BayesEoRInstall(install_path=Path("/tmp/bayeseor"))

    assert install.repo_path == Path("/tmp/bayeseor")


def test_conda_runner_still_importable_from_bayeseor_runner():
    from valska.external_tools.bayeseor.runner import CondaRunner

    assert CondaRunner is not None


def test_container_runner_still_importable_from_bayeseor_runner():
    from valska.external_tools.bayeseor.runner import ContainerRunner

    assert ContainerRunner is not None
