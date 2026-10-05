

import pytest


#  Regression: bookTicker API path bug
# =========================================================================== #


class TestBookTickerPath:
    """
    Regression test for the bookTicker endpoint path bug discovered during audit.

    The correct Binance Futures path is:
        /fapi/v1/ticker/bookTicker   (returns list of all book tickers)

    The incorrect path used before the audit fix:
        /fapi/v1/bookTicker          (404 on Binance Futures)

    This class ensures the client always uses the correct path.
    """

    def test_book_ticker_path_literal_in_source(self):
        """
        Verify the correct path string appears in binance_client.py source
        and the incorrect path does not. Static code check against regressions.
        """
        import inspect
        from universe import binance_client
        source = inspect.getsource(binance_client)
        assert "/fapi/v1/ticker/bookTicker" in source, (
            "The correct bookTicker path '/fapi/v1/ticker/bookTicker' "
            "was not found in binance_client.py source."
        )
        # The old broken path must NOT appear as a standalone endpoint string
        assert '"/fapi/v1/bookTicker"' not in source, (
            "The incorrect path '/fapi/v1/bookTicker' appears in source — "
            "this causes HTTP 404 on Binance Futures."
        )

    @pytest.mark.asyncio
    async def test_get_all_book_tickers_calls_correct_path(self):
        """
        get_all_book_tickers() must call /fapi/v1/ticker/bookTicker,
        not /fapi/v1/bookTicker.
        """
        from universe.binance_client import BinanceFuturesClient
        from universe.config import config as cfg

        correct_path = "/fapi/v1/ticker/bookTicker"
        calls_made: list[str] = []

        async def mock_get(path: str, **kwargs):
            calls_made.append(path)
            return [
                {"symbol": "BTCUSDT", "bidPrice": "50000", "askPrice": "50001",
                 "bidQty": "1", "askQty": "1"},
            ]

        async with BinanceFuturesClient(cfg) as client:
            client._get = mock_get  # type: ignore[method-assign]
            result = await client.get_all_book_tickers()

        assert len(calls_made) == 1, f"Expected 1 path call, got: {calls_made}"
        assert calls_made[0] == correct_path, (
            f"Expected '{correct_path}', got '{calls_made[0]}'. "
            "'/fapi/v1/bookTicker' returns HTTP 404 on Binance Futures."
        )
        assert result[0]["symbol"] == "BTCUSDT"
