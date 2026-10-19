"""Unit tests for evidence"""

import tempfile
from pathlib import Path

import pytest

from valska.external_tools.bayeseor import evidence

from .constants import mock_read_chains


@pytest.mark.parametrize(
    "log_bf, result",
    [
        (6, "Very strong evidence for model 1"),
        (5, "Strong evidence for model 1"),
        (4, "Strong evidence for model 1"),
        (3, "Moderate evidence for model 1"),
        (2, "Moderate evidence for model 1"),
        (1, "Weak/inconclusive evidence"),
        (0, "Weak/inconclusive evidence"),
        (-1, "Moderate evidence for model 2"),
        (-2, "Moderate evidence for model 2"),
        (-3, "Strong evidence for model 2"),
        (-4, "Strong evidence for model 2"),
        (-5, "Very strong evidence for model 2"),
        (-6, "Very strong evidence for model 2"),
    ],
)
def test_interpret_bayes_factor(log_bf, result):
    """Test interpret_bayes_factor"""

    assert evidence.interpret_bayes_factor(log_bf) == result


def test_calculate_bayes_factor(monkeypatch):
    """Test calculate bayes factor"""

    # Patch the anesthetic read_chains() method
    # The mock reads the logZ from a text file, which I create below
    monkeypatch.setattr(evidence, "read_chains", mock_read_chains)

    with tempfile.TemporaryDirectory() as chains_dir:
        with open(f"{chains_dir}/chains_1.txt", "a", encoding="utf-8") as file:
            file.write("20")
        with open(f"{chains_dir}/chains_2.txt", "a", encoding="utf-8") as file:
            file.write("10")

        result = evidence.calculate_bayes_factor(
            Path(f"{chains_dir}/chains_1.txt"),
            Path(f"{chains_dir}/chains_2.txt"),
            "Model 1",
            "Model 2",
            verbose=False,
        )

        expected_result = {
            "model_1": "Model 1",
            "model_2": "Model 2",
            "log_evidence_1": 20.0,
            "log_evidence_2": 10.0,
            "log_bayes_factor": 10.0,
            "interpretation": "Very strong evidence for model 1",
            "success": True,
            "error": None,
        }

        assert result == expected_result


def test_calculate_bayes_factor_error():
    """Test calculate bayes factor with error"""

    result = evidence.calculate_bayes_factor(
        Path("dummy/chains_1.txt"),
        Path("dummy/chains_2.txt"),
        "Model 1",
        "Model 2",
        verbose=False,
    )

    assert result["error"].split("Could not find any compatible chains:")[
        0
    ] == (
        "Error calculating Bayes factor:\n"
        "  model_1 path: dummy/chains_1.txt\n"
        "  model_2 path: dummy/chains_2.txt\n"
        "  exception: "
    )
    assert result["success"] is False


def test_find_single_mn_subdir():
    """Test find subdirectories under root"""

    with tempfile.TemporaryDirectory() as root:
        Path(f"{root}/subdir/").mkdir()
        # Should ignore files and only find subdirectories
        Path(f"{root}/dummy.txt").touch()

        subdirs = evidence._find_single_mn_subdir(Path(root))

        assert subdirs == Path(f"{root}/subdir/")


def test_find_single_mn_subdir_multiple_error():
    """Test find subdirectories under root with too many subdirs"""

    with tempfile.TemporaryDirectory() as root:
        Path(f"{root}/subdir/").mkdir()
        Path(f"{root}/subdir2/").mkdir()

        with pytest.raises(RuntimeError):
            evidence._find_single_mn_subdir(Path(root))


def test_find_single_mn_subdir_empty_error():
    """Test find subdirectories under root with no subdirs"""

    with tempfile.TemporaryDirectory() as root:
        with pytest.raises(RuntimeError):
            evidence._find_single_mn_subdir(Path(root))


def test_normalize_perturbation_key():
    """Test normalise key - function currently does nothing"""

    key = "+1e0pp"
    result = evidence._normalize_perturbation_key(key)

    assert result == key


def test_find_chain_pairs_error():
    """Test find chain pairs with incorrect base dir"""

    base_dir = "/dummy/base/dir"

    with pytest.raises(FileNotFoundError):
        evidence.find_chain_pairs(Path(base_dir))


