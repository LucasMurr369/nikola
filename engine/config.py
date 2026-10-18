"""
Nikola engine configuration.

Faithful port of the proven parameter set from the live margin bot
(kraken_bot/live_margin_bot.py, lines 41-258). These are the *exact* constants
that survived the TP/SL reconfigure and are currently live on Kraken — ported
verbatim so Nikola and the bot share an apples-to-apples risk profile.

The live bot is the source of truth; this module mirrors it so Nikola can be
validated against the bot's real P&L without touching its running process.
"""
from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CONFIG_DIR = BASE_DIR / "config"
PAPER_STATE_FILE = DATA_DIR / "paper_state.json"

# ---------------------------------------------------------------------------
# Community tithing / donations — customizable for forks and shares
# ---------------------------------------------------------------------------
# Default donation address for the Nikola project.  Community members who fork
# this repository can replace the value below with their own wallet address so
# that tithes flow to whoever maintains their fork, while the original project
# keeps its default.  Simply change the string and commit — no other code
# changes are required.
#
# Supported address formats (auto-linked by donation_monitor.py):
#   - BTC:  bc1q... / 3xxxx / 1xxxx
#   - ETH:  0x...
#   - DOGE: D...  /  A...
#   - LTC:  L...  /  l...  /  M...
#   Set to "" (empty string) to disable the donation feature entirely.
DONATION_ADDRESS: str = "bc1qxy2kgdygjrsqtzq2n0yrf29sdf7r2khsl2nf5x"
DONATION_CHAIN: str = "BTC"       # blockchain label shown in --export-html / reports
DONATION_NAME: str = "Nikola Project"  # display name for tithe messages

# ---------------------------------------------------------------------------
# Pair universe — 28-pair Kraken BTNL margin universe (user directive)
# ---------------------------------------------------------------------------
SYMBOLS = [
    "AAVE/USD", "ADA/USD", "ALGO/USD", "AVAX/USD", "BCH/USD", "BTC/USD",
    "CRV/USD", "DOGE/USD", "DOT/USD", "ETH/USD", "HBAR/USD", "HYPE/USD",
    "LINK/USD", "LTC/USD", "NEAR/USD", "PAXG/USD", "PENGU/USD", "PEPE/USD",
    "RENDER/USD", "SHIB/USD", "SOL/USD", "SUI/USD", "TRX/USD", "UNI/USD",
    "WLD/USD", "XLM/USD", "XRP/USD", "ZEC/USD",
]

# Per-pair Kraken maximum leverage (exceeding → "EOrder:Invalid leverage").
# NOTE: XDG→DOGE mapped in normalize_btln_symbol(); the bot marks non-Nikola
# pairs as FOREIGN and never touches them.
PAIR_LEVERAGE = {
    "AAVE/USD": 5,  "ADA/USD": 10,  "ALGO/USD": 5,  "AVAX/USD": 10, "BCH/USD": 5,
    "BTC/USD": 20,  "CRV/USD": 5,   "DOGE/USD": 10, "DOT/USD": 5,   "ETH/USD": 20,
    "HBAR/USD": 5,  "HYPE/USD": 5,  "LINK/USD": 10, "LTC/USD": 10,  "NEAR/USD": 5,
    "PAXG/USD": 5,  "PENGU/USD": 3, "PEPE/USD": 5,  "RENDER/USD": 5, "SHIB/USD": 5,
    "SOL/USD": 10,  "SUI/USD": 10,  "TRX/USD": 5,   "UNI/USD": 5,   "WLD/USD": 3,
    "XLM/USD": 5,   "XRP/USD": 10,  "ZEC/USD": 5,
}

# ---------------------------------------------------------------------------
# Multi-timeframe live refresh (user directive 2026-10-05, 1m added 2026-10-07)
# ---------------------------------------------------------------------------
MTF_TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "4h"]
TF_ORDER = ["4h", "1h", "30m", "15m", "5m", "1m"]  # trend → entry
MTF_CANDLE_LIMIT = 200
MIN_TF_AGREE_DEPLOY = 4  # >=4 of 6 TF must agree at deploy time (filter noise)
ENTRY_MIN_CONFIDENCE = 0.60  # MODERATE+ only — meaningful size requirement (was 0.20)
GOD_CODE_CYCLE_SEC = 300     # God Code quote cycle interval (seconds)

