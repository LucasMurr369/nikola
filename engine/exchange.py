"""
Nikola engine — Exchange layer.

Ports the bot's CCXT Kraken BTNL-margin wrapper (make_exchange, place_entry,
place_sl, place_tp, compute_real_free_margin from live_margin_bot.py
lines 928-1075) **plus** the order-book depth and live 1m price feed that the
user identified as still needed.

A ``PaperExchange`` simulator mirrors the same CCXT-shaped interface so the
daemon code is identical in paper and live mode — paper mode just swaps the
backend.  The paper simulator is seeded from candle data and fills orders at the
book mid ± a slippage model, so it exercises the *real* entry/exit pipeline
without touching Kraken.

Components
----------
- ``make_exchange``         — CCXT Kraken with BTNL market registration
- ``place_entry`` / ``place_sl`` / ``place_tp`` — order primitives (DRY_RUN-aware)
- ``fetch_order_book``      — depth chart (limit-N bids/asks)
- ``compute_real_free_margin`` — free margin after BTNL position margin
- ``LivePriceFeed``         — 1m price deque per pair + EMA/RSI/ATR (bot lines 1300-1357)
- ``PaperExchange``         — zero-write Kraken simulator for paper mode
- ``ExchangeManager``       — holds live or paper backend + price feed
"""
from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from collections import deque, defaultdict
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any, Tuple

from . import config as cfg
from .config import (
    SYMBOLS, PAIR_LEVERAGE, PREFERRED_LEVERAGE, SL_LIMIT_BAND_PCT,
    normalize_btln_symbol, min_base_for, round_amount,
    MTF_TIMEFRAMES, MTF_CANDLE_LIMIT,
)
from . import indicators as ind
from .signals import load_candles, set_candles

log = logging.getLogger("Nikola.Exchange")

# ---------------------------------------------------------------------------
# Order primitives (ported from live_margin_bot.py 928-997)
# ---------------------------------------------------------------------------
# DRY_RUN is env-var driven from config.py. --live in nikola.py sys.argv sets
# NIKOLA_DRY_RUN=false BEFORE this import fires. Override anytime with:
#   NIKOLA_DRY_RUN=true python nikola.py --live   → safe (simulation)
#   NIKOLA_DRY_RUN=false python nikola.py --live  → LIVE (real orders)
from .config import DRY_RUN


def place_entry(exchange, symbol: str, side: str, amount: float,
                price: float, leverage: int, order_type: str = "limit") -> Optional[Dict]:
    """Place an entry order (BTNL margin). ALWAYS LIMIT — no market orders."""
    if DRY_RUN:
        log.info(f"  [DRY_RUN] WOULD enter {side} {amount} {symbol} @ {price} (lev {leverage}, limit)")
        return {"id": f"dry_{int(time.time())}", "symbol": symbol, "side": side,
                "amount": amount, "price": price, "leverage": leverage, "status": "dry_run"}
    try:
        order = exchange.create_order(
            symbol=symbol, type="limit", side=side, amount=amount,
            price=price, params={"leverage": leverage},
        )
        log.info(f"  ENTRY: {side} {amount} {symbol} @ {price} (lev {leverage}) — {order.get('id')}")
        return order
    except Exception as e:
        log.error(f"  ENTRY FAILED: {e}")
        return None


