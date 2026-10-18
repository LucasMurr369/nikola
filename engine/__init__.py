"""Nikola — Dynamic Risk-Reward trading engine for Kraken BTNL margin pairs.

Reuses the proven signal/sizing logic from the live margin bot and layers an
explicit 3-state Dynamic R:R state machine (:mod:`nikola.engine.strategy`) on top.
"""
