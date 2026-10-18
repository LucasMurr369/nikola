"""
Nikola engine — Multi-TimeFrame signal engine.

Faithful port of the live margin bot's MTF signal layer (live_margin_bot.py
lines 290-745). The bot's approach:

  4h  → trend gate  (MACD histogram + RSI)
  1h  → momentum   (RSI > 50 & MACD > 0 → LONG)
  30m → = 1h vote
  15m → entry window (volume imbalance + RSI)   [soft +5% confidence boost]
  5m  → = 15m vote
  1m  → = 5m vote

``synthesize_signal`` computes a **directional_count / total_count** agreement
score (e.g. "6/6 STRONG") and a confidence 0.30–0.85+ weighted by learned
``signal_weights.json``. ``filter_by_leader`` applies the three-leader-model
filter (BTC/ETH/XRP leader direction + BTC 1m cascade guard).

A module-level candle cache (``_CANDLES``) lets the engine run from in-memory
data (tests / mock) or from on-disk JSON files (production, populated by the
exchange refresh layer).
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Optional, Dict, List, Any, Tuple

from . import config as cfg
from . import indicators as ind
from .config import (
    SYMBOLS, MTF_TIMEFRAMES, TF_ORDER, MTF_CANDLE_LIMIT,
    LEADER_DIR_THRESHOLD, MEME_COINS, COIN_GROUPS, LEADERS,
    WEIGHT_MIN, WEIGHT_MAX,
)

log = logging.getLogger("Nikola.Signals")


# ---------------------------------------------------------------------------
# Candle store — in-memory cache that falls back to on-disk JSON
# ---------------------------------------------------------------------------
_CANDLES: Dict[Tuple[str, str], List[List]] = {}


def load_candles(pair: str, tf: str) -> List[List]:
    """Load [ts, o, h, l, c, v] candles for a pair/timeframe.

    Checks the in-memory cache first (populated by ``set_candles`` or the
    exchange refresh layer), then falls back to ``data/{pair_safe}_{tf}.json``.
    """
    key = (pair, tf)
    if key in _CANDLES:
        return _CANDLES[key][-cfg.MTF_CANDLE_LIMIT:]
    safe = pair.replace("/", "_")
    fn = cfg.DATA_DIR / f"{safe}_{tf}.json"
    if not fn.exists():
        return []
    try:
        with open(fn) as f:
            data = json.load(f)
        if isinstance(data, list):
            _CANDLES[key] = data
            return data[-cfg.MTF_CANDLE_LIMIT:]
        return []
    except Exception:
        return []


def set_candles(pair: str, tf: str, candles: List[List]) -> None:
    """Inject candles for testing / mock operation."""
    _CANDLES[(pair, tf)] = candles[-cfg.MTF_CANDLE_LIMIT:]


def ticker_to_candle(tk) -> list:
    """Convert a ccxt ticker to a candle row [ts, o, h, l, c, v]."""
    return [int(time.time() * 1000),
            float(tk.get("open", tk.get("close", 0))),
            float(tk.get("high", tk.get("close", 0))),
            float(tk.get("low", tk.get("close", 0))),
            float(tk["close"]), float(tk.get("volume", 0.0))]


def populate_candle_cache(exchange, pairs=None, timeframes=None):
    """Populate the in-memory candle cache (_CANDLES) from a real exchange.

    The MTF signal engine reads candles via load_candles(); this fills that
    cache from live Kraken OHLCV so paper mode runs on real-time data.
    """
    pairs = pairs or cfg.SYMBOLS
    timeframes = timeframes or cfg.MTF_TIMEFRAMES
    for pair in pairs:
        for tf in timeframes:
            try:
                ohlcv = exchange.fetch_ohlcv(pair, tf=tf,
                                             since=1789905600000, limit=cfg.MTF_CANDLE_LIMIT)
                if ohlcv and len(ohlcv) >= 30:
                    set_candles(pair, tf, ohlcv)
            except Exception as e:
                log.warning(f"  {pair} {tf}: refresh failed ({e})")


def clear_cache() -> None:
    """Clear the in-memory candle cache (forces file reload)."""
    _CANDLES.clear()


# ---------------------------------------------------------------------------
# Leader + meme helpers
# ---------------------------------------------------------------------------
def get_leader_direction(pair: str) -> Optional[str]:
    """Return leader direction (UP/DOWN/SIDEWAYS) from the leader's 1h candles."""
    base = pair.split("/")[0]
    leader = None
    for grp, coins in COIN_GROUPS.items():
        if base in coins:
            leader = grp
            break
    if leader is None:
        return None
    leader_pair = f"{leader}/USD"
    candles = load_candles(leader_pair, "1h")
    if len(candles) < 13:
        return None
    recent = float(candles[-1][4])
    prior = float(candles[-13][4])
    change = (recent - prior) / prior if prior != 0 else 0
    if change > LEADER_DIR_THRESHOLD:
        return "UP"
    elif change < -LEADER_DIR_THRESHOLD:
        return "DOWN"
    return "SIDEWAYS"


