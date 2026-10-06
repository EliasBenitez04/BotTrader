import asyncio
import logging
from typing import Any

import httpx
import pandas as pd

from app.core.exceptions import BinanceAPIError, MarketDataError

logger = logging.getLogger(__name__)

SUPPORTED_INTERVALS = {
    "1m", "3m", "5m", "15m", "30m",
    "1h", "2h", "4h", "6h", "8h", "12h",
    "1d", "3d", "1w", "1M",
}


class BinanceMarketClient:
    def __init__(self, base_url: str, timeout_seconds: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=timeout_seconds)

    async def __aenter__(self) -> "BinanceMarketClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        last_error: Exception | None = None

        for attempt in range(3):
            try:
                response = await self._client.get(path, params=params)
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt == 2:
                    break
                await asyncio.sleep(2**attempt)
                continue

            if response.status_code == 418:
                raise BinanceAPIError("Binance temporarily banned this IP after rate-limit abuse")

            if response.status_code == 429:
                retry_after = min(float(response.headers.get("Retry-After", "1")), 10.0)
                if attempt == 2:
                    raise BinanceAPIError("Binance rate limit reached (HTTP 429)")
                await asyncio.sleep(max(retry_after, 1.0))
                continue

            if 500 <= response.status_code < 600:
                if attempt == 2:
                    raise BinanceAPIError(
                        f"Binance server error HTTP {response.status_code}: {response.text[:300]}"
                    )
                await asyncio.sleep(2**attempt)
                continue

            if response.status_code >= 400:
                raise BinanceAPIError(
                    f"Binance HTTP {response.status_code}: {response.text[:500]}"
                )

            return response.json()

        raise BinanceAPIError(f"Could not reach Binance: {last_error}")

    async def ping(self) -> bool:
        await self._get("/api/v3/ping")
        return True

    async def server_time_ms(self) -> int:
        payload = await self._get("/api/v3/time")
        return int(payload["serverTime"])

    async def ticker_price(self, symbol: str) -> float:
        payload = await self._get("/api/v3/ticker/price", {"symbol": symbol.upper()})
        try:
            return float(payload["price"])
        except (KeyError, TypeError, ValueError) as exc:
            raise MarketDataError(f"Invalid ticker response for {symbol}") from exc

    async def exchange_info(self, symbol: str | None = None) -> dict[str, Any]:
        params = {"symbol": symbol.upper()} if symbol else None
        payload = await self._get("/api/v3/exchangeInfo", params)
        if not isinstance(payload, dict):
            raise MarketDataError("Invalid exchangeInfo response")
        return payload

    async def klines(
        self,
        symbol: str,
        interval: str,
        *,
        limit: int = 500,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
    ) -> pd.DataFrame:
        if interval not in SUPPORTED_INTERVALS:
            raise ValueError(f"Unsupported Binance interval: {interval}")
        if not 1 <= limit <= 1000:
            raise ValueError("Binance kline limit must be between 1 and 1000")

        params: dict[str, Any] = {
            "symbol": symbol.upper(),
            "interval": interval,
            "limit": limit,
        }
        if start_time_ms is not None:
            params["startTime"] = int(start_time_ms)
        if end_time_ms is not None:
            params["endTime"] = int(end_time_ms)

        rows = await self._get("/api/v3/klines", params)
        return self._rows_to_frame(rows)

    async def historical_klines(
        self,
        symbol: str,
        interval: str,
        *,
        start_time_ms: int,
        end_time_ms: int,
        max_candles: int = 100_000,
    ) -> pd.DataFrame:
        if start_time_ms >= end_time_ms:
            raise ValueError("start_time_ms must be earlier than end_time_ms")

        frames: list[pd.DataFrame] = []
        cursor = int(start_time_ms)
        total = 0

        while cursor <= end_time_ms and total < max_candles:
            page = await self.klines(
                symbol,
                interval,
                limit=min(1000, max_candles - total),
                start_time_ms=cursor,
                end_time_ms=end_time_ms,
            )
            if page.empty:
                break

            frames.append(page)
            total += len(page)
            last_open_ms = int(page.iloc[-1]["open_time_ms"])
            next_cursor = last_open_ms + 1
            if next_cursor <= cursor:
                break
            cursor = next_cursor

            if len(page) < 1000:
                break

            await asyncio.sleep(0)

        if not frames:
            raise MarketDataError(
                f"No historical candles returned for {symbol.upper()} {interval}"
            )

        result = pd.concat(frames, ignore_index=True)
        result = result.drop_duplicates(subset=["open_time_ms"]).sort_values("open_time_ms")
        return result.reset_index(drop=True)

    @staticmethod
    def _rows_to_frame(rows: Any) -> pd.DataFrame:
        if not isinstance(rows, list):
            raise MarketDataError("Invalid Binance kline payload")

        columns = [
            "open_time_ms",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "close_time_ms",
            "quote_asset_volume",
            "trades",
            "taker_buy_base",
            "taker_buy_quote",
            "ignore",
        ]
        frame = pd.DataFrame(rows, columns=columns)
        if frame.empty:
            return frame

        for name in ["open", "high", "low", "close", "volume"]:
            frame[name] = pd.to_numeric(frame[name], errors="coerce")

        frame["open_time"] = pd.to_datetime(frame["open_time_ms"], unit="ms", utc=True)
        frame["close_time"] = pd.to_datetime(frame["close_time_ms"], unit="ms", utc=True)

        if frame[["open", "high", "low", "close", "volume"]].isna().any().any():
            raise MarketDataError("Binance returned non-numeric candle data")

        return frame
