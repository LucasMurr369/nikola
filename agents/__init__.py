"""Nikola agents package — Hermes-style autonomous agents (ported from the
BaseAgent pattern in build_hermes_v2.py, adapted to Nikola's single-process model).

Exported agents:
  - GodCodeAgent: ethical guardrail + wisdom passage cycler (build_hermes_v2.py
    GodCodeAgent lines 1151-1278, pre-Nicene texts, harm-signal evaluation).
"""
from .god_code import GodCodeAgent

__all__ = ["GodCodeAgent"]
