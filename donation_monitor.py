#!/usr/bin/env python3
"""
Donation Monitor — HERMES/NIKOLA bot multi-chain donation receiver.

Supports all donation options that are free (or near-free) on both ends:

  A. Direct crypto address (Solana, Base L2)
     - Donor pays ~$0.0001–$0.01 in network fees
     - Bot monitors via free public APIs (Solscan, Basescan, 4byte)
     - No API keys, no exchange, fully on-chain

  B. Kraken deposit memo
     - Donor pays 0% (if sending from Kraken to Kraken)
     - Bot monitors via Kraken REST API (free, uses bot's existing Kraken credentials)
     - Exchange-dependent but convenient for existing users

  C. Lightning Network (near-zero fee, opt-in)
     - Donor pays ~$0.001–$0.01 in routing fees
     - Bot monitors via LND/c-lightning REST or LNbits API (if node running)
     - Not "free" to set up (requires LN node) but free for donors

  D. Auto-donation (internal accounting)
     - No donor action needed; bot allocates % of realized profits to donation address
     - Completely free — no external monitoring
     - Reduces net bot returns by design

Usage:
  python3 donation_monitor.py           # Interactive menu
  python3 donation_monitor.py check     # One-shot balance check
  python3 donation_monitor.py serve     # Run as background monitor (polls every N min)

Configuration:
  Edit DONATION_ADDRESSES below to set your real wallet addresses.
  For Kraken (Option B), set KRAKEN_API_KEY / KRAKEN_API_SECRET in kraken.env.
"""
import os
import json
import time
import hashlib
import hmac
import requests
from decimal import Decimal
from datetime import datetime, timezone
from urllib.parse import urlencode

# ──────────────────────────────────────────────────────────────────────────────
# CONFIGURATION — replace with your real addresses
# ──────────────────────────────────────────────────────────────────────────────

DONATION_ADDRESSES = {
    # Option A: Direct crypto addresses
    "solana": {
        "address": "6N8tA5Q4oQ7oQ8Q5Q6Q7Q8Q9Q0Q1Q2Q3Q4Q5Q6Q7Q8",  # ← REPLACE with your Solana wallet
        "label": "Solana (SOL / USDC)",
        "explorer": "https://solscan.io/account/{addr}",
        "api": "https://public-api.solscan.dev/account?account={addr}",
        "tokens_to_track": ["EPjFWdd5AufqSSqeM2qN1xzwrwLEwK1ANfNvM4oQ9rZJ",  # USDC
                            "Es9vMFrzaCERmJfrF4H2FYD4KConE8NSKkjSo6kSyVDF"],  # USDT
    },
    "base": {
        "address": "0x1234567890123456789012345678901234567890",  # ← REPLACE with your Base wallet
        "label": "Base (ETH / USDbC / USDC)",
        "explorer": "https://basescan.org/address/{addr}",
        "api": "https://base-mainnet.public.blastapi.io",
        "rpc_method": "eth_getBalance",
        "tokens_to_track": ["0xdC035D4567346484301A00e2A5F23207454A4F75"],  # USDbC on Base
    },
    "arbitrum": {
        "address": "0x1234567890123456789012345678901234567890",  # ← REPLACE with your Arbitrum wallet
        "label": "Arbitrum (ETH / USDC)",
        "explorer": "https://arbiscan.io/address/{addr}",
        "api": "https://arb1.arbitrum.io/rpc",
        "rpc_method": "eth_getBalance",
        "tokens_to_track": ["0xFF970a6d257259ec5aA1c543f4d34d0c0c99d0fb"],  # USDC on Arbitrum
    },
    # Option B: Kraken deposit memo
    "kraken": {
        "label": "Kraken deposit memo",
        "note": "Send any asset to your Kraken account; the bot monitors the deposit memo.",
        "api_url": "https://api.kraken.com/0/private/DepositStatus",
        "fee_note": "0% for intra-Kraken transfers; standard fees for external deposits",
    },
    # Option C: Lightning Network (LNbits or LND)
    "lightning": {
        "label": "Lightning Network (BTC)",
        "note": "Bot monitors LN node (LND or LNbits) for incoming payments.",
        "api_url": "http://127.0.0.1:5000",  # LNbits API — change to your node
        "fee_note": "~$0.001 per payment (routing fee)",
    },
    # Option D: Auto-donation
    "auto": {
        "label": "Auto-donation (percent of profits)",
        "note": "Bot automatically allocates a % of realized profits to a donation address.",
        "default_pct": 0.01,  # 1% of realized PnL
    },
    # Option E: PayPal (fiat tithe / offering — free onramp for non-crypto donors)
    "paypal": {
        "label": "PayPal Tithe / Offering",
        "email": "donations@nikola-bot.org",
        "donate_link": "https://www.paypal.me/LucasMurr369",
        "note": "Fiat tithe or offering — no crypto wallet needed. PayPal covers processing fees; nothing required.",
        "fee_note": "~$0.30 + 2.9% per transaction (covered by PayPal, not the donor)",
    },
}

