import numpy as np
import pandas as pd

PEAK = 1
VALLEY = -1


def identify_initial_pivot(X, up_thresh, down_thresh):
    """
    Determines the first pivot (peak or valley) for the ZigZag algorithm.
    """
    x_0 = X[0]
    max_x = x_0
    min_x = x_0
    max_t = 0
    min_t = 0

    up_thresh_val = up_thresh + 1
    down_thresh_val = down_thresh + 1

    for t in range(1, len(X)):
        x_t = X[t]
        ratio_min = x_t / (min_x if min_x != 0 else 1e-8)
        if ratio_min >= up_thresh_val:
            return VALLEY if min_t == 0 else PEAK

        ratio_max = x_t / (max_x if max_x != 0 else 1e-8)
        if ratio_max <= down_thresh_val:
            return PEAK if max_t == 0 else VALLEY

        if x_t > max_x:
            max_x = x_t
            max_t = t
        if x_t < min_x:
            min_x = x_t
            min_t = t

    t_n = len(X) - 1
    return VALLEY if x_0 < X[t_n] else PEAK


def peak_valley_pivots(X, up_thresh, down_thresh):
    """
    Find the peaks and valleys of a series.
    """
    if down_thresh > 0:
        raise ValueError("The down_thresh must be negative.")

    initial_pivot = identify_initial_pivot(X, up_thresh, down_thresh)
    t_n = len(X)
    pivots = np.zeros(t_n, dtype=np.int_)
    trend = -initial_pivot
    last_pivot_t = 0
    last_pivot_x = X[0]
    pivots[0] = initial_pivot

    up_thresh_val = up_thresh + 1
    down_thresh_val = down_thresh + 1

    for t in range(1, t_n):
        x = X[t]
        r = x / (last_pivot_x if last_pivot_x != 0 else 1e-8)
        if trend == -1:
            if r >= up_thresh_val:
                pivots[last_pivot_t] = 0
                pivots[t] = PEAK
                trend = 1
                last_pivot_t = t
                last_pivot_x = x
            elif x < last_pivot_x:
                last_pivot_t = t
                last_pivot_x = x
        else:
            if r <= down_thresh_val:
                pivots[last_pivot_t] = 0
                pivots[t] = VALLEY
                trend = -1
                last_pivot_t = t
                last_pivot_x = x
            elif x > last_pivot_x:
                last_pivot_t = t
                last_pivot_x = x

    return pivots


from .exceptions import InvalidArgumentException, InvalidParameterException


class BaseLevelFinder:
    def __init__(self, merge_distance, merge_percent=None, level_selector="median"):
        self._merge_distance = merge_distance
        self._merge_percent = merge_percent

        self._level_selector = level_selector

        self._levels = None
        self._validate_init_args()

    @property
    def levels(self):
        return self._levels

    def _validate_init_args(self):
        pass

    def fit(self, data):
        if isinstance(data, pd.DataFrame):
            X = data["Close"].values
        elif isinstance(data, np.array):
            X = data
        else:
            raise InvalidArgumentException(
                "Only np.array and pd.DataFrame are supported in `fit` method"
            )

        prices = self._find_potential_level_prices(X)
        levels = self._aggregate_prices_to_levels(prices, self._get_distance(X))

        self._levels = levels

    def _find_potential_level_prices(self, X):
        raise NotImplementedError()

    def _get_distance(self, X):
        if self._merge_distance:
            return self._merge_distance

        mean_price = np.mean(X)
        return self._merge_percent * mean_price / 100

    def _aggregate_prices_to_levels(self, pivot_prices, distance):
        raise NotImplementedError()


class BaseZigZagLevels(BaseLevelFinder):
    def __init__(
        self,
        peak_percent_delta,
        merge_distance,
        merge_percent=None,
        min_bars_between_peaks=0,
        peaks="All",
        level_selector="median",
    ):
        self._peak_percent_delta = peak_percent_delta / 100
        self._min_bars_between_peaks = min_bars_between_peaks
        self._peaks = peaks
        super().__init__(merge_distance, merge_percent, level_selector)

    def _find_potential_level_prices(self, X):
        pivots = peak_valley_pivots(X, self._peak_percent_delta, -self._peak_percent_delta)
        indexes = self._get_pivot_indexes(pivots)
        pivot_prices = X[indexes]

        return pivot_prices

    def _get_pivot_indexes(self, pivots):
        if self._peaks == "All":
            indexes = np.where(np.abs(pivots) == 1)
        elif self._peaks == "High":
            indexes = np.where(pivots == 1)
        elif self._peaks == "Low":
            indexes = np.where(pivots == -1)
        else:
            raise InvalidParameterException("Peaks argument should be one of: `All`, `High`, `Low`")

        return (
            indexes if self._min_bars_between_peaks == 0 else self._filter_by_bars_between(indexes)
        )

    def _filter_by_bars_between(self, indexes):
        indexes = np.sort(indexes).reshape(-1, 1)

        try:
            selected = [indexes[0][0]]
        except IndexError:
            return indexes

        pre_idx = indexes[0][0]
        for i in range(1, len(indexes)):
            if indexes[i][0] - pre_idx < self._min_bars_between_peaks:
                continue
            pre_idx = indexes[i][0]
            selected.append(pre_idx)

        return np.array(selected)
