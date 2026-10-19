"""Utility functions for the ValSKA package.

This module provides:

- Path management via :class:`PathManager`
- Loading of analysis paths from ``config/paths.yaml``
- Loading of site/user runtime paths from ``config/runtime_paths.yaml``
- Compatibility wrappers for BayesEoR perturbation helpers

Notes on runtime_paths.yaml
---------------------------
`config/runtime_paths.yaml` is intended for *site/user-specific* settings, e.g.

- results_root (where all ValSKA outputs go)
- data.named_roots.default (preferred default root for input datasets)
- data.root (legacy default root for input datasets)
- BayesEoR repo_path / conda_sh / conda_env defaults
- Other external tool paths (pyuvsim, OSKAR) in future
"""

from __future__ import annotations

import inspect
import os
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

import yaml  # type: ignore[import-untyped]

PathLike = str | Path


# =============================================================================
# RUNTIME PATHS YAML (SITE/USER CONFIG)
# =============================================================================


class ResolvedDataPath(NamedTuple):
    """Resolved dataset path plus provenance for CLI output/manifests."""

    path: Path
    source: str
    data_root_key: str | None


def load_runtime_paths(
    base_dir: PathLike | None = None,
    runtime_paths_file: PathLike | None = None,
) -> dict[str, object]:
    """Load site/user runtime paths from ``config/runtime_paths.yaml`` if present.

    This configuration is intended for site/user-specific settings such as
    ``results_root``, ``data.named_roots``, and default external-tool paths.

    Parameters
    ----------
    base_dir
        Repository base directory. If None, inferred from this module location.
        Only used when runtime_paths_file is None.
    runtime_paths_file
        Explicit path to a runtime paths YAML.
        If None, resolution order is ``$VALSKA_RUNTIME_PATHS_FILE`` first,
        then ``<base_dir>/config/runtime_paths.yaml``, then
        ``$PWD/config/runtime_paths.yaml`` when ``<base_dir>`` appears to be an
        installed site-packages/dist-packages path.

    Returns
    -------
    dict
        Parsed YAML mapping. Returns an empty dict if the file does not exist.

    Raises
    ------
    ValueError
        If the YAML exists but does not contain a mapping at top level.
    """

    def _is_site_packages_path(path: Path) -> bool:
        parts = {part.lower() for part in path.parts}
        return "site-packages" in parts or "dist-packages" in parts

    if runtime_paths_file is not None:
        p = Path(runtime_paths_file).expanduser().resolve()
    else:
        env_runtime = os.environ.get("VALSKA_RUNTIME_PATHS_FILE")
        if env_runtime:
            p = Path(env_runtime).expanduser().resolve()
        else:
            if base_dir is None:
                # Infer repo root similarly to PathManager
                utils_dir = Path(
                    inspect.getfile(load_runtime_paths)
                ).parent.resolve()
                base_dir_path = utils_dir.parent.parent.resolve()
            else:
                base_dir_path = Path(base_dir).expanduser().resolve()

            p = (base_dir_path / "config" / "runtime_paths.yaml").resolve()

            # Installed package fallback:
            # if config was not bundled into site-packages, allow local repo
            # checkout configs when running CLI from that checkout.
            if not p.exists() and _is_site_packages_path(base_dir_path):
                cwd_candidate = (
                    Path.cwd() / "config" / "runtime_paths.yaml"
                ).resolve()
                if cwd_candidate.exists():
                    p = cwd_candidate

    if not p.exists():
        return {}

    with p.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    if not isinstance(data, dict):
        raise ValueError(f"Expected a mapping in runtime paths YAML: {p}")

    return data


def resolve_data_path(
    data_path: PathLike,
    runtime_paths: Mapping[str, object] | None = None,
    data_root_key: str | None = None,
) -> Path:
    """Resolve an input dataset path using runtime_paths.yaml defaults.

    Rules
    -----
    - If `data_path` is absolute: return it (expanded + resolved).
    - If `data_path` is relative and `data_root_key` is provided:
        return `<data.named_roots[data_root_key]>/<data_path>` (expanded + resolved).
    - If `data_path` is relative and runtime_paths contains `data.named_roots.default`:
        return `<data.named_roots.default>/<data_path>` (expanded + resolved).
    - If `data_path` is relative and runtime_paths contains legacy `data.root`:
        return `<data.root>/<data_path>` (expanded + resolved).
    - Otherwise: resolve relative to the current working directory.

    This keeps CLIs explicit (`--data` is still required) while reducing boilerplate
    and enabling site-specific mount points.

    Parameters
    ----------
    data_path
        Dataset path provided by a user/CLI.
    runtime_paths
        Parsed runtime paths mapping (typically from `load_runtime_paths()`).
    data_root_key
        Optional key in ``runtime_paths.yaml:data.named_roots`` to use for
        relative input paths.

    Returns
    -------
    Path
        Fully resolved absolute path.
    """
    return resolve_data_path_info(
        data_path, runtime_paths, data_root_key=data_root_key
    ).path


