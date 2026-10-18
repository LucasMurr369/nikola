"""
Nikola engine strategy — the 3-State Dynamic Risk-Reward state machine.

This is Nikola's core innovation over the live bot. The bot already runs a TP1/TP2
+ 20% runner ladder with BE ratchet and trailing TP, but those rules are scattered
across ``check_open_positions`` and ``adjust_trailing_tp``. Nikola centralises the
*entire* position lifecycle into one auditable state machine that treats 3:1 as a
**minimum entry filter** and **expands** when market structure (MTF confluence +
ATR) supports a larger move.

States
------
    MONITOR   Entry order sent; SL1 placed (-2.1% partial, convict-on close).
              Waiting for fill confirmation before arming the TP ladder.

    ACTIVE    Entry filled. Base TP1/TP2 + 20% runner are live. SL1 active.
              At +0.1R → BE ratchet primes; upon TP1 fill → SL1 cancelled,
              hard SL2 ratchets to Entry+Fees+0.2%; upon TP2 fill → SL2 ratchets
              to TP1 level, SL1 trails runner at 0.60% wide.
              SL1 partial fires on 1m/5m candle close ≥ 1.5% adverse (conviction gate).

    EXPANDED  +3R reached. 50% partial exit booked. Remaining 50% either:
              • MTF strong (≥3/6 TFs agree) → 2×ATR trailing stop (mega-trend)
              • MTF weak → tight 0.60% trail (lock & bank)

The machine emits :class:`ExecutionAction` directives — it never touches an
exchange directly. The exchange/paper layer consumes them. This makes the
state machine 100 % unit-testable with mock prices and votes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, List, Dict, Any

from .config import (
    SL1_PCT, SL1_CONVICTION_PCT, SL2_PCT, TRAIL_STOP_PCT, TRAIL_WIDE_PCT, TRAIL_WIDE_ARM_PCT,
    BREAKEVEN_BUFFER_PCT, TP_RUNG_PCTS, MAJOR_TP_PCTS,
    MTF_TIMEFRAMES, HIGH_LEV_PAIRS,
    BTC_CASCADE_TRIGGER_PCT, CASCADE_SCALEOUT_PCT,
    FEE_TERM_PCT, RATCHET_PROFIT_BUFFER_PCT, RATCHET_SL1_BUFFER_PCT,
)


class PositionState(Enum):
    MONITOR = auto()    # Entry sent, waiting for fill
    ACTIVE = auto()     # Filled — base TP/SL ladder live
    EXPANDED = auto()   # +3R reached — partial exit + MTF trailing

    @property
    def label(self) -> str:
        return self.name.title()


@dataclass
class TPRungs:
    """The two take-profit rungs + the trailing runner."""
    tp1_price: float
    tp2_price: float
    tp1_pct: float = 0.40      # fraction of BASE at TP1
    tp2_pct: float = 0.40      # fraction of BASE at TP2 (mirrors TP1 — 40/40/20)
    runner_pct: float = 0.20   # fraction of BASE that trails
    tp1_filled: bool = False
    tp2_filled: bool = False
    runner_trailing: bool = False
    be_ratchet_primed: bool = False  # BE_PRIME emitted (micro-Breakeven tracking armed)

    def to_dict(self) -> dict:
        """Serialize to dict for live-state persistence."""
        from dataclasses import asdict
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "TPRungs":
        """Reconstruct from deserialized dict."""
        if d is None:
            return None
        return cls(**d)


@dataclass
class Position:
    """A tracked position with its full exit geometry and state."""
    pair: str
    direction: str              # "LONG" or "SHORT"
    entry_price: float
    base_amount: float
    leverage: int
    signal_type: str = "UNKNOWN"
    confidence: float = 0.0

    # Risk geometry
    risk_distance: float = 0.0  # |SL1 − entry|  (R in $)
    sl1_price: float = 0.0
    sl2_price: float = 0.0

    # Ladder
    tp: Optional[TPRungs] = None
    be_floor: float = 0.0       # current breakeven floor (== SL2 when not ratcheted)

    # State
    state: PositionState = PositionState.MONITOR
    filled: bool = False        # entry fill confirmed
    peak_price: float = 0.0
    peak_r: float = 0.0

    # Expanded-state bookkeeping
    expanded_exited_half: bool = False
    trailing_sl: float = 0.0    # dynamic trailing stop in EXPANDED state

    open_time: str = ""
    cascade_scaled_out: bool = False   # BTC cascade scale-out applied
    sl1_hit: bool = False   # SL1 partial-close fired (prevents re-trigger)
    trade_id: str = ""                 # links to paper_trades.json ledger
    # Post-fill stop ratchet (active after TP1/TP2 fill)
    sl1_cancelled: bool = False      # initial -2.1% SL1 cancelled on exchange after TP1
    sl2_ratcheted: bool = False    # SL2 hard stop ratcheted up to TP1 level after TP2
    # Exchange order IDs — declared with empty-string defaults so bare reads
    # (recovery housekeeping line ~1063, board repr) never raise AttributeError
    # before the IDs are attached from the exchange on recovery.
    sl2_order_id: str = ""
    tp1_order_id: str = ""
    tp2_order_id: str = ""
    entry_order_id: str = ""

    def to_dict(self) -> dict:
        """Serialize to dict for live-state persistence.

        Converts the PositionState enum to its name string so the
        dict is JSON-serializable.  Captures in-flight state lost
        during exchange-based recovery (peak_price, trailing_sl,
        sl1_cancelled, sl2_ratcheted, cascade_scaled_out, etc.).
        """
        from dataclasses import asdict
        d = asdict(self)
        d['state'] = self.state.name
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Position":
        """Reconstruct from deserialized dict for live-mode recovery.

        Restores state flags that exchange recovery alone cannot
        reconstruct: peak_price, trailing_sl, TP-ratchet booleans,
        cascade flag, expanded-exited-half, etc.
        """
        import dataclasses
        state_name = d.pop('state', 'MONITOR')
        tp_dict = d.pop('tp', None)
        field_names = {f.name for f in dataclasses.fields(cls)}
        d = {k: v for k, v in d.items() if k in field_names}
        pos = cls(**d)
        pos.state = PositionState[state_name]
        if tp_dict is not None:
            pos.tp = TPRungs.from_dict(tp_dict)
        return pos


@dataclass
class ExecutionAction:
    """A directive from the state machine to the execution layer."""
    action: str
    pair: str
    price: float = 0.0
    payload: Dict[str, Any] = field(default_factory=dict)


class DynamicRiskReward:
    """3-state dynamic RR engine.

    Configuration knobs (in R-multiples or %):
        be_ratchet_r       — +0.1R → prime BE ratchet
        partial_exit_r      — +3.0R → 50% partial exit, enter EXPANDED
        expand_mtf_min      — ≥3/6 TFs agreeing → MTF trailing (vs tight trail)
        atr_trail_mult      — 2×ATR trailing distance in EXPANDED state
        sl1_conviction_pct  — SL1 partial fires when 1m/5m candle closes adverse
                               by ≥ this fraction (default 1.5% from SL1_CONVICTION_PCT)
    """

    def __init__(self):
        # R-multiple thresholds
        self.be_ratchet_r: float = 0.1
        self.partial_exit_r: float = 3.0
        self.expand_mtf_min: int = 3          # ≥3/6 TFs confirm trend

        # Trailing geometry
        self.atr_trail_mult: float = 2.0
        self.tight_trail_pct: float = TRAIL_WIDE_PCT   # 0.60% tight trail
        self.be_buffer_pct: float = BREAKEVEN_BUFFER_PCT  # +2.0% BE floor

        # SL1 conviction threshold — partial fires on 1m/5m candle close ≥ 1.5% adverse
        self.sl1_conviction_pct: float = SL1_CONVICTION_PCT

        # Peak thresholds (as R-multiples) for runner trail arm
        # TRAIL_WIDE_ARM_PCT = 0.025 (2.5%)  → 2.5/2.1 ≈ 1.19R
        self.runner_arm_r: float = TRAIL_WIDE_ARM_PCT / SL1_PCT

    # ------------------------------------------------------------------
    # R-multiple math
    # ------------------------------------------------------------------
    def r_multiple(self, pos: Position, price: float) -> float:
        """Profit in R-multiples (R = risk_distance). Positive = in profit."""
        if pos.risk_distance <= 0:
            return 0.0
        if pos.direction == "LONG":
            return (price - pos.entry_price) / pos.risk_distance
        return (pos.entry_price - price) / pos.risk_distance

    def _pct_as_r(self, pct: float) -> float:
        """Convert a price percentage (e.g. 0.025) into R-multiples."""
        return pct / SL1_PCT if SL1_PCT > 0 else 0.0

    # ------------------------------------------------------------------
    # Peak tracking
    # ------------------------------------------------------------------
    def _update_peak(self, pos: Position, price: float, r: float) -> None:
        """Track the best price / R seen so far (for trailing)."""
        if pos.direction == "LONG":
            if price > pos.peak_price or pos.peak_price == 0.0:
                pos.peak_price = price
                pos.peak_r = max(pos.peak_r, r)
        else:
            if price < pos.peak_price or pos.peak_price == 0.0:
                pos.peak_price = price
                pos.peak_r = max(pos.peak_r, r)
        # peak_r is always the maximum R seen (positive direction)
        pos.peak_r = max(pos.peak_r, r)

    # ------------------------------------------------------------------
    # TP geometry helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _make_ladder(pos: Position) -> TPRungs:
        """Build the TP1/TP2/runner rungs from entry + pair geometry."""
        pair = pos.pair
        price = pos.entry_price
        from .config import tp_rungs_for
        spec = tp_rungs_for(pair)
        if len(spec) >= 2:
            tp1_pct_level = spec[0][2]
            tp2_pct_level = spec[1][2]
        else:
            tp1_pct_level = TP_RUNG_PCTS[0][2]
            tp2_pct_level = TP_RUNG_PCTS[-1][2]

        if pos.direction == "LONG":
            tp1_price = price + price * tp1_pct_level
            tp2_price = price + price * tp2_pct_level
        else:
            tp1_price = price - price * tp1_pct_level
            tp2_price = price - price * tp2_pct_level

        return TPRungs(
            tp1_price=tp1_price, tp2_price=tp2_price,
            tp1_pct=TP_RUNG_PCTS[0][1], tp2_pct=TP_RUNG_PCTS[1][1],
        )

    def _sl1_price(self, pos: Position) -> float:
        """SL1 distance = entry × SL1_PCT."""
        if pos.direction == "LONG":
            return pos.entry_price - pos.entry_price * SL1_PCT
        return pos.entry_price + pos.entry_price * SL1_PCT

    def _sl2_price(self, pos: Position) -> float:
        """SL2 distance = entry × SL2_PCT (2× SL1)."""
        if pos.direction == "LONG":
            return pos.entry_price - pos.entry_price * SL2_PCT
        return pos.entry_price + pos.entry_price * SL2_PCT

    # ------------------------------------------------------------------
    # Post-fill stop ratchet helpers
    # ------------------------------------------------------------------
    def _ratchet_sl2_price(self, pos: Position) -> float:
        """Post-TP1 hard stop: Entry + fees + 0.2% profit buffer.

        This replaces the original -4.4% SL2 with a positive hard stop just
        above entry, guaranteeing no trade washes out to zero. The 0.2%
        buffer (plus fee term) ensures the stop sits in profit territory
        — 80% of the position is already banked via TP1/TP2.
        """
        buffer = pos.entry_price * (FEE_TERM_PCT + RATCHET_PROFIT_BUFFER_PCT)
        if pos.direction == "LONG":
            return pos.entry_price + buffer
        return pos.entry_price - buffer

    def _ratchet_sl1_below_tp1(self, pos: Position) -> float:
        """Post-TP1 SL1: dynamic candle stop sits ~0.5% below TP1 level.

        After TP1 fills, the old -2.1% SL1 is cancelled on the exchange.
        SL1 is repositioned below TP1 as a trailing candle-close stop that
        protects the remaining position (TP2 + 20% runner) while letting
        the trade continue toward TP2.
        """
        if pos.tp is None:
            return pos.sl1_price
        if pos.direction == "LONG":
            return pos.tp.tp1_price - pos.tp.tp1_price * RATCHET_SL1_BUFFER_PCT
        return pos.tp.tp1_price + pos.tp.tp1_price * RATCHET_SL1_BUFFER_PCT

    def _ratchet_sl2_to_tp1(self, pos: Position) -> float:
        """Post-TP2 hard stop: ratchet SL2 up to TP1 price level.

        After TP2 fills (80% banked), the exchange hard stop moves to TP1
        price, locking in +1.4% profit on the remaining 20% runner. This
        guarantees no trade washout — the runner can never lose money.
        """
        if pos.tp is None:
            return pos.sl2_price
        return pos.tp.tp1_price

    # ------------------------------------------------------------------
    # MTF strength
    # ------------------------------------------------------------------
    def _mtf_strength(self, votes: Dict[str, str], direction: str) -> int:
        """Count timeframes whose vote matches the position direction."""
        if not votes:
            return 0
        return sum(1 for v in votes.values() if v == ("LONG" if direction == "LONG" else "SHORT"))

    # ------------------------------------------------------------------
    # SL1 conviction check
    # ------------------------------------------------------------------
    def _sl1_conviction_triggered(self, pos: Position) -> bool:
        """SL1 partial fires only when a new 1m/5m candle CLOSES adverse >= 1.5%.

        Loads the last completed candle from the 1m and 5m feeds and checks
        whether its close is adverse to the position by >= SL1_CONVICTION_PCT.
        Uses the more adverse of the two timeframes. Candle close (not wick)
        is the conviction signal — no whipsaw scale-out on a price touch.
        """
        from .signals import load_candles
        max_adverse = 0.0
        for tf in ("1m", "5m"):
            candles = load_candles(pos.pair, tf)
            if len(candles) < 2:
                continue
            close = float(candles[-1][4])  # most recent close
            if pos.entry_price <= 0:
                continue
            if pos.direction == "LONG":
                adverse = (pos.entry_price - close) / pos.entry_price
            else:
                adverse = (close - pos.entry_price) / pos.entry_price
            max_adverse = max(max_adverse, adverse)
        return max_adverse >= SL1_CONVICTION_PCT

    # ------------------------------------------------------------------
    # Main evaluation
    # ------------------------------------------------------------------
    def step(self, pos: Position, price: float,
             votes: Optional[Dict[str, str]] = None,
             atr: Optional[float] = None) -> List[ExecutionAction]:
        """Evaluate the position state machine at the current price.

        Returns a list of :class:`ExecutionAction` directives for the execution
        layer to act on. Returns [] when nothing changes.
        """
        actions: List[ExecutionAction] = []
        if pos.entry_price <= 0 or pos.risk_distance <= 0:
            return actions

        r = self.r_multiple(pos, price)
        self._update_peak(pos, price, r)

        # BTC cascade scale-out (live bot lines 2618-2661):
        # when BTC dumps >4% 1m, close 15% reduce-only before the alt's own SL fires.
        # Applies to ACTIVE + EXPANDED. Handles BOTH LONG and SHORT via pos.base_amount
        # tracking — the live bot's short-side filled_prev NameError (line 2812) is
        # structurally impossible here because base_amount is the single source of truth.
        if pos.state != PositionState.MONITOR and pos.filled and not pos.cascade_scaled_out:
            from .signals import btc_1m_momentum
            btc_short = btc_1m_momentum()
            if (pos.pair not in HIGH_LEV_PAIRS and pos.base_amount > 0
                    and btc_short < -BTC_CASCADE_TRIGGER_PCT):
                pos.cascade_scaled_out = True
                scale_base = pos.base_amount * CASCADE_SCALEOUT_PCT
                pos.base_amount -= scale_base
                actions.append(ExecutionAction(
                    "CASCADE_SCALEOUT", pos.pair, price=price,
                    payload={"btc_momentum": round(btc_short, 4),
                             "scaleout_pct": CASCADE_SCALEOUT_PCT,
                             "scale_base": round(scale_base, 8),
                             "remaining_base": round(pos.base_amount, 8)}))

        # ---- MONITOR → ACTIVE ----
        if pos.state == PositionState.MONITOR:
            if pos.filled:
                pos.state = PositionState.ACTIVE
                pos.sl1_price = self._sl1_price(pos)
                pos.sl2_price = self._sl2_price(pos)
                pos.tp = self._make_ladder(pos)
                pos.be_floor = pos.sl2_price  # BE floor = SL2 initially
                pos.peak_price = price
                actions.append(ExecutionAction(
                    "STATE_TRANSITION", pos.pair, price=pos.entry_price,
                    payload={"from": "MONITOR", "to": "ACTIVE",
                             "r": round(r, 2)}))
                actions.append(ExecutionAction(
                    "ARM_SL", pos.pair, price=pos.sl1_price,
                    payload={"stopped_price": pos.sl1_price,
                             "mode": "partial", "sl2": pos.sl2_price}))
            return actions

        # ---- ACTIVE ----
        elif pos.state == PositionState.ACTIVE:
            if pos.tp is None:
                pos.tp = self._make_ladder(pos)

            # 1) TP1 fill (r ≥ R for TP1)
            if not pos.tp.tp1_filled:
                tp1_r = self.r_multiple(pos, pos.tp.tp1_price)
                if (pos.direction == "LONG" and price >= pos.tp.tp1_price) or \
                   (pos.direction == "SHORT" and price <= pos.tp.tp1_price):
                    pos.tp.tp1_filled = True
                    actions.append(ExecutionAction(
                        "TP1_FILLED", pos.pair, price=pos.tp.tp1_price,
                        payload={"r": round(tp1_r, 2), "partial": pos.tp.tp1_pct}))
                    # ── Post-fill stop ratchet (TP1) ──
                    # 1) Cancel the initial -2.1% SL1 on the exchange
                    pos.sl1_cancelled = True
                    actions.append(ExecutionAction(
                        "CANCEL_SL1", pos.pair, price=price,
                        payload={"reason": "tp1_filled", "old_sl1": pos.sl1_price}))
                    # 2) Issue new exchange hard stop SL2 at Entry + Fees + 0.2% buffer
                    pos.sl2_price = self._ratchet_sl2_price(pos)
                    pos.be_floor = pos.sl2_price
                    actions.append(ExecutionAction(
                        "PLACE_SL2_RATCHET", pos.pair, price=pos.sl2_price,
                        payload={"sl2_new": pos.sl2_price,
                                 "reason": "entry+fees+0.2pct_buffer",
                                 "buffer_pct": FEE_TERM_PCT + RATCHET_PROFIT_BUFFER_PCT}))
                    # 3) Move SL1 to just below TP1 level (candle-close trailing stop)
                    pos.sl1_price = self._ratchet_sl1_below_tp1(pos)
                    actions.append(ExecutionAction(
                        "MOVE_SL1", pos.pair, price=pos.sl1_price,
                        payload={"sl1_new": pos.sl1_price,
                                 "below_tp1": pos.tp.tp1_price,
                                 "sl1_buffer_pct": RATCHET_SL1_BUFFER_PCT}))

            # 2) TP2 fill → BE ratchet after BOTH rungs
            if not pos.tp.tp2_filled:
                tp2_r = self.r_multiple(pos, pos.tp.tp2_price)
                if (pos.direction == "LONG" and price >= pos.tp.tp2_price) or \
                   (pos.direction == "SHORT" and price <= pos.tp.tp2_price):
                    pos.tp.tp2_filled = True
                    actions.append(ExecutionAction(
                        "TP2_FILLED", pos.pair, price=pos.tp.tp2_price,
                        payload={"r": round(tp2_r, 2), "partial": pos.tp.tp2_pct}))
                    # 80% exited (40+40), BE ratchet arms on the 20% runner
                    # ── Post-fill stop ratchet (TP2) ──
                    # Ratchet SL2 hard stop UP to TP1 price level (locks +1.4% on runner)
                    ratcheted_sl2 = self._ratchet_sl2_to_tp1(pos)
                    pos.sl2_price = ratcheted_sl2
                    pos.sl2_ratcheted = True
                    # BE floor moves to TP1 level (runner can never lose money)
                    pos.be_floor = ratcheted_sl2
                    actions.append(ExecutionAction(
                        "RATCHET_TP2_SL2_TO_TP1", pos.pair, price=ratcheted_sl2,
                        payload={"sl2_prev": pos.be_floor, "sl2_new": ratcheted_sl2,
                                 "ratcheted_to": "TP1_price", "runner_remainder": pos.tp.runner_pct}))
                    # Attach SL1 to trail the 20% runner — arm immediately
                    if not pos.tp.runner_trailing:
                        pos.tp.runner_trailing = True
                        actions.append(ExecutionAction(
                            "ARM_RUNNER_TRAIL", pos.pair, price=pos.tp.tp1_price,
                            payload={"trail_pct": TRAIL_WIDE_PCT,
                                     "reason": "tp2_filled_ratchet_runner_trail"}))

            # 3) Runner trail arm at peak ≥ TRAIL_WIDE_ARM_PCT (≈1.19R)
            if pos.tp.tp2_filled and not pos.tp.runner_trailing:
                if pos.peak_r >= self.runner_arm_r:
                    pos.tp.runner_trailing = True
                    actions.append(ExecutionAction(
                        "ARM_RUNNER_TRAIL", pos.pair, price=pos.peak_price,
                        payload={"trail_pct": TRAIL_WIDE_PCT}))

            # 4) BE ratchet prime at +0.1R (before TP1 even fills)
            if not pos.tp.tp1_filled and not pos.tp.be_ratchet_primed and r >= self.be_ratchet_r:
                pos.tp.be_ratchet_primed = True
                actions.append(ExecutionAction(
                    "BE_PRIME", pos.pair, price=pos.entry_price,
                    payload={"reason": "early_protection", "r": round(r, 2)}))

            # 5) +3R → EXPANDED (the dynamic gate)
            if r >= self.partial_exit_r:
                pos.state = PositionState.EXPANDED
                pos.expanded_exited_half = False
                mtf = self._mtf_strength(votes or {}, pos.direction)
                actions.append(ExecutionAction(
                    "STATE_TRANSITION", pos.pair, price=price,
                    payload={"from": "ACTIVE", "to": "EXPANDED",
                             "r": round(r, 2), "mtf_strength": mtf}))
                # Branch: partial exit + trail
                self._expanded_branch(pos, actions, price, votes, atr, mtf)

            # 6) SL1 conviction check — partial close 40% of base, retain TPs, arm SL2.
            # Fires only when a new 1m/5m candle CLOSES adverse by >= 1.5% (candle-close
            # confirmation, not whipsaw on a price touch through the -2.1% SL1 level).
            # Skipped after TP1 ratchet — SL1 has been cancelled & repositioned below TP1.
            if not pos.sl1_hit and not pos.sl1_cancelled:
                sl1_triggered = self._sl1_conviction_triggered(pos)
                if sl1_triggered:
                    pos.sl1_hit = True
                    actions.append(ExecutionAction(
                        "SL1_HIT", pos.pair, price=price,
                        payload={"r": round(r, 2),
                                 "partial": TP_RUNG_PCTS[0][1],
                                 "sl2_price": pos.sl2_price}))

            # 7) SL2 hit (-4.4%) → full exit of remaining base
            sl2_triggered = (pos.direction == "LONG" and price <= pos.sl2_price) or \
                            (pos.direction == "SHORT" and price >= pos.sl2_price)
            if sl2_triggered:
                actions.append(ExecutionAction(
                    "SL2_EXIT", pos.pair, price=price,
                    payload={"r": round(r, 2), "reason": "sl2_hit"}))
            return actions

        # ---- EXPANDED ----
        else:
            return self._expanded_step(pos, actions, price, votes, atr)

    # ------------------------------------------------------------------
    # EXPANDED state logic
    # ------------------------------------------------------------------
    def _expanded_branch(self, pos: Position, actions: List[ExecutionAction],
                         price: float, votes: Optional[Dict],
                         atr: Optional[float], mtf: int) -> None:
        """First entry into EXPANDED: 50% partial + arm trailing on remainder."""
        actions.append(ExecutionAction(
            "PARTIAL_EXIT_50PCT", pos.pair, price=price,
            payload={"r": round(pos.peak_r, 2), "reason": "3R_dynamic_exit"}))

        pos.expanded_exited_half = True
        if mtf >= self.expand_mtf_min and atr and atr > 0:
            trail_dist = atr * self.atr_trail_mult
            pos.trailing_sl = (price - trail_dist
                               if pos.direction == "LONG"
                               else price + trail_dist)
            actions.append(ExecutionAction(
                "SWITCH_TO_MTF_TRAILING", pos.pair, price=pos.trailing_sl,
                payload={"trail_dist": round(trail_dist, 5),
                         "atr": round(atr, 5), "atr_mult": self.atr_trail_mult}))
        else:
            actions.append(ExecutionAction(
                "ARM_TIGHT_TRAIL_REMAINDER", pos.pair, price=price,
                payload={"trail_pct": self.tight_trail_pct}))

    def _expanded_step(self, pos: Position, actions: List[ExecutionAction],
                       price: float, votes: Optional[Dict],
                       atr: Optional[float]) -> List[ExecutionAction]:
        """Trailing updates inside EXPANDED — move stop, never add risk."""
        r = self.r_multiple(pos, price)

        # MTF-trail path: 2×ATR behind the peak (only tightens)
        if pos.trailing_sl > 0 and atr and atr > 0:
            mtf = self._mtf_strength(votes or {}, pos.direction)
            if mtf >= self.expand_mtf_min:
                trail_dist = atr * self.atr_trail_mult
                if pos.direction == "LONG":
                    new_sl = pos.peak_price - trail_dist
                    if new_sl > pos.trailing_sl:
                        pos.trailing_sl = new_sl
                        actions.append(ExecutionAction(
                            "MTF_TRAIL_UPDATE", pos.pair, price=new_sl,
                            payload={"trail_dist": round(trail_dist, 5),
                                     "peak": round(pos.peak_price, 5)}))
                else:
                    new_sl = pos.peak_price + trail_dist
                    if new_sl < pos.trailing_sl:
                        pos.trailing_sl = new_sl
                        actions.append(ExecutionAction(
                            "MTF_TRAIL_UPDATE", pos.pair, price=new_sl,
                            payload={"trail_dist": round(trail_dist, 5),
                                     "peak": round(pos.peak_price, 5)}))
            else:
                # MTF turned weak → tighten to 0.60% trail behind peak
                tight = pos.peak_price * self.tight_trail_pct
                if pos.direction == "LONG":
                    new_sl = pos.peak_price - tight
                    if new_sl > pos.trailing_sl:
                        pos.trailing_sl = new_sl
                        actions.append(ExecutionAction(
                            "TIGHTEN_TO_TIGHT_TRAIL", pos.pair, price=new_sl))
                else:
                    new_sl = pos.peak_price + tight
                    if new_sl < pos.trailing_sl:
                        pos.trailing_sl = new_sl
                        actions.append(ExecutionAction(
                            "TIGHTEN_TO_TIGHT_TRAIL", pos.pair, price=new_sl))

        # SL1 still active — backup exit at SL1 distance (direct price comparison)
        if pos.sl1_price > 0:
            sl1_triggered = (pos.direction == "LONG" and price <= pos.sl1_price) or \
                            (pos.direction == "SHORT" and price >= pos.sl1_price)
            if sl1_triggered:
                actions.append(ExecutionAction(
                    "SL2_FULL_EXIT", pos.pair, price=price,
                    payload={"r": round(r, 2), "reason": "expanded_stop_loss"}))
        return actions

    # ------------------------------------------------------------------
    # Factory: build a fresh ACTIVE position from a signal
    # ------------------------------------------------------------------
    def position_from_signal(self, pair: str, direction: str, entry_price: float,
                             base_amount: float, leverage: int, confidence: float,
                             signal_type: str = "UNKNOWN") -> Position:
        """Materialise a Position object immediately in ACTIVE state (filled entry)."""
        pos = Position(
            pair=pair, direction=direction, entry_price=entry_price,
            base_amount=base_amount, leverage=leverage,
            confidence=confidence, signal_type=signal_type,
            risk_distance=entry_price * SL1_PCT,
        )
        pos.filled = True
        pos.state = PositionState.ACTIVE
        pos.sl1_price = self._sl1_price(pos)
        pos.sl2_price = self._sl2_price(pos)
        pos.tp = self._make_ladder(pos)
        pos.be_floor = pos.sl2_price
        pos.peak_price = entry_price
        return pos
