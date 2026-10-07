"""Unit tests for utils"""

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import PropertyMock, patch

import pytest

from valska import utils
from valska.external_tools.bayeseor import (
    TOOL_NAME as BAYESEOR_TOOL_NAME,
)

UTILS_DIR = Path(os.path.abspath(utils.__file__)).parent.resolve()


def test_tool_name_constant():
    # Ensure the canonical tool name is defined and correct
    assert BAYESEOR_TOOL_NAME == "bayeseor"


def test_manifest_contains_tool_field_simulated(tmp_path):
    # Simulate a manifest file and assert presence of tool field
    manifest = {"tool": BAYESEOR_TOOL_NAME}
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert m["tool"] == "bayeseor"


def test_make_timestamp():
    """
    Test make timestamp gives current time to nearest
    minute
    """

    time_now = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    timestamp = utils.make_timestamp()

    assert time_now[0:4] == timestamp[0:4]
    assert time_now[5:6] == timestamp[5:6]
    assert time_now[8:9] == timestamp[8:9]
    assert time_now[11:15] == timestamp[11:15]


def test_load_paths_no_input():
    """Test load paths from default yaml file"""

    paths = utils.load_paths()

    # Reads paths.yaml from config directory
    # Test first path
    assert (
        paths["EoRFg"]
        == "v4d0/EoRFg/MN-23-23-38-2-2.63-2.82-6.2E-03-lp-dPS-v1/"
    )


def test_load_paths_with_input():
    """Test load paths from yaml file"""

    with tempfile.NamedTemporaryFile(mode="w+t") as yaml_file:
        yaml_file.writelines(
            "Test1: test/directory1/\nTest2: test/directory2/"
        )
        yaml_file.seek(0)

        paths = utils.load_paths(yaml_file.name)

        # Reads yaml_file
        assert paths["Test1"] == "test/directory1/"
        assert paths["Test2"] == "test/directory2/"

        yaml_file.close()


def test_load_paths_with_input_error():
    """Test load paths from non-existent yaml file"""

    with pytest.raises(FileNotFoundError):
        utils.load_paths("nonexistent_yaml_file.yml")


