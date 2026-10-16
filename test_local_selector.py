import unittest
import json
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd

from local_selector import AkshareProvider, Selector, is_excluded_name, is_limit_close, is_mainboard, limit_price, main


class SelectorUtilityTests(unittest.TestCase):
    def test_mainboard_codes(self):
        self.assertTrue(is_mainboard("000001"))
        self.assertTrue(is_mainboard("600000"))
        self.assertFalse(is_mainboard("300001"))
        self.assertFalse(is_mainboard("688001"))

    def test_limit_price(self):
        self.assertEqual(limit_price(10.00), 11.00)
        self.assertEqual(limit_price(7.63), 8.39)

    def test_limit_close(self):
        self.assertTrue(is_limit_close(11.00, 10.00))
        self.assertTrue(is_limit_close(10.99, 10.00))
        self.assertFalse(is_limit_close(10.80, 10.00))

    def test_excluded_names(self):
        self.assertTrue(is_excluded_name("ST测试"))
        self.assertTrue(is_excluded_name("*ST测试"))
        self.assertTrue(is_excluded_name("退市测试"))
        self.assertFalse(is_excluded_name("平安银行"))


class ProviderRecoveryTests(unittest.TestCase):
    def test_daily_fallback_preserves_units_and_avoids_failed_source(self):
        data = pd.DataFrame([{
            "date": date(2026, 10, 15), "open": 10, "close": 11,
            "high": 11, "low": 10, "volume": 123400,
            "amount": 1300000, "turnover": 0.056,
        }])
        with tempfile.TemporaryDirectory() as directory:
            provider = AkshareProvider(Path(directory), request_interval=0)
            with patch("local_selector.ak.stock_zh_a_hist", side_effect=ConnectionError("disconnected")) as eastmoney, patch("local_selector.ak.stock_zh_a_daily", return_value=data) as sina, patch("local_selector.time_module.sleep"):
                history = provider.daily_history("000626", date(2026, 10, 15))
                provider.daily_history("600000", date(2026, 10, 15))
                provider.daily_history("000626", date(2026, 10, 15))
            self.assertEqual(eastmoney.call_count, 3)
            self.assertEqual(sina.call_count, 2)
            self.assertEqual(sina.call_args.kwargs["symbol"], "sh600000")
            self.assertEqual(history.iloc[-1]["volume"], 1234)
            self.assertAlmostEqual(history.iloc[-1]["turnover"], 5.6)
            self.assertEqual(history.iloc[-1]["amount"], 1300000)

    def test_empty_daily_is_not_cached(self):
        with tempfile.TemporaryDirectory() as directory:
            provider = AkshareProvider(Path(directory), daily_source="sina")
            with patch("local_selector.ak.stock_zh_a_daily", return_value=pd.DataFrame()):
                with self.assertRaisesRegex(RuntimeError, "未返回"):
                    provider.daily_history("000626", date(2026, 10, 15))
            self.assertEqual(list(Path(directory).glob("*.pkl")), [])

    def test_auction_rejects_wrong_date_and_does_not_cache_it(self):
        data = pd.DataFrame([{"时间": "2026-10-16 09:25:00", "收盘": 11, "成交量": 100, "成交额": 110000}])
        with tempfile.TemporaryDirectory() as directory:
            provider = AkshareProvider(Path(directory), auction_source="eastmoney")
            with patch("local_selector.ak.stock_zh_a_hist_pre_min_em", return_value=data):
                with self.assertRaisesRegex(RuntimeError, "仅提供最近交易日数据"):
                    provider.auction("000626", date(2026, 10, 15))
            self.assertEqual(list(Path(directory).glob("*.pkl")), [])

    def test_auction_uses_only_requested_date_and_caches_valid_rows(self):
        data = pd.DataFrame([
            {"时间": "2026-10-15 09:25:00", "收盘": 11, "成交量": 100, "成交额": 110000},
            {"时间": "2026-10-16 09:25:00", "收盘": 12, "成交量": 200, "成交额": 240000},
        ])
        with tempfile.TemporaryDirectory() as directory:
            provider = AkshareProvider(Path(directory))
            with patch("local_selector.ak.stock_zh_a_hist_pre_min_em", return_value=data) as fetch:
                auction = provider.auction("000626", date(2026, 10, 15))
                cached = provider.auction("000626", date(2026, 10, 15))
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual(auction.price, 11)
            self.assertEqual(cached.timestamp, "2026-10-15T09:25:00")

    def test_auction_fallback_avoids_failed_source_for_remaining_stocks(self):
        data = pd.DataFrame([{"时间": "2026-10-16 09:25:00", "收盘": 11, "成交量": 100, "成交额": 110000}])
        with tempfile.TemporaryDirectory() as directory:
            provider = AkshareProvider(Path(directory), request_interval=0)
            with patch("local_selector.ak.stock_zh_a_hist_pre_min_em", side_effect=ConnectionError("disconnected")) as eastmoney, patch.object(provider, "_sina_auction", return_value=data) as sina, patch("local_selector.time_module.sleep"):
                auction = provider.auction("000626", date(2026, 10, 16))
                provider.auction("600000", date(2026, 10, 16))
            self.assertEqual(eastmoney.call_count, 3)
            self.assertEqual(sina.call_count, 2)
            self.assertEqual(auction.volume, 100)

    def test_wrong_date_from_eastmoney_uses_dated_sina_source(self):
        old = pd.DataFrame([{"时间": "2026-10-16 09:25:00"}])
        correct = pd.DataFrame([{"时间": "2026-10-15 09:25:00", "收盘": 11, "成交量": 100, "成交额": 110000}])
        with tempfile.TemporaryDirectory() as directory:
            provider = AkshareProvider(Path(directory), request_interval=0)
            with patch("local_selector.ak.stock_zh_a_hist_pre_min_em", return_value=old), patch.object(provider, "_sina_auction", return_value=correct):
                auction = provider.auction("000626", date(2026, 10, 15))
            self.assertEqual(auction.timestamp, "2026-10-15T09:25:00")

    def test_sina_auction_excludes_other_times_and_converts_shares_to_lots(self):
        records = [
            {"symbol": "sz000626", "ticktime": "09:15:00", "price": "99", "volume": "50000"},
            {"symbol": "sz000626", "ticktime": "09:25:00", "price": "10.9", "volume": "1200"},
            {"symbol": "sz000626", "ticktime": "09:25:03", "price": "11", "volume": "800"},
            {"symbol": "sz000626", "ticktime": "09:30:00", "price": "12", "volume": "90000"},
        ]
        response = Mock()
        response.json.return_value = records
        with patch("local_selector.requests.get", return_value=response) as fetch:
            data = AkshareProvider._sina_auction("000626", date(2026, 10, 16))
        self.assertEqual(data.iloc[0]["收盘"], 11)
        self.assertEqual(data.iloc[0]["成交量"], 20)
        self.assertEqual(data.iloc[0]["成交额"], 21880)
        self.assertEqual(fetch.call_args.kwargs["params"]["day"], "2026-10-16")
        self.assertEqual(fetch.call_args.kwargs["params"]["asc"], "1")

    def test_sina_does_not_use_regular_session_or_bad_payload_as_auction(self):
        invalid_cases = [
            [],
            {"error": "unavailable"},
            [{"symbol": "sz000626", "ticktime": "09:30:00", "price": "11", "volume": "100"}],
            [{"symbol": "sz000626", "ticktime": "09:25:00", "price": "bad", "volume": "100"}],
            [{"symbol": "sz000626", "ticktime": "09:25:00", "price": "11", "volume": "100"}] * 60,
        ]
        for records in invalid_cases:
            with self.subTest(records=records):
                response = Mock()
                response.json.return_value = records
                with patch("local_selector.requests.get", return_value=response):
                    with self.assertRaises(RuntimeError):
                        AkshareProvider._sina_auction("000626", date(2026, 10, 16))

    def test_failed_history_marks_cli_output_incomplete(self):
        def select_with_failure(selector, trade_date, strategies):
            selector._history("000626", date(2026, 10, 15), count=4)
            return []

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(AkshareProvider, "daily_history", side_effect=RuntimeError("disconnected")), patch.object(Selector, "select_all", select_with_failure), patch("builtins.print") as output:
                status = main(["--date", "2026-10-16", "--cache-dir", directory, "--output-dir", directory])
            payload = json.loads((Path(directory) / "picks_20261016.json").read_text(encoding="utf-8"))
            self.assertEqual(status, 2)
            self.assertEqual(payload["status"], "incomplete")
            self.assertIn("daily:000626", payload["data_errors"])
            self.assertFalse(any(call.args == ("没有符合条件的股票。",) for call in output.call_args_list))


if __name__ == "__main__":
    unittest.main()
