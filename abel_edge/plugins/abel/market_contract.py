"""Public market-node and day-bar request normalization for Abel."""

from __future__ import annotations

CRYPTO_ALIASES = {"BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "AVAX"}
SUPPORTED_FIELDS = {"price", "volume"}
SUPPORTED_MARKET_FIELDS = {"open", "high", "low", "close", "volume"}


def normalize_public_node_id(value: str, *, default_field: str = "price") -> str:
    raw = value.strip()
    if not raw:
        raise ValueError("Ticker or node id cannot be empty.")
    if default_field not in SUPPORTED_FIELDS:
        raise ValueError(f"Unsupported field '{default_field}'.")

    normalized = raw.upper()
    ticker, dot, suffix = normalized.rpartition(".")
    if dot:
        field = suffix.lower()
        if field not in SUPPORTED_FIELDS:
            raise ValueError("Abel node ids must end with .price or .volume.")
        return f"{ticker}.{field}"

    ticker, underscore, suffix = normalized.rpartition("_")
    if underscore:
        field = suffix.lower()
        if field == "close":
            return f"{ticker}.price"
        if field == "volume":
            return f"{ticker}.volume"
        raise ValueError("Abel node ids must use .price or .volume.")

    if normalized in CRYPTO_ALIASES:
        normalized = f"{normalized}USD"
    return f"{normalized}.{default_field}"


def split_public_node_id(node_id: str) -> tuple[str, str]:
    ticker, _, field = normalize_public_node_id(node_id).rpartition(".")
    return ticker, field


def normalize_market_fields(fields: list[str] | None) -> list[str]:
    requested = fields or ["open", "high", "low", "close", "volume"]
    normalized = []
    seen = set()
    for field in requested:
        name = str(field).strip().lower()
        if name in {"timestamp", "symbol", "date"}:
            continue
        if name not in SUPPORTED_MARKET_FIELDS:
            continue
        if name not in seen:
            seen.add(name)
            normalized.append(name)
    if not normalized:
        return ["open", "high", "low", "close", "volume"]
    return normalized


def normalize_market_symbol(value: str) -> str:
    """Normalize public aliases without destroying exchange-qualified tickers."""

    normalized = str(value or "").strip().upper()
    if not normalized:
        raise ValueError("Market symbol cannot be empty.")
    ticker, dot, suffix = normalized.rpartition(".")
    if dot and suffix.lower() in SUPPORTED_FIELDS:
        return ticker
    ticker, underscore, suffix = normalized.rpartition("_")
    if underscore and suffix.lower() in {"price", "close", "volume"}:
        return ticker
    if normalized in CRYPTO_ALIASES:
        return f"{normalized}USD"
    return normalized