def place_sl(exchange, symbol: str, side: str, amount: float,
             stop_price: float, leverage: int) -> Optional[Dict]:
    """Place a REAL stop-loss-limit order (trigger at stop_price, limit band beyond).

    FIX 2026-10-04: previously a plain limit SELL below market — instantly
    marketable and dumped the position. A stop-loss-limit rests until triggered.
    """
    close_side = "sell" if side == "buy" else "buy"
    limit_price = stop_price * (1 - SL_LIMIT_BAND_PCT) if close_side == "sell" \
        else stop_price * (1 + SL_LIMIT_BAND_PCT)
    if DRY_RUN:
        return {"id": f"sl_dry_{int(time.time())}", "symbol": symbol, "side": close_side,
                "amount": amount, "price": limit_price, "stopPrice": stop_price,
                "leverage": leverage, "reduceOnly": True, "status": "dry_run"}
    for attempt in range(3):
        try:
            order = exchange.create_order(
                symbol=symbol, type="limit", side=close_side, amount=amount,
                price=limit_price,
                params={"leverage": leverage, "reduceOnly": True,
                        "stopLossPrice": stop_price, "trigger": "index"},
            )
            log.info(f"  SL(stop-loss-limit): {close_side} {amount} {symbol} "
                     f"trigger={stop_price} limit={limit_price:.5f} — {order.get('id')}")
            return order
        except Exception as e:
            err = str(e).lower()
            if ('nonce' in err or 'timeout' in err or 'connection' in err) and attempt < 2:
                _jump_nonce()
                time.sleep(0.5)
                continue
            log.error(f"  SL FAILED: {e}")
            return None
    log.error(f"  SL FAILED: nonce/timeout after 3 retries")
    return None


def place_tp(exchange, symbol: str, side: str, amount: float,
             tp_price: float, leverage: int) -> Optional[Dict]:
    """Place a reduce-only limit take-profit.

    Cancels any existing same-price reduce-only TP on the pair first
    (idempotency guard against double-close when both _verify re-placement
    and _place_live_exit fire in the same light cycle).
    """
    close_side = "sell" if side == "buy" else "buy"
    if DRY_RUN:
        return {"id": f"tp_dry_{int(time.time())}", "symbol": symbol, "side": close_side,
                "amount": amount, "price": tp_price, "leverage": leverage,
                "reduceOnly": True, "status": "dry_run"}
    # Idempotency: cancel exact-duplicate TP at same price (reduce-only limit,
    # same close side) so we never leave two copies of the same rung.
    _base = normalize_btln_symbol(symbol)
    try:
        for o in exchange.fetch_open_orders():
            osym = normalize_btln_symbol(o.get("symbol", ""))
            if osym != _base:
                continue
            if (o.get("type") != "limit" or o.get("side") != close_side
                    or not o.get("reduceOnly", False)):
                continue
            oprice = float(o.get("price", 0) or o.get("average", 0) or 0)
            if abs(oprice - tp_price) < 1e-9:
                try:
                    exchange.cancel_order(o.get("id"), symbol)
                    log.info(f"  TP dedup: cancelled duplicate at {tp_price} for {symbol}")
                except Exception:
                    pass
    except Exception:
        pass
    for attempt in range(3):
        try:
            order = exchange.create_order(
                symbol=symbol, type="limit", side=close_side, amount=amount,
                price=tp_price,
                params={"leverage": leverage, "reduceOnly": True},
            )
            log.info(f"  TP: {close_side} {amount} {symbol} @ {tp_price} — {order.get('id')}")
            return order
        except Exception as e:
            err = str(e).lower()
            if 'cannot increase position' in err:
                # Position was already reduced by a TP limit fill the bot
                # didn't observe (e.g. TP1/TP2 filled while price feed was
                # frozen, or filled during recovery). Return a sentinel so
                # callers can mark the TP as filled instead of churning.
                log.info(f"  TP for {symbol} @ {tp_price} — "
                         f"position already reduced (TP likely filled on exch)")
                return {"id": "", "symbol": symbol, "side": close_side,
                        "status": "already_filled", "price": tp_price,
                        "reduceOnly": True}
            if ('nonce' in err or 'timeout' in err or 'connection' in err) and attempt < 2:
                _jump_nonce()
                time.sleep(0.5)
                continue
            log.error(f"  TP FAILED: {e}")
            return None
    log.error(f"  TP FAILED: nonce/timeout after 3 retries")
    return None


# ---------------------------------------------------------------------------
# Order book / depth chart
# ---------------------------------------------------------------------------
def fetch_order_book(exchange, symbol: str, limit: int = 5) -> Dict[str, List]:
    """Fetch the order book depth (bids/asks) for a symbol.

    Returns {'bids': [[price, size], ...], 'asks': [[price, size], ...],
             'timestamp': ..., 'datetime': ...}
    The bot uses limit=5 (book mid) in deploy_signal to avoid stale ticker.Last.
    """
    if hasattr(exchange, 'fetch_order_book'):
        return exchange.fetch_order_book(symbol, limit=limit)
    return {"bids": [], "asks": [], "timestamp": time.time()}