@pytest.mark.parametrize(
    "fgeor_prefix, fgeor_suffix, fgonly_prefix, fgonly_suffix, expected_keys",
    [
        ("GL_FgEoR_", ["1.0e00pp"], "GL_FgOnly_", ["1.0e00pp"], ["1.0e00pp"]),
        ("dummy1", ["k1", "k2"], "dummy2", ["k1", "k2"], ["k1", "k2"]),
        ("dummy1", ["k1"], "dummy2", ["k1", "k2"], ["k1"]),
        ("dummy1", [], "dummy2", ["k1", "k2"], []),
        ("dummy1", ["k1", "k2"], "dummy2", [], []),
    ],
)
def test_find_chain_pairs(
    fgeor_prefix, fgeor_suffix, fgonly_prefix, fgonly_suffix, expected_keys
):
    """
    Test find chain pairs

    Checks that it finds the correct matches for FG_EOR and FG_ONLY
    from the supplied directory structure.
    """

    with tempfile.TemporaryDirectory() as base_dir:
        fgeor_paths = {}
        for suffix in fgeor_suffix:
            fgeor_paths[suffix] = Path(
                f"{base_dir}/{fgeor_prefix}_{suffix}/subdir"
            )
            fgeor_paths[suffix].mkdir(parents=True, exist_ok=True)

            # Check that files are correctly skipped by creating
            # the FG only pair but using filename not directory
            fgonly_filepath = Path(f"{base_dir}/{fgonly_prefix}_{suffix}.txt")
            fgonly_filepath.touch()

        fgonly_paths = {}
        for suffix in fgonly_suffix:
            fgonly_paths[suffix] = Path(
                f"{base_dir}/{fgonly_prefix}_{suffix}/subdir"
            )
            fgonly_paths[suffix].mkdir(parents=True, exist_ok=True)

        chain_pair_map = evidence.find_chain_pairs(
            Path(base_dir),
            fgeor_prefix,
            fgonly_prefix,
            debug=False,
        )

        for key in expected_keys:
            assert key in chain_pair_map
            assert chain_pair_map[key].perturbation == key
            assert chain_pair_map[key].fgeor_root == fgeor_paths[key]
            assert chain_pair_map[key].fgonly_root == fgonly_paths[key]

        if len(expected_keys) == 0:
            assert not chain_pair_map


@pytest.mark.parametrize(
    "log_evidence, interp",
    [
        (
            [10.0, 20.0, -10.0],
            ["Very strong evidence for model 2", True, "PASS", None],
        ),
        (
            [20.0, 10.0, 10.0],
            ["Very strong evidence for model 1", True, "FAIL", None],
        ),
        (
            [None, None, None],
            [
                "Analysis failed",
                False,
                "ERROR",
                "Error calculating Bayes factor",
            ],
        ),
    ],
)
def test_analyze_chain_pair(monkeypatch, log_evidence, interp):
    """
    Test analyse chain pair without plotting

    Not testing the print statements in the verbose option.
    """

    key = "k1"

    # Not including error in the bayes factor result
    # because I don't want to check the full traceback!
    expected_result = {
        "perturbation": key,
        "plot_success": True,
        "bayes_factor_result": {
            "model_1": f"FgEoR_{key}",
            "model_2": f"FgOnly_{key}",
            "log_evidence_1": log_evidence[0],
            "log_evidence_2": log_evidence[1],
            "log_bayes_factor": log_evidence[2],
            "interpretation": interp[0],
            "success": interp[1],
        },
        "validation": interp[2],
    }

    # Patch the anesthetic read_chains() method
    # The mock reads the logZ from a text file, which I create below
    monkeypatch.setattr(evidence, "read_chains", mock_read_chains)

    with tempfile.TemporaryDirectory() as base_dir:
        fgeor_path = Path(f"{base_dir}/dummy_prefix1_{key}/subdir")
        fgeor_path.mkdir(parents=True, exist_ok=True)

        fgonly_path = Path(f"{base_dir}/dummy_prefix2_{key}/subdir")
        fgonly_path.mkdir(parents=True, exist_ok=True)

        if log_evidence[0]:
            with open(f"{fgeor_path}/data-", "a", encoding="utf-8") as file:
                file.write(f"{log_evidence[0]}")

        if log_evidence[1]:
            with open(f"{fgonly_path}/data-", "a", encoding="utf-8") as file:
                file.write(f"{log_evidence[1]}")

        # create the chain pair to analyse
        chain_pair = evidence.ChainPair(
            perturbation=key,
            fgeor_root=fgeor_path,
            fgonly_root=fgonly_path,
        )

        result = evidence.analyze_chain_pair(
            chain_pair,
            create_plots=False,
        )

        # If there was an error, only check the first part
        # and omit the traceback!
        if result["bayes_factor_result"]["error"] is not None:
            assert (
                result["bayes_factor_result"]["error"].split(":")[0]
                == interp[3]
            )

        result["bayes_factor_result"].pop("error")

        assert result == expected_result