# PayPal Tithe / Offering slot — referenced by the HTML reporter (--export-html).
DONATION_PAYPAL = DONATION_ADDRESSES["paypal"]


def paypal_qr_url(data: str | None = None, size: int = 200) -> str:
    """qrserver.com URL that renders a scannable QR for the PayPal tithe link.

    Step 5 (--export-html) embeds this in an ``<img src>`` so desktop/mobile
    cameras can scan it. Zero Python deps. For a fully offline HTML report,
    install the ``qrcode`` package (add to requirements.txt) and generate an
    inline SVG/base64 string here instead.
    """
    from urllib.parse import quote
    link = data or DONATION_PAYPAL["donate_link"]
    return (f"https://api.qrserver.com/v1/create-qr-code/"
            f"?size={size}x{size}&data={quote(link)}")


def paypal_donation_info() -> dict:
    """Structured PayPal tithe/offering payload for the HTML reporter."""
    return {
        "label": DONATION_PAYPAL["label"],
        "email": DONATION_PAYPAL["email"],
        "donate_link": DONATION_PAYPAL["donate_link"],
        "note": DONATION_PAYPAL["note"],
        "qr_url": paypal_qr_url(),
        "qr_alt": "Tithe / Donation via PayPal - scan to give",
    }


# Kraken credentials (from kraken.env or environment)
KRAKEN_API_KEY = os.getenv("KRAKEN_API_KEY", "")
KRAKEN_API_SECRET = os.getenv("KRAKEN_API_SECRET", "")

# Poll interval for background monitoring
POLL_INTERVAL_SEC = 300  # 5 minutes


# ──────────────────────────────────────────────────────────────────────────────
# QR CODE — generates via free external API (no local deps needed)
# ──────────────────────────────────────────────────────────────────────────────

class QRCode:
    """QR code URL generator using the free qrserver API."""

    @staticmethod
    def url(data: str, size: int = 200) -> str:
        """Return a URL that renders a QR code image for the given data."""
        from urllib.parse import quote
        return f"https://api.qrserver.com/v1/api/QRCode/?size={size}x{size}&data={quote(data)}"

    @staticmethod
    def svg(data: str, size: int = 200) -> str:
        """Generate a minimal QR code as inline SVG (no external dependency).
        Uses a simple bitmap approach for basic text."""
        # For production, use the qrserver URL. SVG rendering requires a full
        # QR encoder which is beyond scope of this minimal implementation.
        return QRCode.url(data, size)


# ──────────────────────────────────────────────────────────────────────────────
# SOLANA MONITOR (Option A)
# ──────────────────────────────────────────────────────────────────────────────