def depth_chart_text(book: Dict[str, List], levels: int = 5) -> str:
    """Format an order book as an ASCII-style depth chart for terminal display.

       ASK  103.45  0.42    │ BID  103.40  0.38
       ASK  103.46  0.21    │ BID  103.39  0.55
       ...                       ...
    """
    import datetime as _dt
    bids = sorted(book.get("bids", []), key=lambda x: x[0], reverse=True)[:levels]
    asks = sorted(book.get("asks", []), key=lambda x: x[0])[:levels]
    lines = []
    for i in range(levels):
        ask = asks[i] if i < len(asks) else (0, 0)
        bid = bids[i] if i < len(bids) else (0, 0)
        a_px, a_sz = (float(ask[0]), float(ask[1])) if ask else (0, 0)
        b_px, b_sz = (float(bid[0]), float(bid[1])) if bid else (0, 0)
        lines.append(f"  ASK  {a_px:>10.5f}  {a_sz:<8.4f}  │  BID  {b_px:>10.5f}  {b_sz:<8.4f}")
    spread = (asks[0][0] - bids[0][0]) if asks and bids else 0
    lines.append(f"  {'':>20}  {'':<8}  │  {'':>20}  {'':<8}")
    bp = bids[0][0] if bids else 1.0
    spread_pct = (spread / bp * 100) if bp else 0
    lines.append(f"  Spread: {spread:.5f}  ({spread_pct:.3f}%)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Persisted nonce — prevents EAPI:Invalid nonce across process restarts
# ---------------------------------------------------------------------------
_NONCE_FILE = os.path.join(os.path.dirname(__file__), 'nonce_state.json')
# WHY TWO buffers: a co-tenant process (or this bot after a SIGKILL restart) may
# already have pushed Kraken's "next nonce" ceiling past wall-clock time.
# NONCE_AHEAD_MS keeps every normal request comfortably above wall-clock so we
# never collide with a plain ms-time writer; NONCE_JUMP_MS is the recovery jump
# used on an InvalidNonce error to leap PAST any ceiling we've fallen behind.
# The nonce MUST be strictly monotonically increasing, so once we're ahead we
# only ever +1 from there.
NONCE_AHEAD_MS = 60_000_000   # every call stays >= 60M ahead of wall clock (above Kraken's +50M ceiling)
NONCE_JUMP_MS = 300_000_000   # on error, jump 300M ahead to recover past any ceiling
_nonce_state = int(time.time() * 1000) + NONCE_AHEAD_MS
_nonce_lock = threading.Lock()  # thread-safe nonce to prevent price-feed/light-cycle races

print(f"[DEBUG-NONCE] exchange.py loaded — NONCE_AHEAD_MS={NONCE_AHEAD_MS}, NONCE_JUMP_MS={NONCE_JUMP_MS}", flush=True)

def _load_nonce():
    global _nonce_state
    try:
        with open(_NONCE_FILE, 'r') as f:
            loaded = int(json.load(f).get('nonce', 0))
    except Exception:
        loaded = 0
    now_ms = int(time.time() * 1000)
    _nonce_state = max(loaded, now_ms + NONCE_AHEAD_MS)
    print(f"[DEBUG-NONCE] _load_nonce: loaded={loaded}, now={now_ms}, now+60M={now_ms+NONCE_AHEAD_MS}, state={_nonce_state}", flush=True)

def _persisted_nonce():
    """Monotonically increasing nonce that survives process restarts.

    Kraken requires nonce strictly greater than any previously used. The value
    is kept >= wall-clock + NONCE_AHEAD_MS (so it always beats a co-tenant
    ms-time writer) and strictly increasing (max with last+1), so it can NEVER
    reset backward after a _jump_nonce burst. (The old `if now > state:
    state=now` reset, combined with the `+60000` recovery below, could step
    backward into a nonce Kraken had already accepted and re-trigger the
    InvalidNonce cascade.)

    Thread-safe: the price-feed and light-cycle paths may call this
    concurrently without nonce collisions.
    """
    global _nonce_state
    with _nonce_lock:
        now = int(time.time() * 1000)
        _nonce_state = max(_nonce_state + 1, now + NONCE_AHEAD_MS)
        nonce_val = _nonce_state
    # File write outside the lock (best-effort persistence for crash recovery)
    try:
        with open(_NONCE_FILE, 'w') as f:
            json.dump({'nonce': nonce_val}, f)
            os.fsync(f.fileno())
    except Exception:
        pass
    return nonce_val

def _jump_nonce() -> int:
    """Jump the persisted nonce past Kraken's seen value (recovery on nonce errors).

    Uses max() so it can only ever move FORWARD — never backward into a value
    Kraken has already accepted (the previous `now + 120000` could overwrite a
    higher in-flight value and re-invent a collision). Persisted to survive a
    crash. Returns the new nonce ceiling.
    """
    global _nonce_state
    with _nonce_lock:
        _nonce_state = max(_nonce_state + 1, int(time.time() * 1000) + NONCE_JUMP_MS)
        nonce_val = _nonce_state
    try:
        with open(_NONCE_FILE, 'w') as f:
            json.dump({'nonce': nonce_val}, f)
            os.fsync(f.fileno())
    except Exception:
        pass
    return nonce_val

_load_nonce()

# ---------------------------------------------------------------------------
# CCXT wrapper (ported from live_margin_bot.py lines 1003-1042)
# ---------------------------------------------------------------------------
def make_exchange(api_key: str, api_secret: str):
    """CCXT Kraken with BTNL leveraged-token market registration.

    Derives BTNL market metadata from the real spot market so price precision
    is correct (the old hardcoded 0.0001 made Kraken reject ETH/SOL entries).
    """
    import ccxt
    exchange = ccxt.kraken({
        "apiKey": api_key,
        "secret": api_secret,
        "enableRateLimit": True,
        "rateLimit": 300,   # SPEED 2026-10-05: 1000ms over-throttles this call volume
        "timeout": 10000,   # 10s — prevents light-cycle stalls on slow API responses
        "options": {"defaultType": "margin"},
    })
    exchange.load_markets()
    exchange.nonce = _persisted_nonce  # FIX: prevent EAPI:Invalid nonce across restarts
    # Startup nonce validation — recover from a stale file after a SIGKILL restart.
    try:
        exchange.fetch_balance()
    except Exception as ne:
        if 'nonce' in str(ne).lower():
            new = _jump_nonce()
            print(f"[nonce-fix] InvalidNonce on startup — nonce jumped to {new}")
            try:
                exchange.fetch_balance()
            except Exception:
                pass
    for pair in SYMBOLS:
        btnl_symbol = f"{pair}:BTNL"
        if btnl_symbol not in exchange.markets:
            base, quote = pair.split("/")
            spot = exchange.markets.get(pair) or {}
            spot_prec = spot.get("precision") or {}
            spot_limits = spot.get("limits") or {}
            amt_prec = spot_prec.get("amount") or 1e-08
            px_prec = spot_prec.get("price") or 0.0001
            amt_min = (spot_limits.get("amount") or {}).get("min") or min_base_for(pair)
            exchange.markets[btnl_symbol] = {
                "id": btnl_symbol, "symbol": btnl_symbol,
                "base": base, "quote": quote, "type": "margin",
                "classic": True, "spot": False, "contract": False,
                "fungible": True,
                "limits": {"amount": {"min": amt_min, "max": 100000000.0},
                           "price": {"min": 0.00000001, "max": 100000000.0},
                           "cost": {"min": 0.01, "max": 100000000.0}},
                "precision": {"amount": amt_prec, "price": px_prec},
                "info": {},
            }
    return exchange


def compute_real_free_margin(balance: Dict, positions: List[Dict]) -> Tuple[float, float]:
    """Free USD after subtracting BTNL position margin. (ported line 1066)"""
    usd_free = float(balance.get("USD", {}).get("free", 0) or 0)
    total_used = 0.0
    for p in positions:
        sym = p.get("symbol", "")
        if ":BTNL" in sym:
            im = (p.get("initialMargin") or p.get("initial_margin") or
                  p.get("margin", 0) or 0)
            total_used += float(im)
    return max(usd_free - total_used, 0.0), total_used


# ---------------------------------------------------------------------------
# Live-price backend for PAPER mode (real-time Kraken, DRY_RUN orders)
# ---------------------------------------------------------------------------
class RealKraken:
    """Live CCXT Kraken read backend for paper mode.

    Real-time ticker/ohlcv/order-book via public Kraken spot endpoints, while
    keeping ALL order placement DRY_RUN (simulated, no real money, no real
    positions, no API secrets needed).
    """

    def __init__(self, api_key: str = "", api_secret: str = ""):
        import ccxt
        self._ex = ccxt.kraken({
            "apiKey": api_key or "",
            "secret": api_secret or "",
            "enableRateLimit": True,
            "rateLimit": 300,
            "timeout": 10000,
            "options": {"defaultType": "spot"},
        })
        self._ex.load_markets()

    def fetch_ticker(self, symbol: str) -> Dict:
        if symbol.endswith(":BTNL"):
            symbol = symbol[:-5]
        return self._ex.fetch_ticker(symbol)

    def fetch_order_book(self, symbol: str, limit: int = 5) -> Dict:
        if symbol.endswith(":BTNL"):
            symbol = symbol[:-5]
        return self._ex.fetch_order_book(symbol, limit=limit)

    def fetch_ohlcv(self, symbol: str, timeframe: str = "1m",
                    since=None, limit=None) -> List:
        if symbol.endswith(":BTNL"):
            symbol = symbol[:-5]
        return self._ex.fetch_ohlcv(symbol, timeframe=timeframe,
                                     since=since, limit=limit)

    def create_order(self, symbol: str, type: str = "limit",
                     side: str = "buy", amount: float = 0,
                     price: float = None, params: Dict = None) -> Dict:
        if DRY_RUN:
            log.info(f"  [DRY_RUN-real] WOULD {side} {amount} {symbol} "
                     f"@ {price:.5f}")
            return {"id": f"dryreal_{int(time.time())}", "symbol": symbol,
                    "side": side, "amount": amount, "price": price,
                    "leverage": params.get("leverage", PREFERRED_LEVERAGE),
                    "status": "dry_run",
                    "reduceOnly": params.get("reduceOnly", False)}
        return self._ex.create_order(symbol, type, side, amount, price, params)


# ---------------------------------------------------------------------------
# Live 1m price feed (ported from LiveMarginBot 1300-1357)
# ---------------------------------------------------------------------------
class LivePriceFeed:
    """1m price history per pair + streaming EMA/RSI/ATR.

    Used for BTC cascade detection (btc_1m_momentum) and the live price tick
    that feeds the state machine between full scans.
    """

    def __init__(self, pairs: List[str] = None):
        self.pairs = pairs or SYMBOLS
        self._prices: Dict[str, deque] = defaultdict(lambda: deque(maxlen=250))
        self._last_update: Dict[str, float] = {}

    def seed_from_exchange(self, exchange) -> None:
        """Seed 1m history from exchange OHLCV (since 2026-09-20, bot line 1300)."""
        since_ms = 1789905600000  # 2026-09-20 12:00 UTC
        for symbol in self.pairs:
            try:
                ohlcv = exchange.fetch_ohlcv(symbol, timeframe="1m", since=since_ms, limit=300)
                if not ohlcv or len(ohlcv) < 30:
                    ticker = exchange.fetch_ticker(symbol)
                    self._prices[symbol].append(float(ticker["last"]))
                    continue
                prices = [c[4] for c in ohlcv]
                self._prices[symbol].extend(float(p) for p in prices[-250:])
                log.info(f"  Seeded {symbol}: {len(ohlcv)} candles")
            except Exception as e:
                log.warning(f"  {symbol}: seeding failed ({e})")

    def seed_from_candles(self, pair: str, tf: str = "1m") -> None:
        """Seed the 1m feed from on-disk candle files (no exchange needed)."""
        candles = load_candles(pair, tf)
        if candles:
            self._prices[pair].extend(float(c[4]) for c in candles[-250:])

    def update_price(self, symbol: str, price: float) -> None:
        """Append a live tick to the 1m price history."""
        self._prices[symbol].append(price)
        self._last_update[symbol] = time.time()

    def prices(self, symbol: str) -> List[float]:
        return list(self._prices[symbol])

    def ema(self, symbol: str, period: int) -> Optional[float]:
        prices = self.prices(symbol)
        if len(prices) < period:
            return None
        k = 2.0 / (period + 1.0)
        ema = prices[0]
        for p in prices[1:]:
            ema = p * k + ema * (1 - k)
        return ema

    def rsi(self, symbol: str, period: int = 14) -> Optional[float]:
        prices = self.prices(symbol)
        if len(prices) < period + 1:
            return None
        gains, losses = [], []
        for i in range(1, len(prices)):
            diff = prices[i] - prices[i - 1]
            gains.append(max(diff, 0))
            losses.append(max(-diff, 0))
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:])
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def atr(self, symbol: str, period: int = 14) -> Optional[float]:
        """ATR from the on-disk candle store (more accurate than price-only)."""
        candles = load_candles(symbol, "1h")
        if candles:
            return ind.get_atr(candles, period)
        return None


