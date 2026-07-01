# Pattern Detection Rule Book

Source: https://github.com/BennyThadikaran/stock-pattern/wiki/Pattern-Algorithms
Adapted for this codebase. All rules are enforced in `patterns.py`.

---

## Core Concepts

### Pivot Identification
A **swing high** at index `i` requires that no bar within `window_size` bars on either
side has a higher High.  A **swing low** requires no lower Low within the window.
Default `window_size = 5` (i.e., 5 unbroken candles on each side).

### avgCandleRange (ACR)
The tolerance for "two prices are at the same level" is NOT a fixed percentage.
It is the **average candle range** (High − Low) of bars between the two anchor pivots:

```
ACR = mean(High[i] - Low[i])  for i in range(pivot_A.index, pivot_C.index + 1)
```

This auto-scales to current volatility: tight-range stocks get a tight tolerance,
high-volatility stocks get proportionally more room.

### Pattern Labelling Convention
Pivots are labelled A, B, C, D, E, F in chronological order.
Even letters (B, D, F) are typically lows; odd letters (A, C, E) are typically highs
(reversed for inverse patterns).

### Confirmation Rule
A pattern is **still valid** only if no closing price after the pattern formed has
breached the key support/resistance level (neckline, pattern low, etc.).
If breached → pattern is invalidated. The engine reassigns and retries to find the
next most recent valid instance.

### Volume Rule (Double Top / Double Bottom)
The second peak/trough must have **lower volume** than the first.
`cVol < aVol` for Double Top; `cVol > aVol` (smaller absolute volume) for Double Bottom.

---

## Pattern Rules

### Head & Shoulders (Bearish)
```
Pivots:  A(high) B(low) C(high=HEAD) D(low) E(high) F(close)

Rules:
  C > max(A, E)               — head is highest
  max(B, D) < min(A, E)       — neckline below both shoulders
  abs(B - D) < ACR(A..E)      — neckline is roughly horizontal
  F < E                        — close hasn't broken the right shoulder
```

### Inverse Head & Shoulders (Bullish)
```
Pivots:  A(low) B(high) C(low=HEAD) D(high) E(low) F(close)

Rules:
  C < min(A, E)               — head is lowest
  min(B, D) > max(A, E)       — neckline above both shoulders
  abs(B - D) < ACR(A..E)      — neckline roughly horizontal
  F > E                        — close hasn't broken the right shoulder
```

### Double Top (Bearish)
```
Pivots:  A(high) B(low) C(high) D(close)

Rules:
  abs(A - C) <= ACR(A..C)     — two peaks at same level (within avg candle range)
  B < min(A, C)               — valley below both peaks
  cVol < aVol                  — volume on second peak lower than first (declining interest)
  B < D < C                    — close above neckline but below peak (pattern still active)
```

### Double Bottom (Bullish)
```
Pivots:  A(low) B(high) C(low) D(close)

Rules:
  abs(A - C) <= ACR(A..C)     — two troughs at same level
  B > max(A, C)               — bounce peak above both troughs
  cVol < aVol                  — volume on second trough lower (selling pressure waning)
  C < D < B                    — close below neckline but above trough (still active)
```

### Symmetrical Triangle
```
Pivots:  A(high) B(low) C(high) D(low) E(high) F(close)

Rules:
  A > C > E                   — falling highs
  B < D                        — rising lows
  E > F                        — close hasn't broken below E yet (inside triangle)
  Lines through A-C-E and B-D converge ahead
```

### Ascending Triangle (Bullish Bias)
```
Pivots:  A(high) B(low) C(high) D(low) E(high) F(close)

Rules:
  abs(A - C) <= ACR(A..C)     — A and C at same level (flat top)
  abs(C - E) <= ACR(C..E)     — C and E at same level (flat top continues)
  B < D                        — rising lows
  F < E                        — close hasn't broken flat top yet
  B < D < F                    — lows progressing upward
```

### Descending Triangle (Bearish Bias)
```
Pivots:  A(high) B(low) C(high) D(low) E(close/high)

Rules:
  abs(B - D) <= ACR(B..D)     — B and D at same level (flat bottom)
  A > C                        — falling highs
  E > D                        — close still above flat bottom (inside triangle)
  A > C > E                    — highs declining
```

### VCP — Volatility Contraction Pattern (Bullish)
```
Pivots:  A(high) B(low) C(high) D(low) E(close)

Rules:
  abs(A - C) <= ACR(A..C)     — A and C at same level (flat top resistance)
  B < min(A, C, D, E)         — B is the absolute lowest (first contraction low)
  D < min(A, C, E)            — D is second-lowest (second contraction, higher than B)
  E < C                        — close hasn't breached C yet
  Each successive contraction is narrower than the previous (D > B, E between D and C)
```

