"""Tests for BayesEoR perturbation-chain helpers."""

from unittest.mock import patch

from valska.external_tools.bayeseor.chain_utils import (
    build_group_labels,
    build_pp_groups_from_paths,
    filter_chain_pairs,
    filter_chain_pairs_absolute_range,
)


def test_build_pp_groups_orders_and_labels_perturbations() -> None:
    paths = {
        "GSM_FgEoR_1e-1pp": "positive",
        "GSM_FgEoR_-1e0pp": "negative",
        "GSM_FgEoR_0e0pp": "zero",
        "GSM_FgOnly_1e-1pp": "other-model",
        "GSM_FgEoR_invalidpp": "invalid",
    }

    with patch("valska.utils.load_paths", return_value=paths):
        groups = build_pp_groups_from_paths(
            ["GSM_FgEoR_"],
            label_prefixes={"GSM_FgEoR_": "GSM"},
        )

    assert groups == {
        "GSM -1%": ["GSM_FgEoR_-1e0pp"],
        "GSM 0%": ["GSM_FgEoR_0e0pp"],
        "GSM +0.1%": ["GSM_FgEoR_1e-1pp"],
    }


def test_build_group_labels_returns_identity_mapping() -> None:
    groups = {"GSM -1%": ["negative"], "GSM +1%": ["positive"]}

    assert build_group_labels(groups) == {
        "GSM -1%": "GSM -1%",
        "GSM +1%": "GSM +1%",
    }


def test_filter_chain_pairs_uses_signed_range() -> None:
    pairs = {
        "GSM_FgEoR_-1e0pp": "outside",
        "GSM_FgEoR_-1e-1pp": "lower",
        "GSM_FgEoR_0e0pp": "zero",
        "GSM_FgEoR_1e-1pp": "upper",
        "GSM_FgEoR_1e0pp": "outside",
        "unexpected": "ignored",
    }

    assert filter_chain_pairs(pairs) == {
        "GSM_FgEoR_-1e-1pp": "lower",
        "GSM_FgEoR_0e0pp": "zero",
        "GSM_FgEoR_1e-1pp": "upper",
    }


def test_filter_chain_pairs_uses_absolute_range() -> None:
    pairs = {
        "GSM_FgEoR_-1e0pp": "outside",
        "GSM_FgEoR_-1e-1pp": "negative",
        "GSM_FgEoR_0e0pp": "below",
        "GSM_FgEoR_1e-3pp": "lower",
        "GSM_FgEoR_1e-1pp": "upper",
        "unexpected": "ignored",
    }

    assert filter_chain_pairs_absolute_range(pairs) == {
        "GSM_FgEoR_-1e-1pp": "negative",
        "GSM_FgEoR_1e-3pp": "lower",
        "GSM_FgEoR_1e-1pp": "upper",
    }
