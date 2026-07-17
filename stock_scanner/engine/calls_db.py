"""
stock_scanner/engine/calls_db.py
==================================
SQLite persistence layer for equity calls (BUY positions only).

Only BUY calls (LONG-TERM and SWING bullish) are stored here.
Bearish SELL signals from generate_calls are NOT persisted — they
are displayed on the dashboard but never tracked as positions.

Status flow
-----------
  BUY   → position opened (new entry or re-entry signal)
  HOLD  → re-evaluated, still valid, keep holding
  SELL  → exit signal (stop hit / target reached / thesis broken)
           position closes and moves to history
"""

import json
import os
import sqlite3
from datetime import datetime
from typing import Any

DB_PATH = "reports/calls.db"


# ── connection ────────────────────────────────────────────────────────────────


def _connect() -> sqlite3.Connection:
    os.makedirs("reports", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ── schema ────────────────────────────────────────────────────────────────────


def init_db():
    with _connect() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS calls (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker          TEXT    NOT NULL,
            name            TEXT,
            call_type       TEXT,
            conviction      TEXT,
            signal          TEXT,
            pattern         TEXT,
            call_date       TEXT    NOT NULL,
            entry_price     REAL,
            stop_loss       REAL,
            t1              REAL,
            t2              REAL,
            t3              REAL,
            fair_value      REAL,
            upside_pct      REAL,
            fund_score      REAL,
            sentiment_label TEXT,
            sentiment_score REAL,
            status          TEXT    DEFAULT 'BUY',
            current_price   REAL,
            pnl_pct         REAL,
            pnl_abs         REAL,
            last_updated    TEXT,
            exit_price      REAL,
            exit_date       TEXT,
            notes           TEXT,
            recommendation  TEXT,
            raw_json        TEXT
        );

        CREATE TABLE IF NOT EXISTS call_updates (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            call_id         INTEGER NOT NULL,
            update_date     TEXT    NOT NULL,
            current_price   REAL,
            status          TEXT,
            conviction      TEXT,
            sentiment_label TEXT,
            pnl_pct         REAL,
            notes           TEXT,
            FOREIGN KEY (call_id) REFERENCES calls(id)
        );
        """)


# ── upsert ────────────────────────────────────────────────────────────────────


def upsert_call(call: dict[str, Any], call_type: str) -> int:
    """
    Insert a new call or refresh an existing ACTIVE/HOLD/REVIEW call
    for the same ticker + call_type.  Returns the row id.
    """
    init_db()
    ticker = call["ticker"]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    today = now[:10]

    # For LT calls there's no entry_price (buy at market); use current_price
    entry_price = call.get("entry_price") or call.get("current_price")

    raw = json.dumps(call, default=str)

    with _connect() as conn:
        existing = conn.execute(
            "SELECT id FROM calls WHERE ticker=? AND call_type=? " "AND status IN ('BUY','HOLD')",
            (ticker, call_type),
        ).fetchone()

        if existing:
            call_id = existing["id"]
            conn.execute(
                """
                UPDATE calls SET
                    name=?, conviction=?, signal=?, pattern=?,
                    entry_price=COALESCE(entry_price, ?),
                    stop_loss=?, t1=?, t2=?, t3=?,
                    fair_value=?, upside_pct=?, fund_score=?,
                    sentiment_label=?, sentiment_score=?,
                    last_updated=?, raw_json=?
                WHERE id=?
            """,
                (
                    call.get("name"),
                    call.get("conviction"),
                    call.get("signal"),
                    call.get("pattern"),
                    entry_price,  # only fills in if NULL
                    call.get("stop_loss"),
                    call.get("t1"),
                    call.get("t2"),
                    call.get("t3"),
                    call.get("fair_value"),
                    call.get("upside_pct"),
                    call.get("fund_score"),
                    call.get("sentiment_label"),
                    call.get("sentiment_score"),
                    now,
                    raw,
                    call_id,
                ),
            )
        else:
            cur = conn.execute(
                """
                INSERT INTO calls (
                    ticker, name, call_type, conviction, signal, pattern,
                    call_date, entry_price, stop_loss,
                    t1, t2, t3, fair_value, upside_pct,
                    fund_score, sentiment_label, sentiment_score,
                    status, last_updated, raw_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'BUY',?,?)
            """,
                (
                    ticker,
                    call.get("name"),
                    call_type,
                    call.get("conviction"),
                    call.get("signal"),
                    call.get("pattern"),
                    call.get("date") or today,
                    entry_price,
                    call.get("stop_loss"),
                    call.get("t1"),
                    call.get("t2"),
                    call.get("t3"),
                    call.get("fair_value"),
                    call.get("upside_pct"),
                    call.get("fund_score"),
                    call.get("sentiment_label"),
                    call.get("sentiment_score"),
                    now,
                    raw,
                ),
            )
            call_id = cur.lastrowid

    return call_id


# ── queries ───────────────────────────────────────────────────────────────────


def get_active_calls() -> list[dict]:
    """Return all open positions (BUY or HOLD)."""
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM calls WHERE status IN ('BUY','HOLD') " "ORDER BY call_date DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_calls(limit: int = 200) -> list[dict]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(f"SELECT * FROM calls ORDER BY call_date DESC LIMIT {limit}").fetchall()
    return [dict(r) for r in rows]


def get_call_history(call_id: int) -> list[dict]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM call_updates WHERE call_id=? ORDER BY update_date DESC", (call_id,)
        ).fetchall()
    return [dict(r) for r in rows]


# ── update ────────────────────────────────────────────────────────────────────


def update_call(
    call_id: int,
    current_price: float,
    status: str,
    pnl_pct: float,
    pnl_abs: float,
    notes: str,
    recommendation: str = "",
    conviction: str | None = None,
    sentiment_label: str | None = None,
    exit_price: float | None = None,
):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with _connect() as conn:
        conn.execute(
            """
            UPDATE calls SET
                current_price=?, status=?, pnl_pct=?, pnl_abs=?,
                notes=?, recommendation=?, last_updated=?,
                sentiment_label=COALESCE(?, sentiment_label),
                conviction=COALESCE(?, conviction),
                exit_price=CASE WHEN ? IS NOT NULL THEN ? ELSE exit_price END,
                exit_date=CASE WHEN ? IS NOT NULL THEN ? ELSE exit_date END
            WHERE id=?
        """,
            (
                current_price,
                status,
                pnl_pct,
                pnl_abs,
                notes,
                recommendation,
                now,
                sentiment_label,
                conviction,
                exit_price,
                exit_price,
                exit_price,
                now[:10],
                call_id,
            ),
        )
        conn.execute(
            """
            INSERT INTO call_updates
                (call_id, update_date, current_price, status, conviction,
                 sentiment_label, pnl_pct, notes)
            VALUES (?,?,?,?,?,?,?,?)
        """,
            (call_id, now, current_price, status, conviction, sentiment_label, pnl_pct, notes),
        )


def close_call(call_id: int, exit_price: float, notes: str = "Manually sold"):
    """Mark a position as SELL (closed) at the given exit price."""
    with _connect() as conn:
        row = conn.execute("SELECT * FROM calls WHERE id=?", (call_id,)).fetchone()
    if row is None:
        return
    row = dict(row)
    entry = row.get("entry_price") or exit_price
    pnl_pct = (exit_price - entry) / entry if entry else 0
    pnl_abs = pnl_pct * 10_000
    update_call(
        call_id,
        exit_price,
        "SELL",
        pnl_pct,
        pnl_abs,
        notes,
        recommendation="Position sold.",
        exit_price=exit_price,
    )


# ── portfolio export ──────────────────────────────────────────────────────────


def export_portfolio_json(
    out_path: str = "dashboard/portfolio.json",
    equity_curves: dict | None = None,
    portfolio_curve: list | None = None,
):
    """Write a portfolio.json for the dashboard to consume."""
    init_db()
    all_calls = get_all_calls()
    active = [c for c in all_calls if c["status"] in ("BUY", "HOLD")]
    closed = [c for c in all_calls if c["status"] == "SELL"]

    wins = sum(1 for c in closed if (c.get("pnl_pct") or 0) > 0)
    losses = sum(1 for c in closed if (c.get("pnl_pct") or 0) <= 0)
    stops = sum(1 for c in closed if "stop" in (c.get("notes") or "").lower())

    active_pnls = [c.get("pnl_pct") or 0 for c in active]
    avg_pnl = sum(active_pnls) / len(active_pnls) if active_pnls else 0

    best = max(active, key=lambda c: c.get("pnl_pct") or 0, default=None)
    worst = min(active, key=lambda c: c.get("pnl_pct") or 0, default=None)

    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "summary": {
            "total_active": len(active),
            "avg_pnl_pct": round(avg_pnl * 100, 2),
            "closed_wins": wins,
            "closed_losses": losses,
            "stopped_out": stops,
            "total_ever": len(all_calls),
            "best_call": {
                "ticker": best["ticker"],
                "pnl_pct": round((best.get("pnl_pct") or 0) * 100, 2),
            }
            if best
            else None,
            "worst_call": {
                "ticker": worst["ticker"],
                "pnl_pct": round((worst.get("pnl_pct") or 0) * 100, 2),
            }
            if worst
            else None,
        },
        "active": [_clean(c) for c in active],
        "closed": [_clean(c) for c in closed],
        "equity_curves": equity_curves or {},
        "portfolio_curve": portfolio_curve or [],
    }

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)
    return out_path


def _clean(row: dict) -> dict:
    """Strip raw_json blob and round floats for the dashboard."""
    out = {k: v for k, v in row.items() if k != "raw_json"}
    for k in ("pnl_pct", "upside_pct", "sentiment_score"):
        if out.get(k) is not None:
            out[k] = round(float(out[k]), 4)
    return out