def get_meme_momentum(pair: str) -> float:
    """25-hour momentum of the meme pair (1h candles)."""
    candles = load_candles(pair, "1h")
    if len(candles) < 25:
        return 0.0
    recent = float(candles[-1][4])
    prior = float(candles[-25][4])
    return (recent - prior) / prior if prior != 0 else 0.0


def btc_1m_momentum(lookback: int = 15) -> float:
    """BTC ~15-min momentum from the 1m feed — the cascade detector.

    An active BTC cascade (< -4.0% over 15m) drags alts faster than their own signals
    flip. Returns % move over the last ``lookback`` 1m candles (default 15 = 15m).
    """
    candles = load_candles("BTC/USD", "1m")
    if len(candles) <= lookback:
        return 0.0
    recent = float(candles[-1][4])
    prior = float(candles[-1 - lookback][4])
    return (recent - prior) / prior if prior != 0 else 0.0


# ---------------------------------------------------------------------------
# Per-TF vote functions
# ---------------------------------------------------------------------------
def vote_4h(candles: List[List]) -> str:
    if len(candles) < 52:
        return "NEUTRAL"
    macd, signal, hist = ind.get_macd(candles)
    rsi = ind.get_rsi(candles)
    if macd is None or rsi is None:
        return "NEUTRAL"
    bullish = (hist > 0 or rsi > 45)
    bearish = (hist < 0 or rsi < 55)
    if bullish and not bearish:
        return "LONG"
    elif bearish and not bullish:
        return "SHORT"
    return "NEUTRAL"


def vote_1h(candles: List[List]) -> str:
    if len(candles) < 52:
        return "NEUTRAL"
    macd, signal, hist = ind.get_macd(candles)
    rsi = ind.get_rsi(candles)
    if macd is None or rsi is None:
        return "NEUTRAL"
    if rsi > 50 and macd > 0:
        return "LONG"
    elif rsi < 50 and macd < 0:
        return "SHORT"
    return "NEUTRAL"


def vote_15m(candles: List[List]) -> str:
    if len(candles) < 20:
        return "NEUTRAL"
    vi = ind.get_volume_imbalance(candles)
    rsi = ind.get_rsi(candles)
    if vi is None or rsi is None:
        return "NEUTRAL"
    if vi > 0.1 and rsi < 70:
        return "LONG"
    elif vi < -0.1 and rsi > 30:
        return "SHORT"
    return "NEUTRAL"


def vote_30m(candles: List[List]) -> str:
    return vote_1h(candles)

def vote_5m(candles: List[List]) -> str:
    return vote_15m(candles)

def vote_1m(candles: List[List]) -> str:
    # 2026-10-07: delegate to 5m logic (same MACD+RSI confluence, faster 1m data)
    return vote_5m(candles)

def vote_1d(candles: List[List]) -> str:
    return vote_4h(candles)


