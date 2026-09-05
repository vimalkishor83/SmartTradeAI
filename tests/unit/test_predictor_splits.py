"""Regression tests for purged chronological model calibration folds."""

import numpy as np


def test_walk_forward_splits_purge_triple_barrier_horizon():
    from app.services.ai.predictor import _TB_MAX_HOLD, _walk_forward_split

    sample_count = 220
    splits = _walk_forward_split(
        np.zeros((sample_count, 2)), np.zeros(sample_count), n_splits=4,
    )

    assert splits
    for train_idx, val_idx in splits:
        assert train_idx[-1] < val_idx[0]
        assert val_idx[0] - train_idx[-1] > _TB_MAX_HOLD
        assert val_idx[-1] < sample_count - 1


def test_walk_forward_honors_explicit_purge_without_reordering():
    from app.services.ai.predictor import _walk_forward_split

    sample_count = 220
    splits = _walk_forward_split(
        np.zeros((sample_count, 2)), np.zeros(sample_count), n_splits=3, purge_bars=3,
    )

    assert splits
    for train_idx, val_idx in splits:
        assert np.all(np.diff(train_idx) == 1)
        assert np.all(np.diff(val_idx) == 1)
        assert val_idx[0] - train_idx[-1] == 4