# ---------------------------------------------------------------------------
# Money management — live budget ($1M; $100 cap removed 2026-10-09), $300 paper clean-slate (Nikola.md)
# ---------------------------------------------------------------------------
PREFERRED_LEVERAGE = 5
LEVERAGE_FLOOR = 3
LEVERAGE_CAP = 20
LEV_UNLOCK_EQUITY_USD = 150.0       # BTC/ETH uncap to 20x after this equity
HIGH_LEV_PAIRS = ("BTC/USD", "ETH/USD")

MAX_POSITION_MARGIN_USD = 20.0  # LIVE cap: max $20 margin per position
TOTAL_MARGIN_BUDGET_USD = 1_000_000.0
PAPER_BUDGET_USD = 300.0            # Nikola.md clean-state restart
MARGIN_RESERVE_PCT = 0.15  # 15% reserve — unattended safety (was 0.0 = full deploy)
                            # With 7x leverage, 0.15 buffer prevents cascade liquidation
                            # if all 5 positions move against the bot simultaneously.
REENTRY_COOLDOWN_SEC = 3600           # 1-hour cooldown after each exit
MAX_POSITION_LOSS_USD = 10.0        # paper-mode fixed $ loss per trade
FEE_TERM_PCT = 0.005                # round-trip fee estimate
RATCHET_PROFIT_BUFFER_PCT = 0.002   # 0.2% profit buffer above entry for post-TP1 hard stop
RATCHET_SL1_BUFFER_PCT = 0.005      # SL1 sits 0.5% below TP1 level (candle-close trailing)

# Conviction-tiered leverage + dynamic margin (mirrors each other)
# MARGIN_TIERS now express % of deployable budget (dynamic equity-based sizing)
LEV_TIERS = [(0.60, 20), (0.50, 10), (0.40, 7), (0.0, 3)]
MARGIN_TIERS = [(0.60, 0.40), (0.50, 0.30), (0.40, 0.20), (0.20, 0.20)]  # User: increased tiers for meaningful position size (was 0.25/0.20/0.15/0.15)

# ---------------------------------------------------------------------------
# settings.yaml overlay -- technical users tune leverage caps here (config/
# settings.yaml) without touching code. Hardcoded values above are the safe
# defaults; YAML takes precedence when present. Dynamic leverage via
# leverage_for() stays automated by default -- this only rebinds the knobs.
# ---------------------------------------------------------------------------
def _apply_settings_yaml() -> None:
    try:
        import yaml
    except ImportError:  # PyYAML ships in requirements.txt; keep defaults if absent
        return
    cfg_file = CONFIG_DIR / "settings.yaml"
    if not cfg_file.exists():
        return
    try:
        with open(cfg_file, "r", encoding="utf-8") as f:
            s = yaml.safe_load(f) or {}
    except Exception:
        return
    pairs = s.get("pairs") or {}
    global LEVERAGE_FLOOR, LEVERAGE_CAP, PREFERRED_LEVERAGE, LEV_UNLOCK_EQUITY_USD
    global MARGIN_RESERVE_PCT, MARGIN_TIERS
    if "leverage_floor" in pairs:
        LEVERAGE_FLOOR = int(pairs["leverage_floor"])
    if "leverage_cap" in pairs:
        LEVERAGE_CAP = int(pairs["leverage_cap"])
    if "preferred_leverage" in pairs:
        PREFERRED_LEVERAGE = int(pairs["preferred_leverage"])
    if "lev_unlock_equity_usd" in pairs:
        LEV_UNLOCK_EQUITY_USD = float(pairs["lev_unlock_equity_usd"])
    # Load capital settings (margin reserve + margin tiers) so users can
    # tune deploy aggression from settings.yaml without touching code.
    capital = s.get("capital") or {}
    if "margin_reserve_pct" in capital:
        MARGIN_RESERVE_PCT = float(capital["margin_reserve_pct"])
    if "margin_tiers" in capital and isinstance(capital["margin_tiers"], list):
        MARGIN_TIERS = [(float(t[0]), float(t[1])) for t in capital["margin_tiers"]]
    global MAX_POSITION_MARGIN_USD
    global PAPER_BUDGET_USD, LIVE_BUDGET_USD
    if "max_position_margin_usd" in capital:
        MAX_POSITION_MARGIN_USD = float(capital["max_position_margin_usd"])
    if "paper_budget_usd" in capital:
        PAPER_BUDGET_USD = float(capital["paper_budget_usd"])
    if "live_budget_usd" in capital:
        LIVE_BUDGET_USD = float(capital["live_budget_usd"])
    # Load engine settings — mtf_candle_limit controls how many candles
    # the MTF engine loads per pair/timeframe (settings do what they say).
    global MTF_CANDLE_LIMIT
    eng = s.get("engine") or {}
    if "mtf_candle_limit" in eng:
        MTF_CANDLE_LIMIT = int(eng["mtf_candle_limit"])
    if "god_code_cycle_sec" in eng:
        global GOD_CODE_CYCLE_SEC
        GOD_CODE_CYCLE_SEC = int(eng["god_code_cycle_sec"])