# ---------------------------------------------------------------------------
# PaperExchange — zero-write Kraken BTNL simulator
# ---------------------------------------------------------------------------
class PaperExchange:
    """Mirrors the CCXT Kraken margin interface with simulated fills.

    Seeds its synthetic order book from candle data. Orders fill at the
    book mid ± slippage. SL/TP are tracked as conditional orders and settled
    on each ``tick`` against the current price.
    """

    SLIPPAGE_PCT = 0.0005  # 0.05% round-turn slippage

    def __init__(self, cash_usd: float = 300.0):
        self.cash_usd = cash_usd
        self.initial_cash = cash_usd
        self.positions: Dict[str, Dict] = {}      # margin_symbol → pos
        self.orders: Dict[str, Dict] = {}         # order_id → order
        self.order_id_seq = 0
        self.markets: Dict[str, Dict] = {}
        self._seed_markets()

    def _seed_markets(self) -> None:
        for pair in SYMBOLS:
            self.markets[pair] = {"precision": {"amount": 8, "price": 5}}
            self.markets[f"{pair}:BTNL"] = {"precision": {"amount": 8, "price": 5}}

    # -- synthetic book from candles --
    def _book_for(self, margin_symbol: str) -> Dict:
        """Synthesize a 5-level order book from the latest 1h candle close."""
        pair = normalize_btln_symbol(margin_symbol).replace(":BTNL", "")
        candles = load_candles(pair, "1h")
        if not candles:
            return {"bids": [], "asks": [], "timestamp": time.time()}
        last = float(candles[-1][4])
        spread = last * 0.0003
        levels = []
        for i in range(5):
            px = last + (spread * (i + 1) / 2)
            levels.append([round(px, 5), round(0.5 + i * 0.3, 4)])
        bids = [[last - spread * (i + 1) / 2, round(0.5 + i * 0.3, 4)]
                for i in range(5)]
        asks = [[last + spread * (i + 1) / 2, round(0.5 + i * 0.3, 4)]
                for i in range(5)]
        return {"bids": bids, "asks": asks, "timestamp": time.time()}

    def _mid(self, margin_symbol: str) -> float:
        book = self._book_for(margin_symbol)
        if book["bids"] and book["asks"]:
            return (book["bids"][0][0] + book["asks"][0][0]) / 2.0
        return 0.0

    # -- CCXT-shaped interface --
    def fetch_ticker(self, symbol: str) -> Dict:
        mid = self._mid(symbol)
        return {"last": mid, "bid": mid * 0.9999, "ask": mid * 1.0001,
                "timestamp": time.time(), "datetime": datetime_iso()}

    def fetch_order_book(self, symbol: str, limit: int = 5) -> Dict:
        return self._book_for(symbol)

    def fetch_ohlcv(self, symbol: str, timeframe: str = "1m",
                    since: int = None, limit: int = 200) -> List[List]:
        pair = symbol.replace(":BTNL", "")
        return load_candles(pair, timeframe)

    def fetch_tickers(self, symbols: List[str]) -> Dict[str, Dict]:
        return {s: self.fetch_ticker(s) for s in symbols}

    def create_order(self, symbol: str, type: str = "limit", side: str = "buy",
                     amount: float = 0, price: float = None,
                     params: Dict = None) -> Dict:
        """Place an order. Immediate-or-cancel limit at the given price.

        Reduces position for reduceOnly orders; increases for entry orders.
        """
        params = params or {}
        self.order_id_seq += 1
        oid = f"paper_{self.order_id_seq:06d}"
        mid = self._mid(symbol)
        if price is None:
            price = mid

        order = {
            "id": oid, "symbol": symbol, "type": type, "side": side,
            "amount": amount, "price": price, "filled": amount,
            "remaining": 0.0, "status": "closed",
            "average": price, "reduceOnly": params.get("reduceOnly", False),
            "leverage": params.get("leverage", PREFERRED_LEVERAGE),
            "timestamp": time.time(),
        }
        # If it's a reduce-only close, apply immediately
        if params.get("reduceOnly"):
            self._apply_close(order)

        self.orders[oid] = order
        return order

    def _apply_close(self, order: Dict) -> None:
        """Immediately close the matched position portion for a reduce-only order."""
        symbol = order["symbol"]
        pair = normalize_btln_symbol(symbol).replace(":BTNL", "")
        pos = self.positions.get(symbol)
        if not pos:
            return
        close_side = "sell" if pos["direction"] == "LONG" else "buy"
        filled = min(order["amount"], abs(pos["base_amount"]))
        if filled <= 0:
            return
        exit_price = order["price"]
        entry = pos["entry_price"]
        if pos["direction"] == "LONG":
            pnl = (exit_price - entry) * filled
        else:
            pnl = (entry - exit_price) * filled
        pos["base_amount"] -= filled * (1 if pos["direction"] == "LONG" else -1)
        pos["cash_returned"] = pos.get("cash_returned", 0) + exit_price * filled
        pnl -= abs(pnl) * 0.0018  # round-trip fee
        self.cash_usd += exit_price * filled + pnl
        # Mark position closed if fully exited
        if abs(pos["base_amount"]) < 1e-9:
            pos["status"] = "closed"
            pos["exit_price"] = exit_price
            pos["realized_pnl"] = pnl
        order["realized_pnl"] = pnl

    def fetch_positions(self) -> List[Dict]:
        return [dict(p) for p in self.positions.values() if p.get("status") != "closed"]

    def fetch_balance(self) -> Dict:
        used = sum(p.get("margin_deployed", 0) for p in self.positions.values()
                   if p.get("status") != "closed")
        return {"USD": {"free": max(self.cash_usd - used, 0), "used": used,
                        "total": self.cash_usd}}

    def fetch_open_orders(self, symbol: Optional[str] = None) -> List[Dict]:
        result = [dict(o) for o in self.orders.values() if o["status"] == "open"]
        if symbol:
            result = [o for o in result if o["symbol"] == symbol]
        return result

    def cancel_order(self, order_id: str, symbol: str) -> Dict:
        o = self.orders.pop(order_id, None)
        if o:
            o["status"] = "canceled"
            return o
        return {}

    def load_markets(self) -> Dict:
        return self.markets

    # -- paper state helpers --
    def open_position(self, symbol: str, direction: str, entry_price: float,
                      base_amount: float, leverage: int) -> Dict:
        margin = (entry_price * base_amount) / leverage
        pos = {
            "symbol": symbol, "pair": symbol.replace(":BTNL", ""),
            "direction": direction, "entry_price": entry_price,
            "base_amount": base_amount, "leverage": leverage,
            "margin_deployed": margin, "status": "open",
            "open_time": datetime_iso(), "cash_returned": 0,
        }
        self.positions[symbol] = pos
        self.cash_usd -= margin
        return pos

    def get_free_margin(self) -> float:
        bal = self.fetch_balance()
        return bal["USD"]["free"]


