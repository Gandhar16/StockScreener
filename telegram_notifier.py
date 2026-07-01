"""
telegram_notifier.py
====================
Sends StockCalls equity call reports to a Telegram bot.

Setup (one-time):
  1. Open Telegram → search @BotFather → /newbot → follow prompts → copy token
  2. Start a chat with your new bot (send it /start)
  3. Run:  python telegram_notifier.py --setup
     This will detect your chat ID automatically and save config/telegram.json

Usage:
  python telegram_notifier.py                   # send latest equity_calls.json
  python telegram_notifier.py --smart-money     # include smart money summary too
  python telegram_notifier.py --test            # send a test ping
"""

import os, sys, json, math, argparse, time
from datetime import datetime
from typing import Dict, List, Optional, Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import requests

CONFIG_PATH = "config/telegram.json"
CALLS_PATH  = "dashboard/equity_calls.json"
SM_PATH     = "dashboard/smart_money.json"
TG_API      = "https://api.telegram.org/bot{token}/{method}"
MAX_MSG_LEN = 4000   # Telegram limit is 4096; keep below to be safe


# ── Config ─────────────────────────────────────────────────────────────────────

def load_config() -> Dict:
    if not os.path.exists(CONFIG_PATH):
        print(f"[ERROR] No config found at {CONFIG_PATH}")
        print("Run:  python telegram_notifier.py --setup")
        sys.exit(1)
    with open(CONFIG_PATH) as f:
        return json.load(f)


def save_config(cfg: Dict):
    os.makedirs("config", exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)
    print(f"Config saved to {CONFIG_PATH}")


# ── Telegram API ───────────────────────────────────────────────────────────────

def tg_request(token: str, method: str, payload: Dict) -> Dict:
    url = TG_API.format(token=token, method=method)
    r = requests.post(url, json=payload, timeout=15)
    return r.json()


def send_message(token: str, chat_id: str, text: str,
                 parse_mode: str = "HTML", disable_preview: bool = True) -> bool:
    result = tg_request(token, "sendMessage", {
        "chat_id":                  chat_id,
        "text":                     text,
        "parse_mode":               parse_mode,
        "disable_web_page_preview": disable_preview,
    })
    ok = result.get("ok", False)
    if not ok:
        print(f"  [WARN] Telegram error: {result.get('description','unknown')}")
    return ok