_apply_settings_yaml()

# ---------------------------------------------------------------------------
# Two-stage stop-loss + TP ladder (user directive — current live config)
# ---------------------------------------------------------------------------
SL1_PCT = 0.0210          # -2.10% — SL1 distance; partial close (40% of base), TPs retained
SL1_CONVICTION_PCT = 0.015  # SL1 partial fires when 1m/5m candle closes adverse >= 1.5%
SL2_PCT = 0.0440          # -4.40% — full exit of remaining (2x SL1 distance)
STOP_LOSS_PCT = SL1_PCT   # backward-compat alias
TRAIL_STOP_PCT = 0.0030   # stage-1 trail 0.30%
TRAIL_WIDE_PCT = 0.0060   # stage-2 trail 0.60% @ +2.5%
TRAIL_WIDE_ARM_PCT = 0.025  # switch to wide trail once peak >= +2.5%
TRAIL_LOCK_RATIO = 0.5    # retained for legacy adjust_trailing_tp
# --- BTC cascade scale-out (live bot lines 2618-2661) ---
BTC_CASCADE_TRIGGER_PCT = 0.04    # BTC -4% 1m momentum triggers cascade
CASCADE_SCALEOUT_PCT = 0.15       # close 15% of base reduce-only before SL fires
TRAIL_TRIGGER_RATIO = 0.0  # trail kicks in once any profit exists
SL_LIMIT_BAND_PCT = 0.015  # stop-loss-limit slippage allowance
BREAKEVEN_BUFFER_PCT = 0.02  # BE floor = entry + 2.0% (ratchets after TP1+TP2)

# TP1 +1.4%/40% + TP2 +2.8%/40% (mirrors TP1, 2× TP1 distance — user 2026-10-07)
# Final 20% rides the trailing stop.
TP_RUNG_PCTS = [
    ("TP1", 0.40, 0.014),   # 40% of base @ +1.4%
    ("TP2", 0.40, 0.028),   # 40% of base @ +2.8% = 2× TP1 distance (mirrors TP1)
]                           # Final 20% rides the trailing stop.

# Bigger slower coins get closer targets (+1.0%/+2.0% books faster)
MAJOR_TP_PCTS = {"BTC/USD": (0.010, 0.020), "ETH/USD": (0.010, 0.020)}

# ---------------------------------------------------------------------------
# Balance caps — sweep protection (user 2026-10-06)
# ---------------------------------------------------------------------------
MEME_GROUP = {"DOGE/USD", "SHIB/USD", "PEPE/USD", "PENGU/USD"}
MAJOR_GROUP = {"BTC/USD", "ETH/USD", "PAXG/USD", "LTC/USD", "BCH/USD",
               "XRP/USD", "TRX/USD", "XLM/USD", "ADA/USD", "HBAR/USD"}
# MAX_*_POSITIONS = 0 → budget is the only gate (user 2026-10-07)
MAX_TOTAL_POSITIONS = 9  # Hard cap: max 9 concurrent positions ($20 each) (was 5)
MAX_MEME_POSITIONS = 0
MAX_HIGH_BETA_POSITIONS = 0