def resolve_data_path_info(
    data_path: PathLike,
    runtime_paths: Mapping[str, object] | None = None,
    data_root_key: str | None = None,
) -> ResolvedDataPath:
    """Resolve an input dataset path and report where it came from."""
    p = Path(data_path).expanduser()

    if p.is_absolute():
        return ResolvedDataPath(
            path=p.resolve(), source="CLI", data_root_key=None
        )

    rt = runtime_paths or {}
    data_cfg = rt.get("data") if isinstance(rt, Mapping) else None
    if isinstance(data_cfg, Mapping):
        key = (data_root_key or "").strip()
        named_roots = data_cfg.get("named_roots")
        if key or isinstance(named_roots, Mapping):
            roots = named_roots
            available = (
                sorted(str(k) for k in roots.keys())
                if isinstance(roots, Mapping)
                else []
            )
            selected_key = key or "default"
            if not isinstance(roots, Mapping) or selected_key not in roots:
                if key:
                    if available:
                        available_msg = ", ".join(available)
                    else:
                        available_msg = "(none configured)"
                    raise ValueError(
                        "ERROR: data root key "
                        f"'{key}' not found in "
                        "runtime_paths.yaml:data.named_roots. "
                        f"Available keys: {available_msg}"
                    )
            else:
                root = roots[selected_key]
                if not isinstance(root, str) or not root.strip():
                    raise ValueError(
                        "ERROR: runtime_paths.yaml:data.named_roots."
                        f"{selected_key} must be a non-empty path string."
                    )
                return ResolvedDataPath(
                    path=(Path(root).expanduser() / p).resolve(),
                    source=(
                        f"runtime_paths.yaml:data.named_roots.{selected_key}"
                    ),
                    data_root_key=selected_key,
                )

        root = data_cfg.get("root")
        if isinstance(root, str) and root.strip():
            return ResolvedDataPath(
                path=(Path(root).expanduser() / p).resolve(),
                source="runtime_paths.yaml:data.root",
                data_root_key=None,
            )

    return ResolvedDataPath(path=p.resolve(), source="CLI", data_root_key=None)


# =============================================================================
# PATH MANAGEMENT
# =============================================================================


def _default_results_root(base_dir: Path) -> Path:
    """
    Resolve a sensible default results_root for HPC and local use.

    Resolution order:
      1) runtime_paths.yaml (results_root key) [handled by PathManager]
      2) $VALSKA_RESULTS_ROOT
      3) $SCRATCH/UKSRC/ValSKA/results
      4) $HOME/UKSRC/ValSKA/results
      5) <base_dir>/results
    """
    env = os.environ.get("VALSKA_RESULTS_ROOT")
    if env:
        return Path(env).expanduser().resolve()

    scratch = os.environ.get("SCRATCH")
    if scratch:
        return (Path(scratch) / "UKSRC" / "ValSKA" / "results").resolve()

    home = os.environ.get("HOME")
    if home:
        return (Path(home) / "UKSRC" / "ValSKA" / "results").resolve()

    return (base_dir / "results").resolve()


