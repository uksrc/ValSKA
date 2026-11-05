"""Test notebook_helpers"""

import numpy as np
import pytest

from valska.notebook_helpers import extract_vis, unpack_shape

# =========================
# unpack_shape
# =========================


def test_unpack_shape_4d_returns_shape_unchanged():
    arr = np.zeros((10, 2, 64, 4))

    assert unpack_shape(arr) == (10, 2, 64, 4)


def test_unpack_shape_3d_inserts_single_spw_dimension():
    arr = np.zeros((10, 64, 4))

    assert unpack_shape(arr) == (10, 1, 64, 4)


@pytest.mark.parametrize(
    "shape",
    [
        (10,),
        (10, 64),
        (10, 2, 64, 4, 1),
    ],
)
def test_unpack_shape_invalid_dimensions_raises(shape):
    arr = np.zeros(shape)

    with pytest.raises(
        ValueError,
        match=r"Expected a 3D or 4D visibility array",
    ):
        unpack_shape(arr)


# =========================
# extract_vis
# =========================


class MockUVData:
    pass


def test_extract_vis_4d_all_frequencies():
    uv = MockUVData()

    uv.time_array = np.array([1, 1, 2, 2])

    # shape: (Nblts, Nspws, Nfreq, Npol)
    uv.data_array = np.arange(4 * 1 * 3 * 2).reshape(4, 1, 3, 2)

    result = extract_vis(
        uv,
        time_idx=0,
        pol_idx=1,
    )

    expected = uv.data_array[[0, 1], 0, :, 1]

    np.testing.assert_array_equal(result, expected)


def test_extract_vis_4d_single_frequency():
    uv = MockUVData()

    uv.time_array = np.array([1, 1, 2, 2])
    uv.data_array = np.arange(4 * 1 * 3 * 2).reshape(4, 1, 3, 2)

    result = extract_vis(
        uv,
        time_idx=0,
        pol_idx=1,
        freq_idx=2,
    )

    expected = uv.data_array[[0, 1], 0, 2, 1]

    np.testing.assert_array_equal(result, expected)


def test_extract_vis_3d_all_frequencies():
    uv = MockUVData()

    uv.time_array = np.array([1, 1, 2, 2])

    # shape: (Nblts, Nfreq, Npol)
    uv.data_array = np.arange(4 * 3 * 2).reshape(4, 3, 2)

    result = extract_vis(
        uv,
        time_idx=0,
        pol_idx=1,
    )

    expected = uv.data_array[[0, 1], :, 1]

    np.testing.assert_array_equal(result, expected)


def test_extract_vis_3d_single_frequency():
    uv = MockUVData()

    uv.time_array = np.array([1, 1, 2, 2])
    uv.data_array = np.arange(4 * 3 * 2).reshape(4, 3, 2)

    result = extract_vis(
        uv,
        time_idx=0,
        pol_idx=1,
        freq_idx=2,
    )

    expected = uv.data_array[[0, 1], 2, 1]

    np.testing.assert_array_equal(result, expected)


def test_extract_vis_selects_all_rows_for_same_time_value():
    uv = MockUVData()

    uv.time_array = np.array([10, 20, 10, 30])

    uv.data_array = np.arange(4 * 2 * 1).reshape(4, 2, 1)

    result = extract_vis(
        uv,
        time_idx=0,
        pol_idx=0,
    )

    expected = uv.data_array[[0, 2], :, 0]

    np.testing.assert_array_equal(result, expected)