### Rising Wedge (Bearish)
```
Both the highs trendline and lows trendline slope upward, but the lows rise
FASTER than the highs → lines converge above price → bearish breakdown expected.

slope(lows TL) > slope(highs TL) > 0
Current price inside the wedge (between both lines).
```

### Falling Wedge (Bullish)
```
Both lines slope downward, but the highs fall FASTER than the lows →
lines converge below price → bullish breakout expected.

slope(highs TL) < slope(lows TL) < 0
Current price inside the wedge.
```

### Bull Flag (Bullish Continuation)
```
1. Flagpole: strong rally ≥ 5% within ≤ 15 bars (from swing low to swing high)
2. Flag: tight consolidation of ≤ 45% of pole range after the high,
         lasting 3–10 bars
3. Current price inside the flag channel (not broken down)
4. Retracement from pole high ≤ 50% of pole move
```

### Bear Flag (Bearish Continuation)
```
Mirror of Bull Flag — sharp drop ≥ 5%, then tight bounce ≤ 45% of drop,
current price still in consolidation zone.
```

---

## Candlestick Pattern Rules

All candlestick patterns scan only the last `recent_candle_bars` bars (default 15).

### Hammer (Bullish)
```
lower_wick >= 2 × body
upper_wick <= 0.5 × body
Appears after a downtrend or at support.
```

### Shooting Star (Bearish)
```
upper_wick >= 2 × body
lower_wick <= 0.5 × body
Appears after an uptrend or at resistance.
```

### Bullish Engulfing
```
Bar 1: bearish (Close < Open)
Bar 2: bullish, opens below Bar1 Close, closes above Bar1 Open
```

### Bearish Engulfing
```
Bar 1: bullish
Bar 2: bearish, opens above Bar1 Close, closes below Bar1 Open
```

### Morning Star (Bullish 3-bar)
```
Bar 1: strong bearish (large body)
Bar 2: small body (star) — body < 35% of avg(body1, body3)
Bar 3: strong bullish, closes above midpoint of Bar1 body
```

### Evening Star (Bearish 3-bar)
```
Mirror of Morning Star.
```

### Doji
```
body / candle_range <= 5%
Indecision — stronger signal at key S/R levels.
```

### Three White Soldiers (Bullish)
```
3 consecutive bullish candles (Close > Open each)
Each closes higher than the previous
Each body >= 40% of its candle range (substantial bodies, not dojis)
```

### Three Black Crows (Bearish)
```
3 consecutive bearish candles (Close < Open each)
Each closes lower than the previous
Each body >= 40% of candle range
```

### Bullish Harami
```
Bar 1: large bearish candle (body >= 50% of range)
Bar 2: small bullish candle whose body is INSIDE Bar1's body
Bar 2 body < 50% of Bar1 body
```

### Bearish Harami
```
Bar 1: large bullish candle (body >= 50% of range)
Bar 2: small bearish candle whose body is INSIDE Bar1's body
```

### Tweezer Top (Bearish)
```
Two consecutive candles with High within ACR of each other
The second candle is bearish (or closes below its midpoint)
Signals rejection at the same level twice → resistance
```

### Tweezer Bottom (Bullish)
```
Two consecutive candles with Low within ACR of each other
The second candle is bullish (or closes above its midpoint)
Signals support holding at same level twice
```

### Piercing Line (Bullish)
```
Bar 1: bearish candle
Bar 2: bullish, opens BELOW Bar1 Close, closes ABOVE the midpoint of Bar1 body
       but below Bar1 Open (otherwise it's an engulfing)
```

### Dark Cloud Cover (Bearish)
```
Bar 1: bullish candle
Bar 2: bearish, opens ABOVE Bar1 Close, closes BELOW the midpoint of Bar1 body
       but above Bar1 Open (otherwise it's an engulfing)
```

---

## Implementation Notes

1. **ACR replaces fixed %**: Compute `mean(High - Low)` for bars between anchor pivots.
2. **Volume check**: Always compare second-peak/trough volume vs first for Double Top/Bottom.
3. **Breach check**: After identifying pattern, verify no subsequent Close has breached
   the key level. If breached, try next candidate (retry mechanism).
4. **CMP context**: For forming patterns, additionally check if current Close is within
   the valid zone (e.g., inside triangle, inside flag, approaching pattern level).
5. **At-level boost**: A candlestick pattern at a key S/R zone or trendline is given
   higher visual priority and a different label style.