def send_long(token: str, chat_id: str, text: str):
    """Split messages > MAX_MSG_LEN by newline boundaries."""
    if len(text) <= MAX_MSG_LEN:
        send_message(token, chat_id, text)
        return
    parts = []
    current = []
    current_len = 0
    for line in text.split("\n"):
        if current_len + len(line) + 1 > MAX_MSG_LEN and current:
            parts.append("\n".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += len(line) + 1
    if current:
        parts.append("\n".join(current))
    for i, part in enumerate(parts):
        if i > 0:
            time.sleep(0.4)   # avoid Telegram rate limit
        send_message(token, chat_id, part)


# ── Setup wizard ───────────────────────────────────────────────────────────────

def run_setup():
    print("\n=== Telegram Bot Setup ===\n")
    print("Step 1: Create your bot")
    print("  - Open Telegram → search @BotFather")
    print("  - Send:  /newbot")
    print("  - Choose a name (e.g. 'StockCalls Bot') and a username (e.g. 'stockcalls_myname_bot')")
    print("  - BotFather will give you a token like: 7123456789:AAFxxxxxxxxxxxxx\n")

    token = input("Paste your bot token here: ").strip()
    if not token or ":" not in token:
        print("[ERROR] Invalid token format. Should look like: 1234567890:AABBB...")
        sys.exit(1)

    print("\nStep 2: Get your Chat ID")
    print("  - Open Telegram → search for your new bot by the username you just created")
    print("  - Send it any message (e.g. /start or 'hello')")
    print("  - Press Enter here once you've done that...")
    input("  Press Enter to continue > ")

    # Fetch updates to find the chat ID
    print("\n  Fetching chat ID from Telegram ...")
    result = tg_request(token, "getUpdates", {})
    updates = result.get("result", [])

    if not updates:
        print("  [WARN] No messages found. Make sure you sent a message to your bot first.")
        chat_id = input("  Enter your chat ID manually (or press Enter to retry): ").strip()
        if not chat_id:
            print("  No chat ID — aborting.")
            sys.exit(1)
    else:
        msg = updates[-1]["message"]
        chat_id = str(msg["chat"]["id"])
        chat_name = msg["chat"].get("first_name") or msg["chat"].get("title") or "your chat"
        print(f"  Found chat: {chat_name} (ID: {chat_id})")

    # Optional: group/channel override
    override = input(f"\n  Use chat ID {chat_id}? (Enter to confirm, or type a different chat ID): ").strip()
    if override:
        chat_id = override

    # Save config
    cfg = {"token": token, "chat_id": chat_id}
    save_config(cfg)

    # Send test message
    print("\n  Sending test message ...")
    ok = send_message(token, chat_id, "✅ <b>StockCalls Bot connected!</b>\n\nYou'll receive equity call alerts here.")
    if ok:
        print("  Test message sent! Check your Telegram.\n")
    else:
        print("  [WARN] Test message failed — double-check your token and chat ID.\n")


# ── Formatting ─────────────────────────────────────────────────────────────────

def esc(text: str) -> str:
    """Escape characters that break Telegram HTML."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def conviction_icon(conv: str) -> str:
    return {
        "STRONG BUY":     "🟢",
        "BUY":            "🟩",
        "ACCUMULATE":     "🔵",
        "WATCH":          "⚪",
        "HIGH CONVICTION":"🔥",
        "CONFIRMED":      "✅",
        "SETUP":          "👀",
    }.get(conv, "•")


def sentiment_icon(label: str) -> str:
    return {"BULLISH": "📈", "BEARISH": "📉", "NEUTRAL": "➖"}.get(label, "➖")


def fmt_price(val: Optional[float], currency: str = "USD") -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return "—"
    sym = {"USD": "$", "INR": "₹", "GBP": "£", "EUR": "€"}.get(currency, "$")
    if abs(val) >= 1e9:
        return f"{sym}{val/1e9:.2f}B"
    if abs(val) >= 1e6:
        return f"{sym}{val/1e6:.2f}M"
    return f"{sym}{val:,.2f}"


def fmt_pct(val: Optional[float]) -> str:
    if val is None:
        return "—"
    return f"{val*100:+.1f}%"


# ── Message builders ──────────────────────────────────────────────────────────

def build_header(calls: Dict) -> str:
    now  = calls.get("generated_at", datetime.now().strftime("%Y-%m-%d %H:%M"))
    lt   = calls.get("long_term_calls", [])
    sw   = calls.get("swing_calls", [])
    sl   = calls.get("sell_calls", [])

    strong = sum(1 for c in lt if c["conviction"] == "STRONG BUY")
    buy    = sum(1 for c in lt if c["conviction"] == "BUY")
    accum  = sum(1 for c in lt if c["conviction"] == "ACCUMULATE")
    hc     = sum(1 for c in sw if c["conviction"] == "HIGH CONVICTION")
    conf   = sum(1 for c in sw if c["conviction"] == "CONFIRMED")
    hc_s   = sum(1 for c in sl if c["conviction"] == "HIGH CONVICTION")

    lines = [
        "📊 <b>StockCalls — Equity Report</b>",
        f"🕐 {esc(now)}",
        "",
        "📋 <b>Summary</b>",
        f"  🟢 STRONG BUY: {strong}   🟩 BUY: {buy}   🔵 ACCUM: {accum}",
        f"  🔥 HC Swing: {hc}   ✅ Conf Swing: {conf}",
        f"  📉 HC Sell: {hc_s}   Sell total: {len(sl)}",
        "─" * 30,
    ]
    return "\n".join(lines)


def build_lt_section(calls: List[Dict]) -> str:
    if not calls:
        return ""
    lines = ["", "🏦 <b>LONG-TERM CALLS</b>"]
    for c in calls:
        cur  = c.get("currency", "USD")
        icon = conviction_icon(c["conviction"])
        sent = sentiment_icon(c.get("sentiment_label", "NEUTRAL"))
        upside = fmt_pct(c.get("upside_pct"))
        price  = fmt_price(c.get("current_price"), cur)
        fv     = fmt_price(c.get("fair_value"), cur)
        score  = c.get("fund_score", "—")
        flagged = " ⚠️" if c.get("sentiment_flagged") else ""

        lines.append(f"\n{icon} <b>{esc(c['ticker'])}</b> — {esc(c['conviction'])}{flagged}")
        lines.append(f"   {esc(c.get('name','')[:30])}")
        lines.append(f"   Price: <code>{price}</code>  FV: <code>{fv}</code>  Upside: <b>{upside}</b>")
        lines.append(f"   Score: {score}/100  {sent} {esc(c.get('sentiment_label',''))}")
        if c.get("entry_note"):
            lines.append(f"   💡 {esc(c['entry_note'])}")
        for t in c.get("thesis", [])[:2]:
            lines.append(f"   {esc(t[:70])}")
    return "\n".join(lines)


def build_swing_section(calls: List[Dict]) -> str:
    if not calls:
        return ""
    lines = ["", "⚡ <b>SWING CALLS</b>"]
    for c in calls:
        cur  = c.get("currency", "USD")
        icon = conviction_icon(c["conviction"])
        sent = sentiment_icon(c.get("sentiment_label", "NEUTRAL"))
        flagged = " ⚠️" if c.get("sentiment_flagged") else ""
        vol  = "🔊" if c.get("vol_confirmed") else ""
        form = " [forming]" if c.get("forming") else ""

        entry = fmt_price(c.get("entry_price"), cur)
        stop  = fmt_price(c.get("stop_loss"), cur)
        t1    = fmt_price(c.get("t1"), cur)
        t2    = fmt_price(c.get("t2"), cur)
        rr    = f"{c.get('risk_reward',0):.1f}x"

        lines.append(f"\n{icon} <b>{esc(c['ticker'])}</b> — {esc(c['conviction'])}{flagged} {vol}")
        lines.append(f"   Pattern: {esc(c.get('pattern','')[:30])}{form}")
        lines.append(f"   Entry: <code>{entry}</code>  Stop: <code>{stop}</code>  R:R: <b>{rr}</b>")
        lines.append(f"   T1: <code>{t1}</code>  T2: <code>{t2}</code>")
        lines.append(f"   Risk: {c.get('risk_pct',0):.1f}%  {sent} {esc(c.get('sentiment_label',''))}  ⏱ {esc(c.get('time_horizon',''))}")
    return "\n".join(lines)


def build_sell_section(calls: List[Dict]) -> str:
    if not calls:
        return ""
    lines = ["", "🔴 <b>SELL / SHORT CALLS</b>"]
    for c in calls:
        cur  = c.get("currency", "USD")
        icon = conviction_icon(c["conviction"])
        sent = sentiment_icon(c.get("sentiment_label", "NEUTRAL"))
        flagged = " ⚠️" if c.get("sentiment_flagged") else ""
        vol  = "🔊" if c.get("vol_confirmed") else ""

        entry = fmt_price(c.get("entry_price"), cur)
        stop  = fmt_price(c.get("stop_loss"), cur)
        t1    = fmt_price(c.get("t1"), cur)
        rr    = f"{c.get('risk_reward',0):.1f}x"
        down  = fmt_pct(c.get("downside_pct"))

        lines.append(f"\n{icon} <b>{esc(c['ticker'])}</b> SHORT — {esc(c['conviction'])}{flagged} {vol}")
        lines.append(f"   Pattern: {esc(c.get('pattern','')[:30])}")
        lines.append(f"   Entry: <code>{entry}</code>  Stop: <code>{stop}</code>  R:R: <b>{rr}</b>")
        lines.append(f"   T1 ▼: <code>{t1}</code>  Downside: <b>{down}</b>")
        lines.append(f"   {sent} {esc(c.get('sentiment_label',''))}")
    return "\n".join(lines)


def build_smart_money_section(sm_data: Dict, tickers: List[str]) -> str:
    if not sm_data:
        return ""
    lines = ["", "🧠 <b>SMART MONEY</b>"]
    for ticker in tickers:
        d = sm_data.get("tickers", {}).get(ticker)
        if not d:
            continue
        overall  = d.get("overall", "NEUTRAL")
        ins_sig  = d["insiders"].get("signal", "—")
        hf_sig   = d["hedge_funds"].get("net_signal", "—")
        news_lbl = d["news"].get("sentiment_label", "NEUTRAL")

        overall_icon = {"BULLISH": "🟢", "BEARISH": "🔴", "MIXED": "🟡", "NEUTRAL": "⚪"}.get(overall, "⚪")
        ins_icon     = {"BUYING": "⬆️", "SELLING": "⬇️", "MIXED": "↔️", "NEUTRAL": "➖"}.get(ins_sig, "➖")
        hf_icon      = {"INCREASING": "⬆️", "DECREASING": "⬇️", "STABLE": "➖"}.get(hf_sig, "➖")

        lines.append(f"  {overall_icon} <b>{esc(ticker)}</b>  Ins:{ins_icon}{esc(ins_sig)}  HF:{hf_icon}{esc(hf_sig)}  News:{sentiment_icon(news_lbl)}")

        # Show top insider trade if any
        recent_ins = d["insiders"].get("recent", [])
        if recent_ins:
            r = recent_ins[0]
            lines.append(f"    └ {esc(r['name'][:25])} ({esc(r['role'][:20])}) {esc(r['direction'])} {r.get('shares',0):,} sh")

    return "\n".join(lines)


# ── Main sender ────────────────────────────────────────────────────────────────

def send_calls(include_smart_money: bool = False):
    cfg = load_config()
    token   = cfg["token"]
    chat_id = cfg["chat_id"]

    if not os.path.exists(CALLS_PATH):
        print(f"[ERROR] {CALLS_PATH} not found. Run python generate_calls.py first.")
        sys.exit(1)

    with open(CALLS_PATH, encoding="utf-8") as f:
        calls = json.load(f)

    lt = calls.get("long_term_calls", [])
    sw = calls.get("swing_calls", [])
    sl = calls.get("sell_calls", [])
    all_tickers = list({c["ticker"] for c in lt + sw + sl})

    # Smart money data (optional)
    sm_data = {}
    if include_smart_money and os.path.exists(SM_PATH):
        with open(SM_PATH, encoding="utf-8") as f:
            sm_data = json.load(f)

    # Build message blocks
    header    = build_header(calls)
    lt_block  = build_lt_section(lt)
    sw_block  = build_swing_section(sw)
    sl_block  = build_sell_section(sl)
    sm_block  = build_smart_money_section(sm_data, all_tickers) if include_smart_money else ""

    print(f"  Sending to Telegram (chat: {chat_id}) ...")

    # Message 1: header + long-term
    msg1 = header + (lt_block or "\n\n🏦 <b>LONG-TERM</b>\n  No calls generated.")
    send_long(token, chat_id, msg1)
    time.sleep(0.5)

    # Message 2: swing calls
    if sw_block:
        send_long(token, chat_id, sw_block)
        time.sleep(0.5)

    # Message 3: sell calls
    if sl_block:
        send_long(token, chat_id, sl_block)
        time.sleep(0.5)

    # Message 4: smart money
    if sm_block:
        send_long(token, chat_id, sm_block)

    print("  Done! Check your Telegram.")


def send_test(token: str = None, chat_id: str = None):
    if not token:
        cfg = load_config()
        token, chat_id = cfg["token"], cfg["chat_id"]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ok = send_message(token, chat_id, f"🤖 <b>StockCalls ping</b>\n{now}\n\nBot is alive ✅")
    print("Test sent!" if ok else "Test FAILED — check token/chat_id")


# ── Entry ──────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--setup",        action="store_true", help="Interactive setup wizard")
    p.add_argument("--test",         action="store_true", help="Send a test ping")
    p.add_argument("--smart-money",  action="store_true", help="Include smart money summary")
    return p.parse_args()


def main():
    args = parse_args()
    if args.setup:
        run_setup()
    elif args.test:
        send_test()
    else:
        send_calls(include_smart_money=args.smart_money)


if __name__ == "__main__":
    main()