def get_market_regime() -> tuple:
    """Determine BTC market regime from 4h structure + 1h/30m/15m momentum consensus.

    4h: 200-bar ATR range (33 days) — wide range (ATR/price > 2.5%) = trending,
        tight range = choppy/range-bound.
    1h/30m/15m: MACD histogram + EMA20/EMA50 alignment consensus.
    A TF is "aligned" when both bullish (hist>0, ema20>ema50) or both bearish.

    Returns:
      (label, strength, trend_dir) — tuple of:
        label     : "CLEAR" | "STEADY" | "STRONG"
        strength  : float in [0.0, 1.0] — regime quality (NOT direction-adjusted)
        trend_dir : "LONG" | "SHORT" | "NEUTRAL" — from vote_4h(BTC)

      Direction-aware scaling is applied PER-SIGNAL in _deploy(), not here.
      This lets bear markets deploy full-strength SHORT signals while reducing
      opposing LONG signals. See nikola.py: _deploy() direction_multiplier.

      strength = (momentum_aligned + trending) / 3.0
      — CLEAR (0 aligned, no trend):  strength=0.00 → no new entries
      — STEADY  (1 aligned, no trend):  strength=0.33 → reduced deployment
      — STEADY  (1 aligned, trending):  strength=0.67 → moderate deployment
      — STRONG  (2+ aligned, trending): strength=1.00 → full deployment

      Adaptive (not capped): position count and size scale continuously
      with market quality × signal-direction alignment. No hard limits.
    """
    btc_4h = load_candles("BTC/USD", "4h")
    if len(btc_4h) < 200:
        return ("STEADY", 0.5, "NEUTRAL")
    atr = ind.get_atr(btc_4h, 200)
    if atr is None:
        return ("STEADY", 0.5, "NEUTRAL")
    avg_price = sum(float(c[4]) for c in btc_4h[-200:]) / 200.0
    range_pct = atr / avg_price if avg_price > 0 else 0.0
    trending = range_pct > 0.025  # 2.5%+ ATR = trending market

    momentum_aligned = 0
    for tf in ("1h", "30m", "15m"):
        candles = load_candles("BTC/USD", tf)
        if len(candles) < 52:
            continue
        macd, signal, hist = ind.get_macd(candles)
        ema20 = ind.get_ema(candles, 20)
        ema50 = ind.get_ema(candles, 50)
        if hist is None or ema20 is None or ema50 is None:
            continue
        macd_bull = hist > 0
        ema_bull = ema20 > ema50
        if macd_bull == ema_bull:  # both bullish or both bearish → aligned
            momentum_aligned += 1

    # Trend direction from 4h vote (LONG/SHORT/NEUTRAL).
    # Applied in _deploy() as a per-signal multiplier, NOT globally.
    trend_direction = vote_4h(btc_4h)

    if trending and momentum_aligned >= 2:
        strength = min(1.0, (momentum_aligned + 1.0) / 3.0)
        return ("STRONG", strength, trend_direction)
    elif momentum_aligned >= 1:
        strength = min(1.0, momentum_aligned / 3.0)
        if trending:
            strength = min(1.0, (momentum_aligned + 1.0) / 3.0)
        return ("STEADY", strength, trend_direction)
    else:
        return ("CLEAR", 0.0, trend_direction)


TF_VOTE_FUNCS: Dict[str, Any] = {
    "4h": vote_4h,
    "1h": vote_1h,
    "30m": vote_30m,
    "15m": vote_15m,
    "5m": vote_5m,
    "1m": vote_1m,
    "1d": vote_1d,
}


def compute_votes(pair: str) -> Dict[str, str]:
    """Vote every TF for a pair. Returns {tf: LONG|SHORT|NEUTRAL}."""
    votes: Dict[str, str] = {}
    for tf in TF_ORDER:
        candles = load_candles(pair, tf)
        if not candles:
            votes[tf] = "NEUTRAL"
            continue
        func = TF_VOTE_FUNCS[tf]
        votes[tf] = func(candles)
    return votes


