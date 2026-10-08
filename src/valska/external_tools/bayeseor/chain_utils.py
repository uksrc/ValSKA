"""Grouping and filtering helpers for BayesEoR perturbation chains."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

PathLike = str | Path
PairsMap = Mapping[str, object]

__all__ = [
    "build_group_labels",
    "build_pp_groups_from_paths",
    "filter_chain_pairs",
    "filter_chain_pairs_absolute_range",
]


def _pp_key_to_percent_label(
    key: str,
    prefix: str,
    label_prefix: str | None = None,
) -> str | None:
    """Convert a BayesEoR perturbation key into a percentage label."""
    if not key.startswith(prefix):
        return None

    middle = key[len(prefix) :]
    if not middle.endswith("pp"):
        return None

    try:
        percent = float(middle[:-2])
    except ValueError:
        return None

    label_mag = f"{percent:.3g}%"
    sign = "+" if percent > 0 else ""

    if label_prefix is None:
        label_prefix = prefix.split("_", 1)[0]

    return f"{label_prefix} {sign}{label_mag}"


def build_pp_groups_from_paths(
    prefixes: list[str],
    custom_paths_file: PathLike | None = None,
    label_prefixes: dict[str, str] | None = None,
) -> dict[str, list[str]]:
    """Build display groups for BayesEoR perturbation paths.

    Parameters
    ----------
    prefixes
        Analysis-key prefixes to include, such as ``"GSM_FgEoR_"``.
    custom_paths_file
        Optional paths YAML. The default ValSKA paths file is used when this
        is ``None``.
    label_prefixes
        Optional mapping from analysis-key prefix to display prefix.

    Returns
    -------
    dict
        Display labels mapped to sorted analysis keys, ordered by signed
        perturbation percentage.
    """
    from valska.utils import load_paths

    paths = load_paths(custom_paths_file)
    raw_groups: dict[str, list[str]] = {}

    for key in paths:
        for prefix in prefixes:
            if not key.startswith(prefix):
                continue

            label_prefix = (
                label_prefixes.get(prefix)
                if label_prefixes is not None
                else None
            )
            label = _pp_key_to_percent_label(
                key,
                prefix=prefix,
                label_prefix=label_prefix,
            )
            if label is not None:
                raw_groups.setdefault(label, []).append(key)

    def label_to_value(label: str) -> float:
        try:
            return float(label.rsplit(maxsplit=1)[-1].strip("%"))
        except ValueError:
            return 0.0

    return {
        label: sorted(raw_groups[label])
        for label in sorted(raw_groups, key=label_to_value)
    }


def build_group_labels(groups: dict[str, list[str]]) -> dict[str, str]:
    """Build an identity mapping for BayesEoR perturbation group labels."""
    return {label: label for label in groups}


def _parse_pp_key_to_float(key: str) -> float:
    """Parse the percentage-point value from a BayesEoR perturbation key."""
    if not key.endswith("pp"):
        raise ValueError(f"Key does not end with 'pp': {key}")

    token = key.rsplit("_", maxsplit=1)[-1]
    return float(token[:-2])


def filter_chain_pairs(
    pairs: PairsMap,
    min_value: float = -0.1,
    max_value: float = 0.1,
) -> dict[str, object]:
    """Filter chain pairs by signed perturbation percentage points."""
    filtered: dict[str, object] = {}
    for key, value in pairs.items():
        try:
            numeric_value = _parse_pp_key_to_float(key)
        except ValueError:
            continue

        if min_value <= numeric_value <= max_value:
            filtered[key] = value

    return filtered


def filter_chain_pairs_absolute_range(
    pairs: PairsMap,
    min_abs_value: float = 0.001,
    max_abs_value: float = 0.1,
) -> dict[str, object]:
    """Filter chain pairs by absolute perturbation percentage points."""
    filtered: dict[str, object] = {}
    for key, value in pairs.items():
        try:
            numeric_value = abs(_parse_pp_key_to_float(key))
        except ValueError:
            continue

        if min_abs_value <= numeric_value <= max_abs_value:
            filtered[key] = value

    return filtered