class SolanaMonitor:
    """Monitor a Solana address for SOL and SPL-token (USDC/USDT) donations."""

    def __init__(self, address: str):
        self.address = address

    def check_sol_balance(self) -> dict:
        """Check native SOL balance via Solscan public API."""
        try:
            resp = requests.get(
                f"https://public-api.solscan.dev/account?account={self.address}",
                timeout=10,
            )
            data = resp.json()
            lamports = int(data.get("lamports", {}).get("lamports", 0)) if isinstance(data, dict) else 0
            sol = lamports / 1e9
            return {"asset": "SOL", "balance": sol, "usd": sol * 150}  # rough SOL price
        except Exception as e:
            return {"asset": "SOL", "balance": 0, "error": str(e)}

    def check_token_balances(self, token_mints: list) -> list:
        """Check SPL token balances via Solscan public API."""
        results = []
        try:
            resp = requests.get(
                f"https://public-api.solscan.dev/account/tokens?account={self.address}",
                timeout=10,
            )
            tokens = resp.json() if resp.status_code == 200 else []
            for mint in token_mints:
                found = next((t for t in tokens if t.get("tokenAddress", {}).get("address") == mint), None)
                if found:
                    amount = int(found.get("amount", "0")) / (10 ** found.get("decimals", 6))
                    results.append({"asset": found.get("tokenName", mint[:8]), "balance": amount})
                else:
                    results.append({"asset": mint[:8], "balance": 0})
        except Exception as e:
            for mint in token_mints:
                results.append({"asset": mint[:8], "balance": 0, "error": str(e)})
        return results

    def total_usd(self, sol_price: float = 150, usdc_price: float = 1.0) -> float:
        """Get total donation value in USD."""
        sol_data = self.check_sol_balance()
        token_data = self.check_token_balances(DONATION_ADDRESSES["solana"]["tokens_to_track"])
        total = sol_data.get("usd", 0)
        for t in token_data:
            total += t.get("balance", 0) * usdc_price
        return total


# ──────────────────────────────────────────────────────────────────────────────
# ETHEREUM / BASE MONITOR (Option A)
# ──────────────────────────────────────────────────────────────────────────────

class EthereumMonitor:
    """Monitor an Ethereum-compatible address (Base, Arbitrum, etc.) for ETH and ERC-20 donations."""

    def __init__(self, address: str, rpc_url: str):
        self.address = address.lower()
        self.rpc_url = rpc_url

    def _rpc(self, method: str, params: list) -> dict:
        """Make a JSON-RPC call to a public endpoint."""
        payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
        resp = requests.post(self.rpc_url, json=payload, timeout=10)
        return resp.json()

    def check_eth_balance(self) -> dict:
        """Check native ETH balance."""
        try:
            result = self._rpc("eth_getBalance", [self.address, "latest"])
            wei = int(result.get("result", "0x0"), 16)
            eth = wei / 1e18
            return {"asset": "ETH", "balance": eth, "usd": eth * 3000}  # rough ETH price
        except Exception as e:
            return {"asset": "ETH", "balance": 0, "error": str(e)}

    def check_token_balance(self, token_address: str, abi: str = None) -> dict:
        """Check ERC-20 token balance."""
        try:
            # Standard ERC-20 balanceOf abisec
            erc20_abi = abi or json.dumps([{"constant": True, "inputs": [{"name": "account", "type": "address"}],
                  "name": "balanceOf", "type": "function", "payable": False, "stateMutability": "nonpayable"},
                  {"constant": True, "inputs": [{"name": "account", "type": "address"}],
                   "name": "balanceOf", "type": "function", "payable": False, "stateMutability": "nonpayable"}])

            # Call balanceOf via eth_call
            # Simplified: use a static call with the standard 0x70a08231 selector
            balance_resp = self._rpc("eth_call", [{
                "to": token_address,
                "data": "0x70a08231000000000000000000000000" + self.address[2:]
            }, "latest"])
            result = balance_resp.get("result", "0x0")
            if result == "0x" or len(result) <= 2:
                return {"asset": token_address[:8], "balance": 0}
            raw = int(result, 16)
            # Most USDC/USDT tokens have 6 decimals
            decimals = 6
            balance = raw / (10 ** decimals)
            return {"asset": token_address[:8], "balance": balance, "usd": balance * 1.0}
        except Exception as e:
            return {"asset": token_address[:8], "balance": 0, "error": str(e)}