class PathManager:
    """Manage paths for ValSKA workflows and generated outputs."""

    def __init__(
        self,
        base_dir: PathLike | None = None,
        chains_dir: PathLike | None = None,
        data_dir: PathLike | None = None,
        results_dir: PathLike | None = None,
        results_root: PathLike | None = None,
        runtime_paths_file: PathLike | None = None,
    ):
        """Initialize the PathManager with configurable directories.

        If directories are not specified, they will be automatically determined
        relative to the package location and common HPC conventions.

        Parameters
        ----------
        base_dir
            Base directory of the project. If None, it's determined automatically.
        chains_dir
                        Directory containing chain files. If None, falls back through
                        environment/config-aware defaults.
        data_dir
            Directory containing data files (input datasets). If None, attempts:
              - config/runtime_paths.yaml: data.named_roots.default
              - config/runtime_paths.yaml: data.root (legacy)
              - <base_dir>/data (created)
        results_dir
            Directory for ValSKA-produced results (tables/plots/summaries).
            If None, defaults to <results_root>/validation (created).
        results_root
            Root directory for all ValSKA-generated outputs, including external tool outputs.
                        If None, PathManager resolves this from runtime config, environment,
                        and then a repository-local default.
        runtime_paths_file
            Optional explicit path to a runtime paths YAML file.
            If None, uses ``<base_dir>/config/runtime_paths.yaml``.
        """
        # Directory containing this module
        self.utils_dir = Path(inspect.getfile(self.__class__)).parent.resolve()

        # Package dir (same as utils_dir for src layout)
        self.package_dir = self.utils_dir

        # Determine base directory (two levels up from utils_dir, i.e. repo root)
        if base_dir is None:
            self.base_dir = self.utils_dir.parent.parent.resolve()
        else:
            self.base_dir = Path(base_dir).expanduser().resolve()

        # Load runtime paths YAML (site/user config)
        self.runtime_paths: dict[str, object] = load_runtime_paths(
            base_dir=self.base_dir,
            runtime_paths_file=runtime_paths_file,
        )

        # Resolve results_root
        if results_root is None:
            cfg_rr = self.runtime_paths.get("results_root")
            if cfg_rr:
                self.results_root = Path(str(cfg_rr)).expanduser().resolve()
            else:
                self.results_root = _default_results_root(self.base_dir)
        else:
            self.results_root = Path(results_root).expanduser().resolve()
        self.results_root.mkdir(exist_ok=True, parents=True)

        # Set up data directory (input dataset root)
        #
        # Priority:
        #   1) explicit constructor arg data_dir
        #   2) runtime_paths.yaml: data.named_roots.default
        #   3) runtime_paths.yaml: data.root (legacy)
        #   4) <base_dir>/data (created)
        if data_dir is not None:
            self.data_dir = Path(data_dir).expanduser().resolve()
            # If the user explicitly asked for a data_dir, we can create it.
            self.data_dir.mkdir(exist_ok=True, parents=True)
        else:
            cfg_data_root = None
            cfg_data = self.runtime_paths.get("data")
            if isinstance(cfg_data, dict):
                cfg_named_roots = cfg_data.get("named_roots")
                if isinstance(cfg_named_roots, dict):
                    cfg_data_root = cfg_named_roots.get("default")
                if not cfg_data_root:
                    cfg_data_root = cfg_data.get("root")

            if isinstance(cfg_data_root, str) and cfg_data_root.strip():
                # For a configured data root, do not force creation (could be read-only / shared).
                self.data_dir = Path(cfg_data_root).expanduser().resolve()
            else:
                self.data_dir = (self.base_dir / "data").resolve()
                self.data_dir.mkdir(exist_ok=True, parents=True)

        # Set up results directory (ValSKA internal results, not external tool outputs)
        # Default to a subdir under results_root so everything stays together.
        if results_dir is None:
            self.results_dir = (self.results_root / "validation").resolve()
            self.results_dir.mkdir(exist_ok=True, parents=True)
        else:
            self.results_dir = Path(results_dir).expanduser().resolve()
            self.results_dir.mkdir(exist_ok=True, parents=True)

        # Set up chains directory
        if chains_dir is None:
            # 1) Explicit override for external-tool chain location
            env_chains = os.environ.get("BAYESEOR_CHAINS_DIR")
            if env_chains:
                self.chains_dir = Path(env_chains).expanduser().resolve()
            else:
                # 2) Prefer ValSKA-managed BayesEoR output tree if present
                candidate_bayeseor = (self.results_root / "bayeseor").resolve()
                if candidate_bayeseor.exists():
                    self.chains_dir = candidate_bayeseor
                else:
                    # 3) Repo-local chains (legacy)
                    candidate_chains_dir = (self.base_dir / "chains").resolve()
                    if candidate_chains_dir.exists():
                        self.chains_dir = candidate_chains_dir
                    else:
                        # 4) Last resort: base_dir/results
                        self.chains_dir = (self.base_dir / "results").resolve()
        else:
            self.chains_dir = Path(chains_dir).expanduser().resolve()

        # Do not mkdir chains_dir here: chains are often produced externally.

    def resolve_data_path(
        self, data_path: PathLike, data_root_key: str | None = None
    ) -> Path:
        """Resolve a dataset path using this PathManager's runtime_paths.

        See module-level `resolve_data_path()` for the rules.
        """
        return resolve_data_path(
            data_path, self.runtime_paths, data_root_key=data_root_key
        )

    def get_paths(self) -> dict[str, Path]:
        """Get a dictionary of all managed paths.

        Returns
        -------
        dict
            Dictionary mapping path names to :class:`pathlib.Path` objects.
        """
        return {
            "utils_dir": self.utils_dir,
            "package_dir": self.package_dir,
            "base_dir": self.base_dir,
            "results_root": self.results_root,
            "chains_dir": self.chains_dir,
            "data_dir": self.data_dir,
            "results_dir": self.results_dir,
        }

    def get_path(self, name: str) -> Path:
        """Get a specific path by name.

        Parameters
        ----------
        name
            Name of the path to retrieve.

        Returns
        -------
        Path
            Requested path.

        Raises
        ------
        KeyError
            If the requested path name doesn't exist.
        """
        paths = self.get_paths()
        if name not in paths:
            valid_keys = list(paths.keys())
            raise KeyError(
                f"Path '{name}' not found. Valid paths are: {valid_keys}"
            )
        return paths[name]

    def create_subdir(self, parent: str, name: str) -> Path:
        """Create and return a subdirectory in one of the managed directories.

        Parameters
        ----------
        parent
            Name of the parent directory (one of the managed paths).
        name
            Name of the subdirectory to create.

        Returns
        -------
        Path
            Path to the created subdirectory.

        Raises
        ------
        KeyError
            If the parent directory name is invalid.
        """
        parent_dir = self.get_path(parent)
        new_dir = parent_dir / name
        new_dir.mkdir(exist_ok=True, parents=True)
        return new_dir

    def find_file(
        self, pattern: str, path_name: str | None = None
    ) -> list[Path]:
        """Find files matching a pattern in a specified directory.

        Parameters
        ----------
        pattern
            Glob pattern to match files.
        path_name
            Name of the directory to search in. If None, searches in ``base_dir``.

        Returns
        -------
        list of Path
            List of paths to files matching the pattern.
        """
        if path_name is None:
            search_dir = self.base_dir
        else:
            search_dir = self.get_path(path_name)

        return list(search_dir.glob(pattern))

    def __repr__(self) -> str:
        """Return a string representation of the PathManager."""
        paths = self.get_paths()
        path_strs = [f"  {name}: {path}" for name, path in paths.items()]
        return "PathManager:\n" + "\n".join(path_strs)


