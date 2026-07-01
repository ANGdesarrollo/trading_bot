# VENDORED FROM: backend/research/lib/trajectory.py @ 67077c0271af0efd9cd167a1791f20d50c68bb2c (2026-07-01)
# Frozen strategy — DO NOT EDIT. Re-vendor via SYNC.md when parent research changes constants.
"""Full-run trajectory morphology features for H13.

The prior characterization looked ONLY at the counter-bar (the single bar where
the run first turned). This module describes the SHAPE OF THE WHOLE RUN: how the
move climbed from start to peak, how it accelerated or decelerated, where the
biggest bar sat, and how the peak was formed (exhaustion signature).

All features are strictly causal: they are computed from the L bars of the run
itself (run_end - L + 1 .. run_end), known at the moment the run completes. They
never read forward. The OUTCOME label (reversal vs continuation) is the only
forward-looking quantity, and that lives in the analysis layer, not here.

The shape-vector (normalized close path) feeds unsupervised clustering so we can
discover archetypes (parabolic blow-off, staircase, clean ramp) WITHOUT looking
at the outcome — then measure each archetype's reversal rate separately.
"""
from __future__ import annotations

import numpy as np

SHAPE_POINTS = 20  # resampled length of the normalized close path per run


def _theil_sen_slope(y: np.ndarray) -> float:
    """Robust slope of y over its index, normalized by total displacement.

    Theil-Sen (median of pairwise slopes) resists the single huge bar dominating
    an OLS fit, which matters because exhaustion candles are exactly such outliers.
    """
    n = len(y)
    if n < 2:
        return 0.0
    x = np.arange(n, dtype=float)
    slopes = []
    for i in range(n - 1):
        dx = x[i + 1:] - x[i]
        dy = y[i + 1:] - y[i]
        slopes.append(dy / dx)
    return float(np.median(np.concatenate(slopes)))


def _normalized_path(close_seg: np.ndarray, direction: int) -> np.ndarray:
    """Resample the run's close path to SHAPE_POINTS, oriented so the move always
    goes UP (multiply by direction) and scaled to [0, 1] by its own range.

    Orienting up-runs and down-runs the same way lets one cluster model see both
    as the same morphology (a blow-off is a blow-off regardless of sign).
    """
    oriented = direction * close_seg
    rng = oriented.max() - oriented.min()
    if rng <= 0:
        return np.full(SHAPE_POINTS, 0.5)
    norm = (oriented - oriented.min()) / rng
    src_x = np.linspace(0.0, 1.0, len(norm))
    dst_x = np.linspace(0.0, 1.0, SHAPE_POINTS)
    return np.interp(dst_x, src_x, norm)


def extract_trajectory_features(o, h, l, c, atr, run_end, direction, L, sl_dist):
    """Return (scalar feature dict, normalized shape vector) for one run path.

    Indices span the run: [run_end - L + 1 .. run_end] inclusive (L bars).
    sl_dist is the ATR at run_end (same unit used everywhere in H13).
    """
    start = run_end - L + 1
    if start < 1:
        return None, None

    seg_o = o[start: run_end + 1]
    seg_h = h[start: run_end + 1]
    seg_l = l[start: run_end + 1]
    seg_c = c[start: run_end + 1]
    if len(seg_c) != L:
        return None, None

    bar_range = seg_h - seg_l
    bar_body = np.abs(seg_c - seg_o)
    bar_ret = np.diff(np.concatenate([[c[start - 1]], seg_c]))  # signed returns incl. first bar

    half = L // 2
    first_close = direction * seg_c[:half]
    second_close = direction * seg_c[half:]

    slope_first = _theil_sen_slope(first_close)
    slope_second = _theil_sen_slope(second_close)
    accel_ratio = slope_second / slope_first if abs(slope_first) > 1e-12 else np.nan

    largest_bar_pos = float(np.argmax(bar_range)) / (L - 1)
    largest_body_pos = float(np.argmax(bar_body)) / (L - 1)

    with_run = np.sign(bar_ret) == direction
    monotonicity = float(np.mean(with_run))

    net_disp = abs(seg_c[-1] - c[start - 1])
    path_length = float(np.sum(np.abs(bar_ret)))
    straightness = net_disp / path_length if path_length > 0 else 0.0  # 1=laser, <1=jagged

    peak_window = max(3, L // 8)
    peak_o = seg_o[-peak_window:]
    peak_h = seg_h[-peak_window:]
    peak_l = seg_l[-peak_window:]
    peak_c = seg_c[-peak_window:]
    peak_rng = peak_h - peak_l
    if direction == 1:
        peak_rejection = (peak_h - np.maximum(peak_o, peak_c))
    else:
        peak_rejection = (np.minimum(peak_o, peak_c) - peak_l)
    peak_rejection_frac = float(np.mean(np.where(peak_rng > 0, peak_rejection / peak_rng, 0.0)))

    early_range = float(np.mean(bar_range[:half]))
    late_range = float(np.mean(bar_range[half:]))
    range_expansion = late_range / early_range if early_range > 0 else np.nan

    early_body = float(np.mean(bar_body[:half]))
    late_body = float(np.mean(bar_body[half:]))
    body_contraction = late_body / early_body if early_body > 0 else np.nan

    max_bar_atr = float(np.max(bar_range)) / sl_dist if sl_dist > 0 else np.nan
    total_disp_atr = net_disp / sl_dist if sl_dist > 0 else np.nan

    feats = {
        "accel_ratio": float(accel_ratio) if not np.isnan(accel_ratio) else np.nan,
        "largest_bar_pos": largest_bar_pos,
        "largest_body_pos": largest_body_pos,
        "monotonicity": monotonicity,
        "straightness": straightness,
        "peak_rejection_frac": peak_rejection_frac,
        "range_expansion": float(range_expansion) if not np.isnan(range_expansion) else np.nan,
        "body_contraction": float(body_contraction) if not np.isnan(body_contraction) else np.nan,
        "max_bar_atr": max_bar_atr,
        "total_disp_atr": total_disp_atr,
    }
    shape = _normalized_path(seg_c, direction)
    return feats, shape