# Three-leader model
COIN_GROUPS = {
    "BTC": ["BTC", "BCH", "LTC", "HBAR", "PAXG", "TRX", "XLM", "ALGO", "CRV", "ZEC"],
    "ETH": ["ETH", "ADA", "SOL", "AVAX", "DOT", "LINK", "UNI", "NEAR", "AAVE",
            "WLD", "RENDER", "SUI", "HYPE", "PENGU"],
    "XRP": ["XRP"],
}
LEADERS = ["BTC", "ETH", "XRP"]
MEME_COINS = ["DOGE", "SHIB", "PEPE"]
LEADER_DIR_THRESHOLD = 0.01  # 1h leader direction threshold

# ---------------------------------------------------------------------------
# Per-pair exchange minimums (Kraken public AssetPairs 'ordermin')
# ---------------------------------------------------------------------------
MIN_BASE_AMOUNT = 8.0  # fallback (DOGE not listed publicly)
PAIR_MIN_BASE = {
    "AAVE/USD": 0.05,     "ADA/USD": 20.0,      "ALGO/USD": 41.0,
    "AVAX/USD": 0.5,      "BCH/USD": 0.01,      "BTC/USD": 0.00005,
    "CRV/USD": 20.0,      "DOGE/USD": 8.0,      "DOT/USD": 3.9,
    "ETH/USD": 0.001,     "HBAR/USD": 55.0,     "HYPE/USD": 0.1,
    "LINK/USD": 0.55,     "LTC/USD": 0.1,       "NEAR/USD": 4.0,
    "PAXG/USD": 0.001,    "PENGU/USD": 700.0,   "PEPE/USD": 1500000.0,
    "RENDER/USD": 2.5,    "SHIB/USD": 770000.0, "SOL/USD": 0.06,
    "SUI/USD": 5.0,       "TRX/USD": 16.0,      "UNI/USD": 1.5,
    "WLD/USD": 11.0,      "XLM/USD": 30.0,      "XRP/USD": 1.65,
    "ZEC/USD": 0.01,
}

# Per-pair amount precision (decimal fix for all coins)
PAIR_AMT_PRECISION = {
    "AAVE/USD": 8, "ADA/USD": 8, "ALGO/USD": 8, "AVAX/USD": 8,
    "BCH/USD": 8, "BTC/USD": 8, "CRV/USD": 8, "DOGE/USD": 8,
    "DOT/USD": 8, "ETH/USD": 8, "HBAR/USD": 8, "HYPE/USD": 8,
    "LINK/USD": 8, "LTC/USD": 8, "NEAR/USD": 8, "PAXG/USD": 8,
    "PENGU/USD": 2, "PEPE/USD": 0, "RENDER/USD": 8, "SHIB/USD": 0,
    "SOL/USD": 8, "SUI/USD": 8, "TRX/USD": 8, "UNI/USD": 8,
    "WLD/USD": 8, "XLM/USD": 8, "XRP/USD": 8, "ZEC/USD": 8,
}

# ---------------------------------------------------------------------------
# Timing / loop cadence
# ---------------------------------------------------------------------------
LIGHT_LOOP_INTERVAL = 15     # seconds — light check (stop/TP monitoring)
FULL_SCAN_INTERVAL = 150     # seconds — full scan (MTF refresh + signal scan)
SWEEP_CHECK_TF = "15m"
STALE_TICKER_MAX_AGE_SEC = 900
ENTRY_FILL_GRACE_SEC = 60   # patience for unfilled entry limits before _sync kills them (chop fill reliability)
ENTRY_SLIPPAGE_PCT = 0.003  # thin buy-limit buffer above the 1m close so chop/uptrend entries fill (bounded 0.3% slip; RR rebases onto filled price, distances unchanged)
BTC_DUMP_GUARD_PCT = -0.025  # skip NEW alt deploys when BTC 15m momentum < -2.5%

# ---------------------------------------------------------------------------
# Self-learning (signal_weights.json ±0.05, clamped 0.5-1.5)
# ---------------------------------------------------------------------------
WEIGHT_MIN = 0.5
WEIGHT_MAX = 1.5
WEIGHT_ADJUST = 0.05

# ---------------------------------------------------------------------------
# Paper mode
# ---------------------------------------------------------------------------
PAPER_AUTO_EXECUTE = True
PAPER_TRADE_MAX_AGE_HOURS = 24

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
os = __import__('os')
DRY_RUN = os.environ.get("NIKOLA_DRY_RUN", "true").lower() == "true"
FREE_MARGIN_MIN = 1.0
MIN_FREE_MARGIN_USD = 2.0
EQUITY_SCALE_MIN = 0.5
EQUITY_SCALE_MAX = 1.35
EQUITY_BASELINE_USD = 100.0
EQUITY_SCALE = 1.0