# ──────────────────────────────────────────────────────────────────────────────
# KRAKEN DEPOSIT MONITOR (Option B)
# ──────────────────────────────────────────────────────────────────────────────

class KrakenDepositMonitor:
    """Monitor Kraken deposit status via the REST API using the bot's existing credentials."""

    def __init__(self, api_key: str = None, api_secret: str = None):
        self.api_key = api_key or KRAKEN_API_KEY
        self.api_secret = api_secret or KRAKEN_API_SECRET

    def _sign(self, uri_path: str, data: dict) -> tuple:
        """Generate Kraken API signature."""
        if not self.api_key or not self.api_secret:
            return None, None

        try:
            # Validate that the secret is valid base64
            import base64 as b64
            b64.b64decode(self.api_secret)
        except Exception:
            return None, None

        nonce = str(int(time.time() * 1000))
        data["nonce"] = nonce
        postdata = urlencode(data)
        encoded = (nonce + postdata).encode('utf-8')
        signature = hmac.new(
            base64.b64decode(self.api_secret),
            uri_path.encode() + hashlib.sha256(encoded).digest(),
            hashlib.sha256
        ).digest()
        return base64.b64encode(signature).decode(), nonce

    def check_deposits(self, asset: str = None, since: int = None) -> list:
        """Check deposit status. Returns list of deposit records."""
        if not self.api_key or not self.api_secret:
            return [{"error": "Kraken API credentials not set in kraken.env"}]

        import base64 as b64mod
        uri_path = "/0/private/DepositStatus"
        data = {"asset": asset} if asset else {}
        if since:
            data["ofs"] = since

        signature, nonce = self._sign(uri_path, data)
        if signature is None:
            return [{"error": "API credentials missing"}]

        api_url = f"https://api.kraken.com{uri_path}"
        headers = {"API-Key": self.api_key, "API-Sign": signature}

        try:
            resp = requests.post(api_url, headers=headers, data=data, timeout=15)
            result = resp.json()
            if result.get("error"):
                return [{"error": str(result["error"])}]
            deposits = result.get("result", [])
            return deposits
        except Exception as e:
            return [{"error": str(e)}]

    def list_deposit_methods(self, asset: str) -> list:
        """List available deposit methods (addresses + memos) for an asset."""
        if not self.api_key or not self.api_secret:
            return [{"error": "Kraken API credentials not set"}]

        uri_path = "/0/private/DepositMethods"
        data = {"asset": asset}
        signature, nonce = self._sign(uri_path, data)
        if signature is None:
            return [{"error": "API credentials missing"}]

        api_url = f"https://api.kraken.com{uri_path}"
        headers = {"API-Key": self.api_key, "API-Sign": signature}
        try:
            resp = requests.post(
                f"https://api.kraken.com{uri_path}",
                headers=headers, data=data, timeout=15
            )
            result = resp.json()
            methods = result.get("result", [])
            return methods
        except Exception as e:
            return [{"error": str(e)}]


# ──────────────────────────────────────────────────────────────────────────────
# LIGHTNING NETWORK MONITOR (Option C) — opt-in
# ──────────────────────────────────────────────────────────────────────────────

