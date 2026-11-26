from pathlib import Path

from valska.external_tools.bayeseor.setup import (
    BayesEoRInstall,
    prepare_bayeseor_commands,
)
from valska.external_tools.common.runner import CondaRunner


def test_prepare_bayeseor_command():

    runner = CondaRunner(
        conda_activate="source /opt/conda/etc/profile.d/conda.sh",
        env_name="bayeseor",
    )
    config_yaml = Path("/tmp/config.yaml")
    mode = "cpu"
    command = prepare_bayeseor_commands(
        runner=runner,
        install=BayesEoRInstall(
            run_script=Path("test.sh"), install_path=Path("/bayeseor")
        ),
        config_yaml=config_yaml,
        mode=mode,
    )

    expected_cmd = (
        "python -u /bayeseor/test.sh --config /tmp/config.yaml --cpu"
    )

    assert command == expected_cmd


def test_prepare_bayeseor_array_command(runner):

    mode = "cpu"
    command = prepare_bayeseor_commands(
        runner=runner,
        install=BayesEoRInstall(
            run_script=Path("test.sh"), install_path=Path("/bayeseor")
        ),
        config_yaml="$CONFIG_YAML",
        mode=mode,
    )

    expected_cmd = 'python -u /bayeseor/test.sh --config "$CONFIG_YAML" --cpu'

    assert command == expected_cmd