# ---------------------------------------------------------------------------
# Signal synthesis — confluence scoring
# ---------------------------------------------------------------------------
def synthesize_signal(pair: str, votes: Dict[str, str],
                      signal_weights: Dict[str, Dict]) -> Dict[str, Any]:
    """Score a pair's MTF confluence → confidence 0.30–0.85+.

    Confidence tiers:
      6/6 all agree   → base 0.70 + 0.15 * (6/6) = 0.85  → STRONG
      2-5 agree       → base 0.50 + 0.20 * (n/6)        → MODERATE/WEAK
      0-1 agree       → base 0.30 + 0.20 * (n/6)        → WEAK
    Then × learned weight (signal_weights.json, clamped 0.5-1.5).
    15m entry-window agreement gives a soft +5% bump (no hard gate).
    """
    directional = {k: v for k, v in votes.items() if v != "NEUTRAL"}
    n_dir = len(directional)
    n_total = len(votes)

    longs = [tf for tf, v in directional.items() if v == "LONG"]
    shorts = [tf for tf, v in directional.items() if v == "SHORT"]

    if longs and shorts:
        return {"pair": pair, "composite_signal": None, "confidence": 0.0,
                "score": "0/0 CONFLICT", "votes": votes,
                "reasoning": f"CONFLICT: {len(longs)} LONG vs {len(shorts)} SHORT",
                "signal_type": "CONFLICT", "direction": None,
                "directional_count": 0, "total_count": n_total}
    if n_dir == 0:
        return {"pair": pair, "composite_signal": None, "confidence": 0.0,
                "score": "0/0 NO SIGNAL", "votes": votes,
                "reasoning": "All timeframes NEUTRAL",
                "signal_type": "NO_SIGNAL", "direction": None,
                "directional_count": 0, "total_count": n_total}
    if len(longs) > len(shorts):
        direction = "LONG"
    elif len(shorts) > len(longs):
        direction = "SHORT"
    elif len(longs) == len(shorts):
        return {"pair": pair, "composite_signal": None, "confidence": 0.0,
                "score": "0/0 CONFLICT", "votes": votes,
                "reasoning": "Tie between LONG and SHORT",
                "signal_type": "CONFLICT", "direction": None,
                "directional_count": 0, "total_count": n_total}

    if n_dir == n_total:
        base_conf = 0.70 + (0.15 * (n_dir / n_total))
    elif n_dir >= 2:
        base_conf = 0.50 + (0.20 * (n_dir / n_total))
    else:
        base_conf = 0.30 + (0.20 * (n_dir / n_total))

    signal_type = "-".join(f"{tf}-{votes[tf]}" for tf in TF_ORDER if votes[tf] != "NEUTRAL")
    if not signal_type:
        signal_type = "NO_SIGNAL"
    weight_entry = signal_weights.get(signal_type, {"weight": 1.0})
    weight = weight_entry.get("weight", 1.0)
    effective_conf = base_conf * weight
    # Soft 15m bump: if the 15m entry-window vote agrees with the composite direction
    if votes.get("15m") == direction:
        effective_conf *= 1.05

    score_label = (f"{n_dir}/{n_total} STRONG" if n_dir == n_total else
                   f"{n_dir}/{n_total} MODERATE" if n_dir >= 2 else
                   f"{n_dir}/{n_total} WEAK")
    reasoning_parts = []
    for tf in TF_ORDER:
        v = votes.get(tf, "NEUTRAL")
        if v != "NEUTRAL":
            label = {"4h": "(trend gate)", "1h": "(momentum)", "15m": "(entry window)",
                     "1d": "(long-term)"}.get(tf, "")
            reasoning_parts.append(f"{tf} {v} {label}".strip())
    reasoning = ", ".join(reasoning_parts) if reasoning_parts else "No directional votes"

    composite = "BUY" if direction == "LONG" else "SELL"
    return {"pair": pair, "composite_signal": composite,
            "confidence": round(effective_conf, 4),
            "base_confidence": round(base_conf, 4), "weight": weight,
            "score": score_label, "votes": votes, "reasoning": reasoning,
            "signal_type": signal_type, "direction": direction,
            "directional_count": n_dir, "total_count": n_total}