def leverage_for(confidence: float, pair: str | None = None, equity: float = 0.0) -> int:
    """Conviction-tiered leverage (3-20x), capped by Kraken's per-pair maximum.

    BTC/ETH capped at 7x until equity >= LEV_UNLOCK_EQUITY_USD (then up to 20x).
    """
    lev = LEVERAGE_FLOOR
    tiers = list(LEV_TIERS)
    for floor, l in tiers:
        if confidence >= floor:
            lev = min(l, LEVERAGE_CAP)
            break
    if pair is not None:
        pair_cap = PAIR_LEVERAGE.get(pair, LEVERAGE_CAP)
        if pair in HIGH_LEV_PAIRS and equity < LEV_UNLOCK_EQUITY_USD:
            pair_cap = min(pair_cap, 7)
        lev = min(lev, pair_cap)
    return max(lev, 1)


def progressive_reserve_pct(equity_usd: float = 0.0) -> float:
    """Reserve % scales with equity — protects accumulated gains as the bot succeeds.

    Starts at $0: a fresh bot (no gains to protect) keeps a 15% floor.
    Reserve % ramps up as equity grows — more gains = more protection.

    Examples (per user directive):
      $100 equity → 25% reserve ($25)
      $150 equity → 33% reserve ($50)
    """
    if equity_usd <= 50:
        return 0.15  # 15% floor — fresh bot, minimal gains to protect
    elif equity_usd <= 100:
        return 0.15 + (equity_usd - 50) / 50 * 0.10  # 15% → 25%
    elif equity_usd <= 150:
        return 0.25 + (equity_usd - 100) / 50 * 0.08  # 25% → 33%
    else:
        return 0.33  # 33% cap for high equity


def deployable_margin(budget: float = TOTAL_MARGIN_BUDGET_USD) -> float:
    """Deployable margin = budget × equity_scale × (1 − reserve_pct)."""
    return budget * EQUITY_SCALE * (1.0 - MARGIN_RESERVE_PCT)


def margin_tier_for(confidence: float, budget: float = TOTAL_MARGIN_BUDGET_USD) -> float:
    """Conviction-weighted margin: dynamic % of deployable budget (no static $ caps)."""
    deployable = deployable_margin(budget)
    for floor, pct in MARGIN_TIERS:
        if confidence >= floor:
            return deployable * pct
    return deployable * MARGIN_TIERS[-1][1]


def tp_rungs_for(pair: str | None = None) -> list[tuple[str, float, float]]:
    """Per-pair TP geometry: majors get closer targets, alts use the default ladder."""
    if pair and pair in MAJOR_TP_PCTS:
        t1, t2 = MAJOR_TP_PCTS[pair]
        return [("TP1", TP_RUNG_PCTS[0][1], t1),
                ("TP2", TP_RUNG_PCTS[1][1], t2)]
    return list(TP_RUNG_PCTS)


def min_base_for(pair: str) -> float:
    return PAIR_MIN_BASE.get(pair, MIN_BASE_AMOUNT)


def round_amount(pair: str, amount: float) -> float:
    """Round order amount to the correct per-coin decimal precision."""
    return round(amount, PAIR_AMT_PRECISION.get(pair, 8))


def group_of(pair: str) -> str:
    if pair in MEME_GROUP:
        return "MEME"
    if pair in MAJOR_GROUP:
        return "MAJOR"
    return "HIGH_BETA"


def normalize_btln_symbol(sym: str) -> str:
    """Convert Kraken-native BTNL symbol (NEARUSD:BTNL) to CCXT format (NEAR/USD:BTNL)."""
    if "/" in sym:
        return sym
    if ":BTNL" not in sym:
        return sym
    prefix = sym.replace(":BTNL", "")
    # XBT→BTC, XDG→DOGE mapping (FOREIGN-pair blocking depends on it)
    if prefix.startswith("XBT"):
        prefix = "BTC" + prefix[3:]
    if prefix.startswith("XDG"):
        prefix = "DOGE" + prefix[3:]
    for pair in SYMBOLS:
        if pair.replace("/", "") == prefix:
            return f"{pair}:BTNL"
    return sym