class LightningMonitor:
    """Monitor Lightning Network payments via LNbits REST API (or LND if configured)."""

    def __init__(self, api_url: str = None, api_key: str = None):
        self.api_url = (api_url or DONATION_ADDRESSES["lightning"]["api_url"]).rstrip("/")
        self.api_key = api_key  # LNbits invoice key

    def check_payments(self) -> list:
        """Check recent Lightning payments (non-custodial LNbits)."""
        try:
            headers = {"X-Api-Key": self.api_key} if self.api_key else {}
            resp = requests.get(f"{self.api_url}/api/v1/payments", headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("data", data.get("payments", []))
            return [{"error": f"HTTP {resp.status_code}"}]
        except Exception as e:
            return [{"error": str(e)}]

    def create_invoice(self, amount_sat: int, description: str = "HERMES donation") -> dict:
        """Create a Lightning invoice for a donor to pay."""
        if not self.api_key:
            return {"error": "LNbits API key not configured"}
        try:
            resp = requests.post(
                f"{self.api_url}/api/v1/payments",
                headers={"X-Api-Key": self.api_key},
                json={"out": False, "amount": str(amount_sat), "memo": description},
                timeout=10,
            )
            return resp.json()
        except Exception as e:
            return {"error": str(e)}


# ──────────────────────────────────────────────────────────────────────────────
# AUTO-DONATION (Option D) — internal accounting
# ──────────────────────────────────────────────────────────────────────────────

class AutoDonation:
    """Tracks auto-donated portion of realized bot profits.

    Usage in live bot:
      >>> auto = AutoDonation(donation_pct=0.01, address="0x...")
      >>> auto.record_realized_pnl(100.0)  # called when a trade closes with +$100 PnL
      >>> auto.accumulated()  # current accumulated donation amount
    """

    def __init__(self, donation_pct: float = 0.01, address: str = None):
        self.donation_pct = donation_pct
        self.donation_address = address
        self.accumulated_usd = 0.0
        self.history = []

    def record_realized_pnl(self, pnl: float, pair: str = ""):
        """Call when a trade closes with realized PnL. Only positive PnL is donated."""
        if pnl > 0:
            donated = pnl * self.donation_pct
            self.accumulated_usd += donated
            self.history.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "pair": pair,
                "pnl": pnl,
                "donated": donated,
                "accumulated": self.accumulated_usd,
            })
        return self.accumulated_usd

    def accumulated(self) -> float:
        return self.accumulated_usd


# ──────────────────────────────────────────────────────────────────────────────
# DISPLAY — donor-facing info
# ──────────────────────────────────────────────────────────────────────────────

def print_donation_info():
    """Print all donation options for users."""
    print("\n" + "=" * 72)
    print(" TITHE / OFFERING / DONATION OPTIONS")
    print("=" * 72)
    print("\n  Nikola is 100% free. Any tithe, offering, or donation is optional")
    print("  and completely free either way. Three simple ways to give:\n")
    print("  Option 1 (Click):  Open https://www.paypal.me/LucasMurr369 in your browser")
    print("                      (no app, no crypto wallet, no signup)")
    print("  Option 2 (Scan):   Open the PayPal QR in your phone camera")
    print(f"                      {paypal_qr_url(size=200)}")
    print("  Option 3 (Crypto): Run `python3 donation_monitor.py info`")
    print("                      for wallet (SOL/Base/ARB), Kraken memo, and Lightning")
    print("\n" + "-" * 72)

    for key, info in DONATION_ADDRESSES.items():
        label = info.get("label", key)
        print(f"\n  [{key.upper()}] {label}")
        print(f"  {info.get('note', '')}")

        if key in ("solana", "base", "arbitrum"):
            addr = info["address"]
            # Show truncated address
            if key == "solana":
                display = f"{addr[:12]}...{addr[-12:]}"
            else:
                display = f"{addr[:10]}...{addr[-10:]}"

            print(f"  Address: {display}")
            print(f"  Full:   {addr}")
            qr = QRCode.url(addr if key == "solana" else addr, 150)
            print(f"  QR:     {qr}")
            explorer = info.get("explorer", "").format(addr=addr)
            print(f"  Explorer: {explorer}")

            if "tokens_to_track" in info:
                for token in info["tokens_to_track"]:
                    print(f"  Token: {token[:12]}...")

        if key == "kraken":
            print(f"  {info.get('fee_note', '')}")
            print(f"  API URL: {info['api_url']}")
            print("  Setup: Set KRAKEN_API_KEY + KRAKEN_API_SECRET in kraken.env")

        if key == "lightning":
            print(f"  API URL: {info['api_url']}")
            print(f"  {info.get('fee_note', '')}")

        if key == "auto":
            print(f"  Default: {info['default_pct']*100}% of realized profits")

        if key == "paypal":
            print(f"  Tithe/Offering via PayPal — {info['donate_link']}")
            print(f"  Support email:   {info['email']}")
            print(f"  QR for reports:  {paypal_qr_url(size=150)}")
            print(f"  {info.get('fee_note', '')}")

    print("\n" + "=" * 72)
    print(" PayPal Tithe: ~$0.30 + 2.9% processing (optional for the donor)")
    print(" Solana Base: ~$0.0001-0.01 per donation | Kraken: 0% intra-Kraken")
    print(" Lightning: ~$0.001 per payment | Auto: 0% (internal accounting)")
    print("=" * 72)