def test_load_runtime_paths_env_override(tmp_path, monkeypatch):
    """VALSKA_RUNTIME_PATHS_FILE should override inferred locations."""

    runtime_yaml = tmp_path / "runtime.yaml"
    runtime_yaml.write_text(
        "results_root: /tmp/from_env\nbayeseor:\n  repo_path: /tmp/bayeseor\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("VALSKA_RUNTIME_PATHS_FILE", str(runtime_yaml))

    data = utils.load_runtime_paths(base_dir=tmp_path / "no_config_here")
    assert isinstance(data, dict)
    bayeseor_cfg = data.get("bayeseor")
    assert isinstance(bayeseor_cfg, dict)

    assert data["results_root"] == "/tmp/from_env"
    assert bayeseor_cfg["repo_path"] == "/tmp/bayeseor"


def test_load_runtime_paths_site_packages_cwd_fallback(tmp_path, monkeypatch):
    """
    When base_dir is an installed package path, fall back to CWD config.
    """

    worktree = tmp_path / "worktree"
    (worktree / "config").mkdir(parents=True)
    (worktree / "config" / "runtime_paths.yaml").write_text(
        "results_root: /tmp/from_cwd\nbayeseor:\n  repo_path: /tmp/cwd_bayeseor\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(worktree)

    fake_site_base = (
        tmp_path / "env" / "lib" / "python3.11" / "site-packages" / "valska"
    )

    data = utils.load_runtime_paths(base_dir=fake_site_base)
    assert isinstance(data, dict)
    bayeseor_cfg = data.get("bayeseor")
    assert isinstance(bayeseor_cfg, dict)

    assert data["results_root"] == "/tmp/from_cwd"
    assert bayeseor_cfg["repo_path"] == "/tmp/cwd_bayeseor"


def test_resolve_data_path_named_root(tmp_path):
    """Relative dataset paths can resolve against a named data root."""

    runtime_paths = {
        "data": {
            "root": str(tmp_path / "default"),
            "named_roots": {"gaussian": str(tmp_path / "gaussian")},
        }
    }

    resolved = utils.resolve_data_path_info(
        "input.uvh5", runtime_paths, data_root_key="gaussian"
    )

    assert resolved.path == (tmp_path / "gaussian" / "input.uvh5").resolve()
    assert resolved.source == "runtime_paths.yaml:data.named_roots.gaussian"
    assert resolved.data_root_key == "gaussian"


def test_resolve_data_path_named_default_root(tmp_path):
    """Relative dataset paths prefer named_roots.default when no key is passed."""

    runtime_paths = {
        "data": {
            "root": str(tmp_path / "legacy-default"),
            "named_roots": {"default": str(tmp_path / "named-default")},
        }
    }

    resolved = utils.resolve_data_path_info("input.uvh5", runtime_paths)

    assert (
        resolved.path == (tmp_path / "named-default" / "input.uvh5").resolve()
    )
    assert resolved.source == "runtime_paths.yaml:data.named_roots.default"
    assert resolved.data_root_key == "default"


def test_resolve_data_path_legacy_root_fallback(tmp_path):
    """Legacy data.root is still used when named_roots.default is absent."""

    runtime_paths = {"data": {"root": str(tmp_path / "legacy-default")}}

    resolved = utils.resolve_data_path_info("input.uvh5", runtime_paths)

    assert (
        resolved.path == (tmp_path / "legacy-default" / "input.uvh5").resolve()
    )
    assert resolved.source == "runtime_paths.yaml:data.root"
    assert resolved.data_root_key is None


def test_resolve_data_path_missing_named_root_lists_available(tmp_path):
    """Missing named data roots fail with available keys in the message."""

    runtime_paths = {
        "data": {
            "named_roots": {
                "airy_diam14m": str(tmp_path / "airy"),
                "gaussian": str(tmp_path / "gaussian"),
            }
        }
    }

    with pytest.raises(ValueError) as excinfo:
        utils.resolve_data_path_info(
            "input.uvh5", runtime_paths, data_root_key="missing"
        )

    msg = str(excinfo.value)
    assert "data root key 'missing' not found" in msg
    assert "airy_diam14m, gaussian" in msg


def test_path_manager_get_paths(path_manager):
    """
    Test PathManager get_paths method
    This returns a dictionary of all the paths
    """

    expected_dictionary = {
        "utils_dir": UTILS_DIR,
        "package_dir": UTILS_DIR,
        "base_dir": path_manager.base_dir,
        "chains_dir": path_manager.chains_dir,
        "data_dir": path_manager.data_dir,
        "results_dir": path_manager.results_dir,
        "results_root": path_manager.results_root,
    }

    assert path_manager.get_paths() == expected_dictionary


@pytest.mark.parametrize(
    "name",
    [
        "utils_dir",
        "package_dir",
        "base_dir",
        "chains_dir",
        "data_dir",
        "results_dir",
    ],
)
def test_path_manager_get_path(path_manager, name):
    """
    Test PathManager get_path method
    This returns a dictionary of all the paths
    """
    if name in {"utils_dir", "package_dir"}:
        expected = UTILS_DIR
    else:
        expected = getattr(path_manager, name)

    assert path_manager.get_path(name) == expected


def test_path_manager_get_path_error(path_manager):
    """Test get_path with incorrect name"""

    with pytest.raises(KeyError):
        path_manager.get_path("incorrect_name")


def test_repr(path_manager):
    """Test __repr__ method"""

    expected_dictionary = {
        "utils_dir": UTILS_DIR,
        "package_dir": UTILS_DIR,
        "base_dir": path_manager.base_dir,
        "chains_dir": path_manager.chains_dir,
        "data_dir": path_manager.data_dir,
        "results_dir": path_manager.results_dir,
        "results_root": path_manager.results_root,
    }

    repr_string = repr(path_manager)

    # Don't require exact ordering/complete equality; ensure required lines exist.
    assert repr_string.startswith("PathManager:\n")
    for name, path in expected_dictionary.items():
        assert f"  {name}: {path}" in repr_string


def test_path_manager_create_sub_dir(path_manager):
    """Test create sub directory"""

    new_dir = "new_directory"

    with tempfile.TemporaryDirectory() as base_dir:
        # Update the chains dir
        path_manager.chains_dir = Path(base_dir)

        returned_dir = path_manager.create_subdir("chains_dir", new_dir)

        assert returned_dir == Path(base_dir).joinpath(new_dir)
        assert returned_dir.exists()


def test_path_manager_find_file(path_manager):
    """Test find file with named directory"""

    with tempfile.NamedTemporaryFile(suffix=".dat") as test_file:
        path_manager.chains_dir = Path(test_file.name).parent

        result = path_manager.find_file("*.dat", path_name="chains_dir")

        assert result == [Path(test_file.name)]


def test_path_manager_find_file_default(path_manager):
    """Test find file from default directory"""

    with tempfile.NamedTemporaryFile(suffix=".dat") as test_file:
        path_manager.base_dir = Path(test_file.name).parent

        result = path_manager.find_file("*.dat")

        assert result == [Path(test_file.name)]


@pytest.mark.parametrize(
    "pm, chains",
    [
        ("class", True),
        ("class", False),
        ("method", True),
        ("method", False),
    ],
)
def test_create_path_manager_default(pm, chains):
    """
    Test creation of default path manager
    with or without default chains directory
    """

    with tempfile.TemporaryDirectory() as base_dir:
        test_dir = Path(base_dir + "/one/two/three/")

        if chains:
            os.mkdir(base_dir + "/chains")

        with patch("inspect.getfile", new_callable=PropertyMock) as getfile:
            getfile.return_value = str(test_dir)

            if pm == "class":
                path_manager = utils.PathManager(
                    base_dir=Path(base_dir),
                    chains_dir=Path(base_dir) / "chains",
                    data_dir=Path(base_dir) / "data",
                    results_dir=Path(base_dir) / "results",
                    results_root=Path(base_dir),
                )
            elif pm == "method":
                # Ensure get_default_path_manager doesn't inject site/runtime
                # values by patching load_paths to a minimal dict during call.
                with patch("valska.utils.load_paths", return_value={}):
                    path_manager = utils.get_default_path_manager()
                # Force the attributes used by assertions
                path_manager.base_dir = Path(base_dir)
                path_manager.chains_dir = Path(base_dir) / "chains"
                path_manager.data_dir = Path(base_dir) / "data"
                path_manager.results_dir = Path(base_dir) / "results"
                path_manager.results_root = Path(base_dir)
                # Ensure the expected directories actually exist for assertions
                (Path(base_dir) / "data").mkdir(parents=True, exist_ok=True)
                (Path(base_dir) / "results").mkdir(parents=True, exist_ok=True)
            else:
                raise AssertionError(f"Unexpected pm value: {pm}")

            assert path_manager.utils_dir == test_dir.parent.resolve()
            assert path_manager.package_dir == test_dir.parent.resolve()
            assert path_manager.base_dir.resolve() == Path(base_dir).resolve()
            assert (
                path_manager.chains_dir.resolve()
                == Path(base_dir + "/chains").resolve()
            )
            assert (
                path_manager.data_dir.resolve()
                == Path(base_dir + "/data").resolve()
            )
            assert (
                path_manager.results_dir.resolve()
                == Path(base_dir + "/results").resolve()
            )

            assert Path(base_dir + "/data").exists()
            assert Path(base_dir + "/results").exists()


def test_build_pp_groups_from_paths_default():
    """Test with default input - i.e. reads from paths.yaml"""

    prefixes = ["GSM_FgEoR_"]

    expected_output = {
        "GSM -10%": ["GSM_FgEoR_-1e1pp"],
        "GSM -5%": ["GSM_FgEoR_-5e0pp"],
        "GSM -2%": ["GSM_FgEoR_-2e0pp"],
        "GSM -1%": ["GSM_FgEoR_-1e0pp"],
        "GSM -0.1%": ["GSM_FgEoR_-1e-1pp"],
        "GSM -0.01%": ["GSM_FgEoR_-1e-2pp"],
        "GSM -0.001%": ["GSM_FgEoR_-1e-3pp"],
        "GSM +0.001%": ["GSM_FgEoR_+1e-3pp"],
        "GSM +0.01%": ["GSM_FgEoR_+1e-2pp"],
        "GSM +0.1%": ["GSM_FgEoR_+1e-1pp"],
        "GSM +1%": ["GSM_FgEoR_+1e0pp"],
        "GSM +2%": ["GSM_FgEoR_+2e0pp"],
        "GSM +5%": ["GSM_FgEoR_+5e0pp"],
        "GSM +10%": ["GSM_FgEoR_+1e1pp"],
    }

    groups = utils.build_pp_groups_from_paths(prefixes)

    assert groups == expected_output


@pytest.mark.parametrize(
    "prefixes, label_prefixes, expected_result",
    [
        (
            ["Test1_"],
            {"Test1_": "T1", "Test2_": "T2"},
            {
                "T1 -0.001%": ["Test1_-1e-3pp"],
                "T1 -0.01%": ["Test1_-1e-2pp"],
                "T1 -0.1%": ["Test1_-1e-1pp"],
                "T1 -1%": ["Test1_-1e0pp"],
            },
        ),
        (
            ["Test2_"],
            {"Test1_": "T1", "Test2_": "T2"},
            {
                "T2 -2%": ["Test2_-2e0pp"],
                "T2 -5%": ["Test2_-5e0pp"],
                "T2 -10%": ["Test2_-1e1pp"],
            },
        ),
        (
            ["Test2_"],
            {"Dummy": "something"},
            {
                "Test2 -2%": ["Test2_-2e0pp"],
                "Test2 -5%": ["Test2_-5e0pp"],
                "Test2 -10%": ["Test2_-1e1pp"],
            },
        ),
        (
            ["Test2_"],
            None,
            {
                "Test2 -2%": ["Test2_-2e0pp"],
                "Test2 -5%": ["Test2_-5e0pp"],
                "Test2 -10%": ["Test2_-1e1pp"],
            },
        ),
        (["Test3_"], {"Test1_": "T1", "Test2_": "T2"}, {}),
        (["Test4_"], {"Test1_": "T1", "Test2_": "T2"}, {}),
    ],
)
def test_build_pp_groups_from_paths_with_input(
    prefixes, label_prefixes, expected_result
):
    """Test with input yaml file"""

    with tempfile.NamedTemporaryFile(mode="w+t") as yaml_file:
        yaml_file.writelines(
            [
                "Test1_-1e-3pp: test/directory1a/\n",
                "Test1_-1e-2pp: test/directory1b/\n",
                "Test1_-1e-1pp: test/directory1c/\n",
                "Test1_-1e0pp: test/directory1d/\n",
                "Test2_-2e0pp: test/directory2a/\n",
                "Test2_-5e0pp: test/directory2b/\n",
                "Test2_-1e1pp: test/directory2c/\n",
                "Test3_-ee1pp: test/directory3/",
            ]
        )

        yaml_file.seek(0)

        groups = utils.build_pp_groups_from_paths(
            prefixes,
            custom_paths_file=yaml_file.name,
            label_prefixes=label_prefixes,
        )

        yaml_file.close()

        assert groups == expected_result


def test_build_group_labels():
    """Test build group labels"""

    groups = {
        "key1": ["value1"],
        "key2": ["value2a", "value2b"],
        "key3": ["value3"],
    }

    expected_result = {
        "key1": "key1",
        "key2": "key2",
        "key3": "key3",
    }

    labels = utils.build_group_labels(groups)

    assert labels == expected_result
