import logging
import numpy as np
import pandas as pd
from typing import List, Dict, Any, Tuple, Optional

logger = logging.getLogger(__name__)

class MarketStructureEngine:
    """
    MarketStructureEngine: Advanced technical analysis engine that detects horizontal
    support/resistance zones, diagonal trendlines, and classifies the current market context.
    """
    def __init__(self, window_size: int = 5, tolerance_pct: float = 0.015):
        self.window_size = window_size
        self.tolerance_pct = tolerance_pct

    def analyze_structure(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Performs full market structure analysis on historical OHLC DataFrame.
        """
        if df.empty or len(df) < (self.window_size * 2 + 10):
            logger.warning("DataFrame too small to perform market structure analysis.")
            return {
                "support_zones": [],
                "resistance_zones": [],
                "support_trendlines": [],
                "resistance_trendlines": [],
                "context": "Unknown (Insufficient Data)"
            }

        # Ensure index is sorted chronologically
        df = df.sort_index()
        current_price = float(df['Close'].iloc[-1])

        # 1. Identify pivot highs and lows
        p_highs, p_lows = self._find_pivots(df)

        # 2. Cluster pivots to find horizontal zones
        support_zones = self._build_horizontal_zones(df, p_lows, "support", current_price)
        resistance_zones = self._build_horizontal_zones(df, p_highs, "resistance", current_price)

        # 3. Detect diagonal trendlines (Long-term and Short-term)
        long_term_support = self._detect_trendlines(df, p_lows, "support", current_price, term="long")
        long_term_resistance = self._detect_trendlines(df, p_highs, "resistance", current_price, term="long")
        short_term_support = self._detect_trendlines(df, p_lows, "support", current_price, term="short")
        short_term_resistance = self._detect_trendlines(df, p_highs, "resistance", current_price, term="short")

        # 4. Classify current context using long-term trendlines
        context = self._classify_context(current_price, support_zones, resistance_zones, long_term_support, long_term_resistance)

        return {
            "support_zones": support_zones[:23],  # Rank and take top 23
            "resistance_zones": resistance_zones[:23],  # Rank and take top 23
            "support_trendlines": long_term_support,  # Backward compatibility
            "resistance_trendlines": long_term_resistance,  # Backward compatibility
            "long_term_support_trendlines": long_term_support,
            "long_term_resistance_trendlines": long_term_resistance,
            "short_term_support_trendlines": short_term_support,
            "short_term_resistance_trendlines": short_term_resistance,
            "context": context
        }

    def _find_pivots(self, df: pd.DataFrame) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Detects local maxima (highs) and minima (lows) in OHLC data.
        Requires the pivot bar to be strictly greater/less than its immediate
        neighbors to avoid marking every bar in flat regions as a pivot.
        """
        p_highs = []
        p_lows = []
        n = len(df)
        w = self.window_size

        for i in range(w, n - w):
            sub_highs = df['High'].iloc[i - w : i + w + 1]
            sub_lows = df['Low'].iloc[i - w : i + w + 1]

            current_high = df['High'].iloc[i]
            current_low = df['Low'].iloc[i]

            # Local Maxima: must be the window maximum AND strictly above both
            # immediate neighbors to prevent consecutive flat-top duplicates.
            if (current_high == sub_highs.max()
                    and df['High'].iloc[i - 1] < current_high
                    and df['High'].iloc[i + 1] < current_high):
                p_highs.append({
                    "index": i,
                    "date": df.index[i],
                    "price": float(current_high),
                    "volume": float(df['Volume'].iloc[i])
                })

            # Local Minima: must be the window minimum AND strictly below both
            # immediate neighbors.
            if (current_low == sub_lows.min()
                    and df['Low'].iloc[i - 1] > current_low
                    and df['Low'].iloc[i + 1] > current_low):
                p_lows.append({
                    "index": i,
                    "date": df.index[i],
                    "price": float(current_low),
                    "volume": float(df['Volume'].iloc[i])
                })

        return p_highs, p_lows

    def _build_horizontal_zones(
        self, 
        df: pd.DataFrame, 
        pivots: List[Dict[str, Any]], 
        level_type: str,
        current_price: float
    ) -> List[Dict[str, Any]]:
        """
        Clusters pivot points using Agglomerative Clustering (following day0market/support_resistance)
        to find horizontal S&R zones, then rates each zone using the TouchScorer algorithm.
        """
        if not pivots:
            return []

        prices = np.array([p["price"] for p in pivots])
        
        if len(prices) == 1:
            p = pivots[0]
            price = p["price"]
            distance_pct = (price - current_price) / current_price
            return [{
                "type": f"{level_type}_zone",
                "zone": [price, price],
                "center_price": price,
                "price_range": [price, price],
                "touch_count": 1,
                "recency": 30,
                "recency_days": 30,
                "reaction_strength": 0.02,
                "distance_from_current_price": distance_pct,
                "distance_pct": distance_pct,
                "strength_score": 10.0
            }]

        # 1. Cluster pivot prices using AgglomerativeClustering
        from sklearn.cluster import AgglomerativeClustering
        from stock_scanner.pricelevels.scoring.touch_scorer import TouchScorer, PointEventType
        
        distance_threshold = self.tolerance_pct * current_price
        
        clustering = AgglomerativeClustering(
            distance_threshold=distance_threshold,
            n_clusters=None,
            linkage='complete'
        )
        
        try:
            clustering.fit(prices.reshape(-1, 1))
            labels = clustering.labels_
        except Exception as e:
            logger.warning(f"Agglomerative Clustering failed: {e}")
            return []

        # Group pivots into clusters based on labels
        clusters_dict = {}
        for idx, label in enumerate(labels):
            if label not in clusters_dict:
                clusters_dict[label] = []
            clusters_dict[label].append(prices[idx])

        # Prepare levels in the format TouchScorer expects: list of dicts with 'price'
        levels_to_score = [{'price': float(np.median(cluster_prices))} for cluster_prices in clusters_dict.values()]

        # Prepare df copy with Datetime column if not present
        df_copy = df.copy()
        if 'Datetime' not in df_copy.columns:
            df_copy['Datetime'] = df_copy.index

        # Run the TouchScorer algorithm from the repository
        # Parameters use percentage values divided by 100 internally, so
        # diff_perc_for_candle_close=1.5 → 1.5% touch tolerance (was 0.05 → 0.05%)
        # diff_perc_from_extreme=2.0    → 2% extreme proximity (was 0.05 → 0.05%)
        scorer = TouchScorer(
            min_candles_between_body_cuts=3,
            diff_perc_from_extreme=2.0,
            min_distance_between_levels=0.5,
            min_trend_percent=0.5,
            diff_perc_for_candle_close=1.5
        )
        scorer.fit(levels_to_score, df_copy)

        zones = []
        n_days = len(df)

        for idx, (level_dict, score_tuple) in enumerate(zip(levels_to_score, scorer.scores)):
            center_price = level_dict['price']
            score_i, scored_price, point_score = score_tuple
            
            cluster_prices = list(clusters_dict.values())[idx]
            min_price = float(np.min(cluster_prices))
            max_price = float(np.max(cluster_prices))
            pivot_touch_count = len(cluster_prices)
            
            events = point_score.point_event_list
            touch_events = [e for e in events if e.type in (
                PointEventType.TOUCH_DOWN,
                PointEventType.TOUCH_DOWN_HIGHLOW,
                PointEventType.TOUCH_UP,
                PointEventType.TOUCH_UP_HIGHLOW
            )]
            
            if touch_events:
                latest_event_time = touch_events[-1].timestamp
                matching_rows = df_copy[df_copy['Datetime'] == latest_event_time]
                if not matching_rows.empty:
                    try:
                        latest_idx = df_copy.index.get_loc(matching_rows.index[-1])
                        # Handle integer/boolean/slice indices
                        if isinstance(latest_idx, slice):
                            latest_idx = latest_idx.start
                        elif isinstance(latest_idx, np.ndarray):
                            latest_idx = int(latest_idx[0])
                        recency_days = n_days - int(latest_idx)
                    except Exception:
                        recency_days = 30
                else:
                    recency_days = 30
            else:
                matching_pivots = df_copy[df_copy['Close'].isin(cluster_prices)]
                if not matching_pivots.empty:
                    try:
                        latest_idx = df_copy.index.get_loc(matching_pivots.index[-1])
                        if isinstance(latest_idx, slice):
                            latest_idx = latest_idx.start
                        elif isinstance(latest_idx, np.ndarray):
                            latest_idx = int(latest_idx[0])
                        recency_days = n_days - int(latest_idx)
                    except Exception:
                        recency_days = 30
                else:
                    recency_days = 30

            reaction_strengths = []
            for e in touch_events:
                matching_rows = df_copy[df_copy['Datetime'] == e.timestamp]
                if not matching_rows.empty:
                    row = matching_rows.iloc[-1]
                    reaction_strengths.append((row['High'] - row['Low']) / row['Close'])
            avg_reaction = float(np.mean(reaction_strengths)) if reaction_strengths else 0.0
            
            distance_pct = (center_price - current_price) / current_price
            strength_score = float(point_score.score + (pivot_touch_count * 10.0))

            zones.append({
                "type": f"{level_type}_zone",
                "zone": [min_price, max_price],
                "center_price": center_price,
                "price_range": [min_price, max_price],
                "touch_count": pivot_touch_count,
                "recency": int(recency_days),
                "recency_days": int(recency_days),
                "reaction_strength": avg_reaction,
                "distance_from_current_price": distance_pct,
                "distance_pct": distance_pct,
                "strength_score": strength_score
            })

        zones.sort(key=lambda x: x["strength_score"], reverse=True)
        return zones

    def _detect_trendlines(
        self,
        df: pd.DataFrame,
        pivots: List[Dict[str, Any]],
        line_type: str,
        current_price: float,
        term: str = "long"
    ) -> List[Dict[str, Any]]:
        """
        Detects diagonal trendlines using a pivot-based approach.

        For each pair of pivot points a candidate line is drawn; additional
        pivot points within tolerance are counted as extra touches.  The line
        is then validated by counting how many bars have price meaningfully
        past the line (violations).  Lines with too many violations are
        discarded.  Remaining candidates are deduplicated and ranked.

        This replaces the previous trendln-library approach whose errpct
        scaling made the effective tolerance essentially zero for real stocks
        over longer periods, causing zero trendlines to be returned.
        """
        n_days = len(df)

        if n_days < 10:
            return []

        # Restrict pivots to the relevant time window
        if term == "short":
            cutoff = max(0, n_days - 120)
            local_pivots = [p for p in pivots if p["index"] >= cutoff]
        else:
            local_pivots = list(pivots)

        # When no pre-computed pivots are provided, detect them from the raw
        # price series so the method can work standalone (e.g. in unit tests).
        if len(local_pivots) < 2:
            auto_highs, auto_lows = self._find_pivots(df)
            if line_type == "support":
                local_pivots = auto_lows if term == "long" else [
                    p for p in auto_lows if p["index"] >= max(0, n_days - 120)]
            else:
                local_pivots = auto_highs if term == "long" else [
                    p for p in auto_highs if p["index"] >= max(0, n_days - 120)]

        if len(local_pivots) < 2:
            return []

        # 2 % of price: a pivot within this band counts as a line touch
        touch_tolerance = 0.02
        # 2.5 % past the line counts as a violation (wicks slightly past are ignored)
        break_tolerance = 0.025
        prices_col = 'Low' if line_type == "support" else 'High'

        candidates: List[Dict[str, Any]] = []

        for i in range(len(local_pivots)):
            for j in range(i + 1, len(local_pivots)):
                p1 = local_pivots[i]
                p2 = local_pivots[j]

                x1, y1 = p1["index"], p1["price"]
                x2, y2 = p2["index"], p2["price"]

                dx = x2 - x1
                if dx == 0:
                    continue

                slope = (y2 - y1) / dx
                intercept = y1 - slope * x1

                # Collect all pivots that sit within touch_tolerance of the line
                touch_indices: List[int] = []
                for p in local_pivots:
                    xi = p["index"]
                    line_val = slope * xi + intercept
                    if line_val > 0 and abs(p["price"] - line_val) / line_val <= touch_tolerance:
                        touch_indices.append(xi)

                if len(touch_indices) < 2:
                    continue

                # Span check
                t_min, t_max = min(touch_indices), max(touch_indices)
                span = t_max - t_min
                if term == "long" and span < 60:
                    continue
                if term == "short" and span < 10:
                    continue

                # Count how many bars have price meaningfully past the line
                start_idx = t_min
                total_bars = n_days - start_idx
                violations = 0
                line_collapsed = False

                for k in range(start_idx, n_days):
                    line_val = slope * k + intercept
                    if line_val <= 0:
                        line_collapsed = True
                        break
                    bar_val = float(df[prices_col].iloc[k])
                    if line_type == "support":
                        if bar_val < line_val * (1.0 - break_tolerance):
                            violations += 1
                    else:
                        if bar_val > line_val * (1.0 + break_tolerance):
                            violations += 1

                if line_collapsed:
                    continue

                # Allow up to 3 violations or 5 % of the bars
                max_violations = max(3, int(total_bars * 0.05))
                if violations > max_violations:
                    continue

                current_val = slope * (n_days - 1) + intercept
                if current_val <= 0:
                    continue

                recency = n_days - 1 - t_max
                recency_factor = max(0.0, 1.0 - recency / 365.0)

                reaction_ranges = []
                for idx in touch_indices:
                    h_val = float(df['High'].iloc[idx])
                    l_val = float(df['Low'].iloc[idx])
                    c_val = float(df['Close'].iloc[idx])
                    if c_val > 0:
                        reaction_ranges.append((h_val - l_val) / c_val)
                avg_reaction = float(np.mean(reaction_ranges)) if reaction_ranges else 0.0

                n_touches = len(touch_indices)
                distance_pct = (current_val - current_price) / current_price
                strength_score = (n_touches * 20.0) + (recency_factor * 25.0) + (avg_reaction * 100.0)
                if term == "long":
                    strength_score += 15.0

                candidates.append({
                    "type": f"{line_type}_trendline",
                    "term": term,
                    "line": {"slope": slope, "intercept": intercept, "current_value": current_val},
                    "slope": slope,
                    "intercept": intercept,
                    "current_value": current_val,
                    "start_index": start_idx,
                    "end_index": int(t_max),
                    "touch_index_list": sorted(set(touch_indices)),
                    "touch_count": n_touches,
                    "recency": int(recency),
                    "recency_days": int(recency),
                    "reaction_strength": avg_reaction,
                    "distance_from_current_price": distance_pct,
                    "distance_pct": distance_pct,
                    "strength_score": float(strength_score)
                })

        # Sort best first, then deduplicate lines that are nearly identical
        candidates.sort(key=lambda x: x["strength_score"], reverse=True)

        filtered: List[Dict[str, Any]] = []
        for cand in candidates:
            is_duplicate = False
            for accepted in filtered:
                slope_close = abs(cand["slope"] - accepted["slope"]) <= (
                    abs(accepted["slope"]) * 0.10 + 1e-8)
                val_close = abs(cand["current_value"] - accepted["current_value"]) / (
                    accepted["current_value"] + 1e-8) <= 0.02
                if slope_close and val_close:
                    is_duplicate = True
                    break
            if not is_duplicate:
                filtered.append(cand)

        return filtered[:10]

    def _classify_context(
        self, 
        current_price: float,
        supports: List[Dict[str, Any]], 
        resistances: List[Dict[str, Any]],
        s_trendlines: List[Dict[str, Any]],
        r_trendlines: List[Dict[str, Any]]
    ) -> str:
        """
        Classifies the asset's current price position relative to detected support & resistance zones.
        """
        # Find closest support and resistance below and above current price
        closest_support = None
        closest_resistance = None

        for s in supports:
            if s["center_price"] <= current_price:
                if closest_support is None or s["center_price"] > closest_support["center_price"]:
                    closest_support = s

        for r in resistances:
            if r["center_price"] >= current_price:
                if closest_resistance is None or r["center_price"] < closest_resistance["center_price"]:
                    closest_resistance = r

        # Classification rules
        if closest_support and abs(current_price - closest_support["center_price"]) / closest_support["center_price"] <= 0.015:
            return "Testing Horizontal Support"
        
        if closest_resistance and abs(closest_resistance["center_price"] - current_price) / current_price <= 0.015:
            return "Testing Horizontal Resistance"

        # Check if price has broken out above all major horizontal resistance zones
        all_resistances = [r["center_price"] for r in resistances]
        if all_resistances and current_price > max(all_resistances):
            return "Bullish Breakout (All-Time Highs / Multi-Year Highs)"

        # Check if price has broken down below all major horizontal support zones
        all_supports = [s["center_price"] for s in supports]
        if all_supports and current_price < min(all_supports):
            return "Bearish Breakdown (Multi-Year Lows)"

        # Check trend channels
        if s_trendlines and r_trendlines:
            best_s = s_trendlines[0]
            best_r = r_trendlines[0]
            if abs(current_price - best_s["current_value"]) / best_s["current_value"] <= 0.015:
                return "Testing Trendline Support"
            if abs(best_r["current_value"] - current_price) / current_price <= 0.015:
                return "Testing Trendline Resistance"

        return "Consolidating in Range"