def check_all_balances():
    """One-shot check of all configured donation addresses."""
    results = {}
    for key, info in DONATION_ADDRESSES.items():
        if key == "solana":
            mon = SolanaMonitor(info["address"])
            results[key] = {
                "sol": mon.check_sol_balance(),
                "tokens": mon.check_token_balances(info["tokens_to_track"]),
                "total_usd": mon.total_usd(),
            }
        elif key in ("base", "arbitrum"):
            mon = EthereumMonitor(info["address"], info["api"])
            results[key] = {
                "eth": mon.check_eth_balance(),
                "tokens": [mon.check_token_balance(t) for t in info["tokens_to_track"]],
            }
        elif key == "kraken":
            mon = KrakenDepositMonitor()
            if not KRAKEN_API_KEY or not KRAKEN_API_SECRET:
                results[key] = {"deposits": [{"error": "Kraken API credentials not configured — set KRAKEN_API_KEY + KRAKEN_API_SECRET in kraken.env"}]}
            else:
                results[key] = {
                    "deposits": mon.check_deposits(since=int(time.time() - 30 * 24 * 3600)),
                }
        elif key == "lightning":
            mon = LightningMonitor()
            results[key] = {
                "payments": mon.check_payments()[:10],
            }

    print("\n" + "=" * 72)
    print(" DONATION BALANCES")
    print("=" * 72)
    for key, data in results.items():
        label = DONATION_ADDRESSES[key]["label"]
        print(f"\n  [{key.upper()}] {label}")
        # Check for errors at top level
        for subkey, val in data.items():
            if isinstance(val, list):
                for v in val:
                    if isinstance(v, dict) and "error" in v:
                        print(f"    {subkey}: {v['error']}")
                    elif isinstance(v, dict) and "balance" in v:
                        print(f"    {v.get('asset', '?')}: {v.get('balance', 0):.6f}")
            elif isinstance(val, dict):
                if "error" in val:
                    print(f"    {subkey}: {val['error']}")
                elif "balance" in val:
                    usd = val.get("usd", 0)
                    print(f"    {val.get('asset', '?')}: {val.get('balance', 0):.6f} (${usd:.2f})")
                elif "total_usd" in val:
                    print(f"    Total: ${val['total_usd']:.2f}")

    total_all = sum(
        results[k].get("total_usd", 0) for k in ("solana",)
    )
    print(f"\n  Total (blockchain): ${total_all:.2f}")
    print("=" * 72)
    return results


def run_monitor(interval_sec: int = POLL_INTERVAL_SEC):
    """Run as background monitor, polling every N seconds."""
    print("  Donation monitor running (Ctrl+C to stop)")
    print(f"  Polling every {interval_sec}s")
    print()
    while True:
        try:
            check_all_balances()
            print(f"\n  Next check in {interval_sec}s...")
            time.sleep(interval_sec)
        except KeyboardInterrupt:
            print("\n  Monitor stopped.")
            break
        except Exception as e:
            print(f"  [ERROR] {e}")
            time.sleep(interval_sec)


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    # Need base64 for Kraken signing
    import base64

    if len(sys.argv) < 2:
        print_donation_info()
        print("\n  Usage: python3 donation_monitor.py [check|serve|info]")
    elif sys.argv[1] == "check":
        check_all_balances()
    elif sys.argv[1] == "serve":
        interval = int(sys.argv[2]) if len(sys.argv) > 2 else POLL_INTERVAL_SEC
        run_monitor(interval)
    elif sys.argv[1] == "info":
        print_donation_info()
    else:
        print(f"  Unknown command: {sys.argv[1]}")
        print(f"  Usage: python3 donation_monitor.py [check|serve|info]")