@pytest.mark.parametrize(
    "input_list, summary, successful",
    [
        (
            [
                {
                    "key": "k1",
                    "log_evidence": [10.0, 20.0, -10.0],
                    "interp": "Very strong evidence for model 2",
                    "success": True,
                    "validation": "PASS",
                    "error": None,
                },
                {
                    "key": "k2",
                    "log_evidence": [20.0, 10.0, 10.0],
                    "interp": "Very strong evidence for model 1",
                    "success": True,
                    "validation": "FAIL",
                    "error": None,
                },
                {
                    "key": "k3",
                    "log_evidence": [None, None, None],
                    "interp": "Analysis failed",
                    "success": False,
                    "validation": "ERROR",
                    "error": "Error calculating Bayes factor",
                },
            ],
            {"total": 3, "pass": 1, "fail": 1, "error": 1},
            [
                {
                    "perturbation": "k1",
                    "log_evidence_fgeor": 10.0,
                    "log_evidence_fgonly": 20.0,
                    "log_bayes_factor": -10.0,
                    "validation": "PASS",
                    "interpretation": "Very strong evidence for model 2",
                },
                {
                    "perturbation": "k2",
                    "log_evidence_fgeor": 20.0,
                    "log_evidence_fgonly": 10.0,
                    "log_bayes_factor": 10.0,
                    "validation": "FAIL",
                    "interpretation": "Very strong evidence for model 1",
                },
            ],
        ),
        (
            [
                {
                    "key": "k1",
                    "log_evidence": [1.0, 1.1, -0.10000000000000009],
                    "interp": "Weak/inconclusive evidence",
                    "success": True,
                    "validation": "PASS",
                    "error": None,
                },
                {
                    "key": "k2",
                    "log_evidence": [1.1, 1.0, 0.10000000000000009],
                    "interp": "Weak/inconclusive evidence",
                    "success": True,
                    "validation": "FAIL",
                    "error": None,
                },
            ],
            {"total": 2, "pass": 1, "fail": 1, "error": 0},
            [
                {
                    "perturbation": "k1",
                    "log_evidence_fgeor": 1.0,
                    "log_evidence_fgonly": 1.1,
                    "log_bayes_factor": -0.10000000000000009,
                    "validation": "PASS",
                    "interpretation": "Weak/inconclusive evidence",
                },
                {
                    "perturbation": "k2",
                    "log_evidence_fgeor": 1.1,
                    "log_evidence_fgonly": 1.0,
                    "log_bayes_factor": 0.10000000000000009,
                    "validation": "FAIL",
                    "interpretation": "Weak/inconclusive evidence",
                },
            ],
        ),
        (
            [
                {
                    "key": "k1",
                    "log_evidence": [None, None, None],
                    "interp": "Analysis failed",
                    "success": False,
                    "validation": "ERROR",
                    "error": "Error calculating Bayes factor",
                },
                {
                    "key": "k2",
                    "log_evidence": [None, None, None],
                    "interp": "Analysis failed",
                    "success": False,
                    "validation": "ERROR",
                    "error": "Error calculating Bayes factor",
                },
            ],
            {"total": 2, "pass": 0, "fail": 0, "error": 2},
            [],
        ),
    ],
)
def test_run_full_analysis(monkeypatch, input_list, summary, successful):
    """
    Test run complete analysis

    Not testing optional arguments or print statements
    """

    # Patch the anesthetic read_chains() method
    # The mock reads the logZ from a text file, which I create below
    monkeypatch.setattr(evidence, "read_chains", mock_read_chains)

    with tempfile.TemporaryDirectory() as base_dir:
        chain_pair_map = {}
        expected_results = []

        for inputs in input_list:
            expected_results.append(
                {
                    "perturbation": inputs["key"],
                    "plot_success": True,
                    "bayes_factor_result": {
                        "model_1": f"FgEoR_{inputs['key']}",
                        "model_2": f"FgOnly_{inputs['key']}",
                        "log_evidence_1": inputs["log_evidence"][0],
                        "log_evidence_2": inputs["log_evidence"][1],
                        "log_bayes_factor": inputs["log_evidence"][2],
                        "interpretation": inputs["interp"],
                        "success": inputs["success"],
                    },
                    "validation": inputs["validation"],
                }
            )

            fgeor_path = Path(
                f"{base_dir}/dummy_prefix1_{inputs['key']}/subdir"
            )
            fgeor_path.mkdir(parents=True, exist_ok=True)

            fgonly_path = Path(
                f"{base_dir}/dummy_prefix2_{inputs['key']}/subdir"
            )
            fgonly_path.mkdir(parents=True, exist_ok=True)

            if inputs["log_evidence"][0]:
                with open(
                    f"{fgeor_path}/data-", "a", encoding="utf-8"
                ) as file:
                    file.write(f"{inputs['log_evidence'][0]:.9f}")

            if inputs["log_evidence"][1]:
                with open(
                    f"{fgonly_path}/data-", "a", encoding="utf-8"
                ) as file:
                    file.write(f"{inputs['log_evidence'][1]:.9f}")

            assert fgonly_path.exists()

            # create the chain pair to analyse
            chain_pair = evidence.ChainPair(
                perturbation=inputs["key"],
                fgeor_root=fgeor_path,
                fgonly_root=fgonly_path,
            )

            chain_pair_map[inputs["key"]] = chain_pair

        expected_output = {
            "results": expected_results,
            "summary": summary,
            "successful_results": successful,
        }

        results = evidence.run_complete_bayeseor_analysis(
            chain_pair_map,
        )

        for result in results["results"]:
            result["bayes_factor_result"].pop("error")

        assert results == expected_output