def datetime_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# ExchangeManager — unifies live (CCXT) and paper (PaperExchange) + price feed
# ---------------------------------------------------------------------------
class ExchangeManager:
    """Holds either a live CCXT exchange or a PaperExchange, plus a LivePriceFeed."""

    def __init__(self, api_key: str = "", api_secret: str = "",
                 paper: bool = True, cash_usd: float = 300.0):
        self.paper = paper
        self.feed = LivePriceFeed()
        self.cash_usd = cash_usd
        if paper:
            self.exchange = RealKraken(api_key=api_key, api_secret=api_secret)
            self.seed_price_history()
        else:
            self.exchange = make_exchange(api_key, api_secret)

    @property
    def is_paper(self) -> bool:
        return self.paper

    def fetch_ticker(self, symbol: str) -> Dict:
        # Strip :BTNL suffix — Kraken returns last=0 for the synthetic BTNL
        # market (make_exchange registers it with info={}). Route to the
        # underlying spot market for a live last price.
        if symbol.endswith(":BTNL"):
            symbol = symbol[:-5]
        return self.exchange.fetch_ticker(symbol)

    def fetch_order_book(self, symbol: str, limit: int = 5) -> Dict:
        return self.exchange.fetch_order_book(symbol, limit=limit)

    def fetch_ohlcv(self, symbol: str, timeframe: str, since=None, limit=None) -> List[List]:
        return self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=limit)

    def create_order(self, symbol: str, **kwargs) -> Dict:
        return self.exchange.create_order(symbol, **kwargs)

    def fetch_balance(self) -> Dict:
        return self.exchange.fetch_balance()

    def fetch_positions(self) -> list:
        if self.paper:
            return []
        return self.exchange.fetch_positions()

    def fetch_open_orders(self) -> list:
        if self.paper:
            return []
        return self.exchange.fetch_open_orders()

    def free_margin(self) -> float:
        if self.paper or DRY_RUN:
            return self.cash_usd
        bal, _ = compute_real_free_margin(self.exchange.fetch_balance(),
                                          self.exchange.fetch_positions())
        return bal

    def seed_price_history(self) -> None:
        """Seed 1m price feed + candle store from a real exchange (paper or live)."""
        self.feed.seed_from_exchange(self.exchange)
        self.refresh_mtf_candles()

    def refresh_mtf_candles(self) -> Dict[str, int]:
        """Fetch LIVE OHLCV for all 6 MTF timeframes and persist to data/."""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import threading
        results: Dict[str, int] = defaultdict(int)
        errors: Dict[str, int] = defaultdict(int)
        from .signals import set_candles
        _lock = threading.Lock()

        def fetch_one(pair: str, tf: str):
            for attempt in range(3):
                try:
                    ohlcv = self.exchange.fetch_ohlcv(pair, timeframe=tf, limit=MTF_CANDLE_LIMIT)
                    if ohlcv and len(ohlcv) >= 52:
                        rows = [[int(c[0])] + [float(x) for x in c[1:6]] for c in ohlcv]
                        set_candles(pair, tf, rows)
                        with _lock:
                            results[tf] += 1
                        return
                except Exception:
                    time.sleep(1.0 * (attempt + 1))
            with _lock:
                errors[tf] += 1

        jobs = [(pr, tf) for pr in SYMBOLS for tf in MTF_TIMEFRAMES]
        with ThreadPoolExecutor(max_workers=4) as ex:
            list(ex.map(lambda j: fetch_one(j[0], j[1]), jobs))
        if errors:
            log.warning(f"  MTF refresh errors: {dict(errors)}")
        return dict(results)