# ---------------------------------------------------------------------------
# Leader filter (three-leader model + BTC cascade guard)
# ---------------------------------------------------------------------------
def filter_by_leader(signal_info: Dict[str, Any], pair: str) -> Dict[str, Any]:
    """Apply three-leader-model + BTC cascade guard (deploy-side only)."""
    base = pair.split("/")[0]

    # BTC cascade guard: < -0.6% over 1m → deprioritize alts (soft 0.25x, never block)
    btc_short = btc_1m_momentum()
    if btc_short < -0.006:
        signal_info["confidence"] = float(signal_info.get("confidence", 0.0) or 0.0) * 0.25
        signal_info["reasoning"] = signal_info.get("reasoning", "") + \
            f" [BTC CASCADE {btc_short*100:.2f}% 1m — alt deprioritized]"

    if base in MEME_COINS:
        btc_dir = get_leader_direction(pair)
        mem_momentum = get_meme_momentum(pair)
        if btc_dir == "DOWN" and mem_momentum <= 0.01:
            signal_info["composite_signal"] = None
            signal_info["confidence"] = 0.0
            signal_info["reasoning"] = signal_info.get("reasoning", "") + \
                " [FILTERED: BTC DOWN + no MEME momentum]"
    elif base in COIN_GROUPS.get("BTC", []) or \
         base in COIN_GROUPS.get("ETH", []) or \
         base in COIN_GROUPS.get("XRP", []):
        leader = None
        if base in COIN_GROUPS.get("BTC", []):
            leader = "BTC"
        elif base in COIN_GROUPS.get("ETH", []):
            leader = "ETH"
        elif base in COIN_GROUPS.get("XRP", []):
            leader = "XRP"
        if leader:
            leader_dir = get_leader_direction(pair)
            if leader_dir == "UP" and signal_info.get("direction") == "SHORT":
                signal_info["composite_signal"] = None
                signal_info["confidence"] = 0.0
                signal_info["reasoning"] = signal_info.get("reasoning", "") + \
                    f" [FILTERED: {leader} UP, can't short]"
            elif leader_dir == "DOWN" and signal_info.get("direction") == "LONG" and leader != base:
                signal_info["composite_signal"] = None
                signal_info["confidence"] = 0.0
                signal_info["reasoning"] = signal_info.get("reasoning", "") + \
                    f" [FILTERED: {leader} DOWN, can't buy]"
    return signal_info



# ---------------------------------------------------------------------------
# Signal weights I/O (self-learning: ±WEIGHT_ADJUST, clamped WEIGHT_MIN..WEIGHT_MAX)
# ---------------------------------------------------------------------------
WEIGHTS_FILE = cfg.DATA_DIR / "signal_weights.json"
WEIGHT_ADJUST = 0.05