def get_default_path_manager() -> PathManager:
    """Get a :class:`PathManager` instance with default settings."""
    return PathManager()


# =============================================================================
# CONFIG / PATHS YAML
# =============================================================================


def make_timestamp() -> str:
    """Create a timestamp string for naming files and directories.

    Returns
    -------
    str
        Current timestamp in format ``YYYY-MM-DD_HHMMSS``.
    """

    return datetime.now().strftime("%Y-%m-%d_%H%M%S")


def load_paths(custom_paths_file: PathLike | None = None) -> dict[str, str]:
    """Load analysis paths from a YAML configuration file.

    Parameters
    ----------
    custom_paths_file
        Custom paths file to load. If None, loads the default paths file.

    Returns
    -------
    dict
        Dictionary of analysis path keys to relative chain subdirectories.
    """
    if custom_paths_file is None:
        # Get the directory of this file
        this_dir = Path(__file__).parent.resolve()
        # paths_file = this_dir / "config" / "paths.yaml"
        paths_file = this_dir.parent.parent / "config" / "paths.yaml"
    else:
        paths_file = Path(custom_paths_file)

    if not paths_file.exists():
        raise FileNotFoundError(f"Paths file not found: {paths_file}")

    with open(paths_file, encoding="utf-8") as f:
        paths = yaml.safe_load(f)

    return paths


# =============================================================================
# BAYESEOR COMPATIBILITY HELPERS
# =============================================================================


