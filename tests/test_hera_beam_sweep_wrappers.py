"""Tests for the HERA beam case-study BayesEoR sweep wrappers.

The wrappers are run with ``VALSKA_BAYESEOR_SWEEP_CMD`` pointing at a stub
that records its argv, so no sweep is prepared and no job is submitted.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
WRAPPER_DIR = REPO_ROOT / "case_studies" / "hera_beam" / "bash_scripts"
COMMON_WRAPPER = WRAPPER_DIR / "valska-bayeseor-sweep-v3-common.sh"
CAMPAIGN_WRAPPERS = sorted(WRAPPER_DIR.glob("valska-bayeseor-sweep-*_v3.sh"))

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None, reason="bash is required"
)


def _run_wrapper(
    tmp_path: Path, wrapper: Path, *args: str
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """Run a wrapper against an argv-recording stub sweep command."""
    args_file = tmp_path / "sweep_args.bin"
    stub = tmp_path / "stub-sweep"
    stub.write_text(
        '#!/usr/bin/env bash\nprintf \'%s\\0\' "$@" > "$SWEEP_ARGS_FILE"\n',
        encoding="utf-8",
    )
    stub.chmod(0o755)

    env = {
        **os.environ,
        "VALSKA_BAYESEOR_SWEEP_CMD": str(stub),
        "SWEEP_ARGS_FILE": str(args_file),
        "MPLCONFIGDIR": str(tmp_path / "mpl"),
    }
    proc = subprocess.run(
        ["bash", str(wrapper), "--results-root", str(tmp_path), *args],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    argv: list[str] = []
    if args_file.exists():
        argv = args_file.read_bytes().decode("utf-8").split("\0")[:-1]
    return proc, argv


def _option_value(argv: list[str], option: str) -> str | None:
    if option not in argv:
        return None
    return argv[argv.index(option) + 1]


def test_campaign_wrappers_are_discovered() -> None:
    assert CAMPAIGN_WRAPPERS
    for wrapper in CAMPAIGN_WRAPPERS:
        assert COMMON_WRAPPER.name in wrapper.read_text(encoding="utf-8")


def test_common_wrapper_help_lists_walltime_options(tmp_path) -> None:
    proc, _ = _run_wrapper(tmp_path, CAMPAIGN_WRAPPERS[0], "--help")

    assert proc.returncode == 0, proc.stderr
    assert "--cpu-time TIME" in proc.stdout
    assert "--gpu-time TIME" in proc.stdout


@pytest.mark.parametrize("wrapper", CAMPAIGN_WRAPPERS, ids=lambda p: p.name)
def test_campaign_wrappers_forward_walltimes(tmp_path, wrapper) -> None:
    proc, argv = _run_wrapper(
        tmp_path,
        wrapper,
        "--cpu-time",
        "02:30:00",
        "--gpu-time",
        "1-00:00:00",
    )

    assert proc.returncode == 0, proc.stderr
    assert _option_value(argv, "--cpu-time") == "02:30:00"
    assert _option_value(argv, "--gpu-time") == "1-00:00:00"


@pytest.mark.parametrize("wrapper", CAMPAIGN_WRAPPERS, ids=lambda p: p.name)
def test_campaign_wrappers_omit_walltimes_by_default(
    tmp_path, wrapper
) -> None:
    proc, argv = _run_wrapper(tmp_path, wrapper)

    assert proc.returncode == 0, proc.stderr
    assert argv
    assert "--cpu-time" not in argv
    assert "--gpu-time" not in argv
    assert "CPU walltime:" not in proc.stdout
    assert "GPU walltime:" not in proc.stdout


@pytest.mark.parametrize(
    ("args", "expected_cpu", "expected_gpu"),
    [
        (("--cpu-time", "02:30:00"), "02:30:00", None),
        (("--gpu-time", "1-00:00:00"), None, "1-00:00:00"),
    ],
)
def test_common_wrapper_forwards_walltimes_independently(
    tmp_path, args, expected_cpu, expected_gpu
) -> None:
    proc, argv = _run_wrapper(tmp_path, CAMPAIGN_WRAPPERS[0], *args)

    assert proc.returncode == 0, proc.stderr
    assert _option_value(argv, "--cpu-time") == expected_cpu
    assert _option_value(argv, "--gpu-time") == expected_gpu


def test_common_wrapper_keeps_walltime_values_as_single_arguments(
    tmp_path,
) -> None:
    # Not valid walltimes: the whitespace and glob character detect any word
    # splitting or pathname expansion between the wrapper and the CLI.
    cpu_time = "02:30:00 *"
    gpu_time = "1-00:00:00 ?"
    (tmp_path / "glob-target").touch()

    proc, argv = _run_wrapper(
        tmp_path,
        CAMPAIGN_WRAPPERS[0],
        "--cpu-time",
        cpu_time,
        "--gpu-time",
        gpu_time,
    )

    assert proc.returncode == 0, proc.stderr
    assert _option_value(argv, "--cpu-time") == cpu_time
    assert _option_value(argv, "--gpu-time") == gpu_time
    assert argv.count("--cpu-time") == 1
    assert argv.count("--gpu-time") == 1