def load_signal_weights() -> Dict[str, Dict]:
    if WEIGHTS_FILE.exists():
        try:
            with open(WEIGHTS_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_signal_weights(weights: Dict[str, Dict]) -> None:
    WEIGHTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = WEIGHTS_FILE.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(weights, f, indent=2)
    os.replace(tmp, WEIGHTS_FILE)


def adjust_weight(signal_type: str, won: bool,
                  weights: Dict[str, Dict]) -> Dict[str, Dict]:
    if signal_type not in weights:
        weights[signal_type] = {
            "trades": 0, "wins": 0, "losses": 0,
            "win_rate": 0.0, "avg_pnl": 0.0, "avg_pnl_pct": 0.0,
            "weight": 1.0,
        }
    entry = weights[signal_type]
    entry["trades"] += 1
    if won:
        entry["wins"] += 1
        entry["weight"] = min(entry["weight"] + WEIGHT_ADJUST, WEIGHT_MAX)
    else:
        entry["losses"] += 1
        entry["weight"] = max(entry["weight"] - WEIGHT_ADJUST, WEIGHT_MIN)
    entry["win_rate"] = entry["wins"] / entry["trades"] if entry["trades"] > 0 else 0.0
    return weights


# ---------------------------------------------------------------------------
# Engine class — ties it all together
# ---------------------------------------------------------------------------
class MTFEngine:
    """Compute, score, and rank MTF signals for the 28-pair universe.

    Usage:
        eng = MTFEngine(signal_weights={})
        sigs = eng.compute_all_signals()
        ranked = eng.rank_candidates(sigs)
        top = eng.find_best_signals(sigs, n=5, held=set(), cooldowns={})
    """

    def __init__(self, signal_weights: Optional[Dict[str, Dict]] = None, paper_sim: bool = False):
        self.signal_weights = signal_weights if signal_weights is not None else load_signal_weights()
        self.paper_sim = paper_sim

    def compute_all_signals(self) -> List[Dict[str, Any]]:
        """Score every pair: votes → synthesize → filter_by_leader."""
        all_signals: List[Dict] = []
        for pair in SYMBOLS:
            votes = compute_votes(pair)
            sig = synthesize_signal(pair, votes, self.signal_weights)
            sig = filter_by_leader(sig, pair)
            if sig.get("directional_count", 0) < cfg.MIN_TF_AGREE_DEPLOY:
                sig["composite_signal"] = None
                sig["confidence"] = 0.0
                sig["score"] = f"0/0 REJECTED (<{cfg.MIN_TF_AGREE_DEPLOY} TF agree)"
            if sig.get("composite_signal") is not None:
                candles_1h = load_candles(pair, "1h")
                if candles_1h:
                    sig["current_price"] = float(candles_1h[-1][4])
                else:
                    sig["current_price"] = 0.0
            all_signals.append(sig)
        return all_signals

    def rank_candidates(self, signals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Rank actionable signals by confidence × weight + small XP boost.

        Soft preference only: new/unproven STRONG setups still qualify, they
        just start lower until they prove themselves (>=5 trades, win>50%).
        """
        cands: List[Dict] = []
        for s in signals:
            # DEBUG: dump ALL candidates with composite_signal != None (user audit override)
            if s.get("composite_signal") is not None:
                print(f"[CANDIDATE] {s.get('pair','?'):12s} dir={s.get('direction','?'):4s} conf={s.get('confidence',0):.4f} score={s.get('score','?')}", flush=True)
            if s.get("composite_signal") is None or s.get("confidence", 0) < cfg.ENTRY_MIN_CONFIDENCE:
                continue
            st = s.get("signal_type", "UNKNOWN")
            w = self.signal_weights.get(st, {}) or {}
            trades = int(w.get("trades", 0) or 0)
            win_rate = float(w.get("win_rate", 0) or 0)
            weight = float(w.get("weight", 1.0) or 1.0)
            boost = 0.02 if (trades >= 5 and win_rate > 0.5 and weight >= 1.0) else 0.0
            # LIVE only: do not deploy on signal types proven to lose
            # (weight down-weighted AND a real sample showing no wins).
            if not self.paper_sim and trades >= 3 and weight < 1.0 and win_rate <= 0.0:
                continue
            c = dict(s)
            c["rank_score"] = round(float(s.get("confidence", 0)) + boost, 4)
            c["xp_boost"] = boost
            cands.append(c)
        cands.sort(key=lambda c: c["rank_score"], reverse=True)
        return cands

    def find_best_signals(self, signals: Optional[List[Dict]] = None,
                           n: int = 5, held: Optional[set] = None,
                           cooldowns: Optional[Dict[str, float]] = None) -> List[Dict]:
        """Top-N deployable signals (excludes held pairs + cooldown)."""
        if signals is None:
            signals = self.compute_all_signals()
        ranked = self.rank_candidates(signals)
        held = held or set()
        cooldowns = cooldowns or {}
        now = time.time()
        result: List[Dict] = []
        for c in ranked:
            pair = c["pair"]
            if pair in held:
                print(f"[FBS-REJECT] {pair}: already held (skip)", flush=True)
                continue
            if now - cooldowns.get(pair, 0) < cfg.REENTRY_COOLDOWN_SEC:
                print(f"[FBS-REJECT] {pair}: on cooldown (skip)", flush=True)
                continue
            result.append(c)
            if len(result) >= n:
                break
        return result
