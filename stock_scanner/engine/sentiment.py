"""
stock_scanner/engine/sentiment.py
==================================
News sentiment analysis using FinBERT (financial-domain BERT).
Fetches headlines from yfinance and produces per-ticker signals:
  BULLISH / NEUTRAL / BEARISH  +  weighted score in [-1, +1].

Cache: reports/sentiment_cache.pkl  (4-hour TTL)

Install deps once:
    pip install transformers torch
"""

import os, pickle, logging
from datetime import datetime, timedelta
from typing import Dict, List

import yfinance as yf

logger = logging.getLogger("sentiment")

SENTIMENT_CACHE  = "reports/sentiment_cache.pkl"
CACHE_MAX_AGE_H  = 4
BULLISH_THRESHOLD =  0.15
BEARISH_THRESHOLD = -0.15


class SentimentEngine:
    def __init__(self):
        self._pipe = None

    # ── model loading ─────────────────────────────────────────────────────────

    def _load_model(self):
        if self._pipe is not None:
            return self._pipe
        try:
            from transformers import pipeline as hf_pipeline
            print("  Loading FinBERT (first run downloads ~400 MB) ...", end=" ", flush=True)
            self._pipe = hf_pipeline(
                "text-classification",
                model="ProsusAI/finbert",
                top_k=None,
                device=-1,   # force CPU; set to 0 for GPU
            )
            print("ready.")
        except ImportError:
            raise ImportError(
                "transformers not installed. Run:\n"
                "    pip install transformers torch"
            )
        return self._pipe

    # ── news fetch ────────────────────────────────────────────────────────────

    def _fetch_news(self, ticker: str) -> List[Dict]:
        try:
            return yf.Ticker(ticker).news or []
        except Exception as e:
            logger.warning(f"News fetch failed for {ticker}: {e}")
            return []

    # ── scoring ───────────────────────────────────────────────────────────────

    def _score(self, text: str) -> Dict:
        pipe = self._load_model()
        try:
            raw = pipe(text[:512], truncation=True)
            # raw is [[{label, score}, ...]] (list-of-list when top_k=None)
            items = raw[0] if raw and isinstance(raw[0], list) else raw
            scores = {r["label"]: r["score"] for r in items}
            pos = scores.get("positive", 0)
            neg = scores.get("negative", 0)
            neu = scores.get("neutral",  0)
            net = pos - neg
            label = ("BULLISH" if pos > neg and pos > neu
                     else "BEARISH" if neg > pos and neg > neu
                     else "NEUTRAL")
            return {"score": round(net, 4), "label": label}
        except Exception as e:
            logger.warning(f"FinBERT scoring error: {e}")
            return {"score": 0, "label": "NEUTRAL"}

    # ── per-ticker analysis ───────────────────────────────────────────────────

    def _parse_article(self, art: Dict) -> Dict:
        """Normalise article dict across old and new yfinance news structures."""
        # New structure (yfinance ≥ 0.2.52): {"id": ..., "content": {...}}
        if "content" in art and isinstance(art["content"], dict):
            c = art["content"]
            title   = c.get("title")   or ""
            summary = c.get("summary") or c.get("description") or ""
            pub_str = c.get("pubDate") or c.get("displayTime") or ""
            # pubDate is ISO string e.g. "2026-06-25T23:13:47Z"
            try:
                pub = pub_str[:10]   # "YYYY-MM-DD"
            except Exception:
                pub = ""
        else:
            # Legacy structure: flat dict with providerPublishTime (unix ts)
            title   = art.get("title")   or ""
            summary = art.get("summary") or ""
            pub_ts  = art.get("providerPublishTime") or 0
            pub     = datetime.fromtimestamp(pub_ts).strftime("%Y-%m-%d") if pub_ts else ""
        return {"title": title.strip(), "summary": summary.strip(), "published": pub}

    def analyze(self, ticker: str) -> Dict:
        articles = self._fetch_news(ticker)[:10]
        if not articles:
            return _empty()

        self._load_model()          # ensure model is ready before looping

        weighted, headlines = [], []
        for i, art in enumerate(articles):
            parsed  = self._parse_article(art)
            title   = parsed["title"]
            summary = parsed["summary"]
            text    = (title + ". " + summary).strip()
            if not text:
                continue

            result = self._score(text)
            weight = 1.0 / (i + 1)   # decay: most-recent article counts most
            weighted.append((result["score"], weight))

            headlines.append({
                "title":     title,
                "sentiment": result["label"],
                "score":     result["score"],
                "published": parsed["published"],
            })

        if not weighted:
            return _empty()

        total_w   = sum(w for _, w in weighted)
        avg_score = sum(s * w for s, w in weighted) / total_w
        label     = ("BULLISH" if avg_score > BULLISH_THRESHOLD
                     else "BEARISH" if avg_score < BEARISH_THRESHOLD
                     else "NEUTRAL")

        # Surface the most decisive headlines first
        headlines.sort(key=lambda h: abs(h["score"]), reverse=True)

        return {
            "sentiment_score": round(avg_score, 4),
            "sentiment_label": label,
            "news_count":      len(headlines),
            "top_headlines":   headlines[:3],
        }

    # ── batch with disk cache ─────────────────────────────────────────────────

    def analyze_batch(self, tickers: List[str]) -> Dict[str, Dict]:
        cache  = _load_cache()
        result = {}
        now    = datetime.now()

        for ticker in tickers:
            entry = cache.get(ticker)
            if entry and (now - entry["timestamp"]) < timedelta(hours=CACHE_MAX_AGE_H):
                result[ticker] = entry["data"]
                continue

            print(f"  Sentiment {ticker:<12}", end=" ", flush=True)
            data = self.analyze(ticker)
            lbl  = data["sentiment_label"]
            sc   = data["sentiment_score"]
            cnt  = data["news_count"]
            print(f"→ {lbl:<8} ({sc:+.2f}, {cnt} articles)")

            result[ticker]  = data
            cache[ticker]   = {"timestamp": now, "data": data}

        _save_cache(cache)
        return result


# ── cache helpers ─────────────────────────────────────────────────────────────

def _empty() -> Dict:
    return {"sentiment_score": 0, "sentiment_label": "NEUTRAL",
            "news_count": 0, "top_headlines": []}


def _load_cache() -> Dict:
    if os.path.exists(SENTIMENT_CACHE):
        try:
            with open(SENTIMENT_CACHE, "rb") as f:
                return pickle.load(f)
        except Exception:
            pass
    return {}


def _save_cache(cache: Dict):
    os.makedirs("reports", exist_ok=True)
    with open(SENTIMENT_CACHE, "wb") as f:
        pickle.dump(cache, f)