def build_pp_groups_from_paths(
    prefixes: list[str],
    custom_paths_file: PathLike | None = None,
    label_prefixes: dict[str, str] | None = None,
) -> dict[str, list[str]]:
    """
    Build groups for perturbation runs from paths.yaml for one or more
    prefixes.

    Examples
    --------
    ``prefixes=['GSM_FgEoR_']`` -> GSM v5d0 EoR+Fg

    ``prefixes=['GL_FgEoR_']`` -> GSM+GLEAM v7d0 EoR+Fg

    ``prefixes=['GSM_FgEoR_', 'GL_FgEoR_']`` -> combined

    ``label_prefixes={'GSM_FgEoR_': 'GSM', 'GL_FgEoR_': 'GL'}``
    -> labels like 'GSM -1%', 'GL -1%' instead of both 'GSM ...'
    """
    from valska.external_tools.bayeseor.chain_utils import (
        build_pp_groups_from_paths as build_groups,
    )

    return build_groups(
        prefixes,
        custom_paths_file=custom_paths_file,
        label_prefixes=label_prefixes,
    )


def build_group_labels(groups: dict[str, list[str]]) -> dict[str, str]:
    """Build a simple group-label identity mapping."""
    from valska.external_tools.bayeseor.chain_utils import (
        build_group_labels as build_labels,
    )

    return build_labels(groups)


def filter_chain_pairs(
    pairs: Mapping[str, object],
    min_value: float = -0.1,
    max_value: float = 0.1,
) -> dict[str, object]:
    """Filter chain pairs by signed perturbation value in percentage points.

    Parameters
    ----------
    pairs
        Mapping from perturbation key (ending with ``'pp'``) to any value
        (e.g. :class:`ChainPair` objects).
    min_value
        Minimum allowed value (inclusive), in percentage points.
    max_value
        Maximum allowed value (inclusive), in percentage points.

    Returns
    -------
    dict
        Filtered mapping containing only keys with
        ``min_value <= value <= max_value``.

    Notes
    -----
    The numeric value is taken directly from the ``'<value>pp'`` suffix, e.g.
    ``'-1e0pp' -> -1.0``, ``'1.0e-01pp' -> 0.1``.
    """
    from valska.external_tools.bayeseor.chain_utils import (
        filter_chain_pairs as filter_pairs,
    )

    return filter_pairs(
        pairs,
        min_value=min_value,
        max_value=max_value,
    )


def filter_chain_pairs_absolute_range(
    pairs: Mapping[str, object],
    min_abs_value: float = 0.001,
    max_abs_value: float = 0.1,
) -> dict[str, object]:
    """Filter chain pairs by absolute perturbation value in percentage points.

    Parameters
    ----------
    pairs
        Mapping from perturbation key (ending with ``'pp'``) to any value
        (e.g. :class:`ChainPair` objects).
    min_abs_value
        Minimum allowed absolute value (inclusive), in percentage points.
    max_abs_value
        Maximum allowed absolute value (inclusive), in percentage points.

    Returns
    -------
    dict
        Filtered mapping containing only keys with
        ``min_abs_value <= |value| <= max_abs_value``.
    """
    from valska.external_tools.bayeseor.chain_utils import (
        filter_chain_pairs_absolute_range as filter_pairs,
    )

    return filter_pairs(
        pairs,
        min_abs_value=min_abs_value,
        max_abs_value=max_abs_value,
    )


# =============================================================================
# EXAMPLES (MANUAL)
# =============================================================================


if __name__ == "__main__":
    # Simple manual checks, similar in spirit to evidence.py examples.

    # PathManager example
    path_manager = get_default_path_manager()
    print(path_manager)

    # Example: resolve a relative dataset path via runtime_paths.yaml data.named_roots.default (if configured)
    try:
        example_rel = "example_dataset.uvh5"
        resolved = path_manager.resolve_data_path(example_rel)
        print(
            f"\nResolved data path:\n  input:    {example_rel}\n  resolved: {resolved}"
        )
    except Exception as exc:
        print(f"\nCould not resolve example data path: {exc}")

    # Example usage of load_paths
    try:
        paths = load_paths()
        print(f"\nLoaded {len(paths)} paths from config/paths.yaml")
    except FileNotFoundError as exc:
        print(f"\nCould not load paths.yaml: {exc}")
