#!/usr/bin/env python3
"""
binance_futures_bot.py

Python bot for Binance Futures Testnet (USDT-M).
Supports MARKET and LIMIT orders, BUY and SELL sides.
Command-line interface for placing orders.
Logs events and errors.
"""

import argparse
import hashlib
import hmac
import logging
from logging.handlers import RotatingFileHandler
import time
import requests
import sys
from urllib.parse import urlencode
import json
import math

BASE_URL = "https://testnet.binancefuture.com"

# Logging setup
logger = logging.getLogger("FuturesBot")
logger.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s')

# Console handler
ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.INFO)
ch.setFormatter(formatter)
logger.addHandler(ch)

# File handler
fh = RotatingFileHandler("futures_bot.log", maxBytes=2_000_000, backupCount=3)
fh.setLevel(logging.DEBUG)
fh.setFormatter(formatter)
logger.addHandler(fh)

class BinanceFuturesClient:
    def __init__(self, api_key, api_secret, base_url=BASE_URL, recv_window=5000):
        self.api_key = api_key
        self.api_secret = api_secret.encode()
        self.base_url = base_url.rstrip("/")
        self.recv_window = recv_window
        self.session = requests.Session()
        self.session.headers.update({"X-MBX-APIKEY": self.api_key})

    def _sign(self, params: dict) -> str:
        query_string = urlencode(params, doseq=True)
        return hmac.new(self.api_secret, query_string.encode(), hashlib.sha256).hexdigest()

    def _request(self, method, path, params=None):
        url = f"{self.base_url}{path}"
        try:
            logger.debug(f"{method} {url} | params: {params}")
            if method == "POST":
                resp = self.session.post(url, params=params, timeout=10)
            else:
                resp = self.session.get(url, params=params, timeout=10)
            resp.raise_for_status()
            logger.debug(f"Response ({resp.status_code}): {resp.text}")
            return resp.json()
        except requests.RequestException as e:
            logger.error(f"HTTP request error: {e}")
            raise

    def get_symbol_info(self, symbol):
        info = self._request("GET", "/fapi/v1/exchangeInfo")
        return next(s for s in info["symbols"] if s["symbol"] == symbol.upper())

    def place_order(self, symbol, side, order_type, quantity, price=None, time_in_force="GTC"):
        symbol_info = self.get_symbol_info(symbol)
        step_size = tick_size = min_notional = None
        for f in symbol_info["filters"]:
            if f["filterType"] == "LOT_SIZE":
                step_size = float(f["stepSize"])
            elif f["filterType"] == "PRICE_FILTER":
                tick_size = float(f["tickSize"])
            elif f["filterType"] == "MIN_NOTIONAL":
                min_notional = float(f.get("minNotional") or 0)

        if not step_size or not tick_size:
            raise ValueError("Failed to fetch step_size or tick_size for symbol")

        # Round functions
        def round_down(value, step):
            return math.floor(value / step) * step

        quantity = round_down(quantity, step_size)
        if price is not None:
            price = round_down(price, tick_size)

        if order_type.upper() == "LIMIT" and (quantity * price) < (min_notional or 0):
            raise ValueError(f"Order notional {quantity * price} below minimum {min_notional}")

        params = {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "type": order_type.upper(),
            "quantity": str(quantity),
            "timestamp": int(time.time() * 1000),
            "recvWindow": self.recv_window
        }

        if order_type.upper() == "LIMIT":
            if price is None:
                raise ValueError("Limit order requires --price")
            params.update({"price": str(price), "timeInForce": time_in_force})

        params["signature"] = self._sign(params)
        return self._request("POST", "/fapi/v1/order", params)

def parse_args():
    parser = argparse.ArgumentParser(description="Binance Futures Testnet Bot")
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--api-secret", required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--side", required=True, choices=["buy", "sell"])
    parser.add_argument("--type", required=True, choices=["market", "limit"])
    parser.add_argument("--quantity", type=float, required=True)
    parser.add_argument("--price", type=float)
    parser.add_argument("--timeinforce", default="GTC", choices=["GTC", "IOC", "FOK"])
    return parser.parse_args()

def main():
    args = parse_args()
    client = BinanceFuturesClient(args.api_key, args.api_secret)

    try:
        order = client.place_order(
            symbol=args.symbol,
            side=args.side,
            order_type=args.type,
            quantity=args.quantity,
            price=args.price,
            time_in_force=args.timeinforce
        )
        logger.info("Order placed successfully!")
        print(json.dumps(order, indent=2))
    except Exception as e:
        logger.error(f"Failed to place order: {e}")
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
