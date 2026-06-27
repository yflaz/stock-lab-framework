from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.market_data import fetch_a_share_quote


class AShareQuotePathTests(unittest.TestCase):
    def test_single_symbol_prefers_tencent_fast_path(self):
        with patch("core.market_data.fetch_tencent_a_quotes") as mock_tencent, patch(
            "core.market_data.fetch_akshare_a_quotes"
        ) as mock_ak:
            mock_tencent.return_value = (
                {
                    "600519": {
                        "symbol": "600519",
                        "name": "贵州茅台",
                        "market": "A",
                        "latest": 1234.5,
                        "prev_close": 1200.0,
                        "change_pct": 2.88,
                        "data_source": "Tencent qt.gtimg.cn fallback",
                    }
                },
                {"source": "Tencent qt.gtimg.cn fallback", "ok": True, "message": ""},
            )
            mock_ak.return_value = ({}, {"source": "AKShare stock_zh_a_spot_em", "ok": False, "message": "should not be used"})

            quote, health = fetch_a_share_quote("600519")

            self.assertEqual(quote["symbol"], "600519")
            self.assertTrue(health["ok"])
            mock_tencent.assert_called_once_with(["600519"])
            mock_ak.assert_not_called()

    def test_single_symbol_falls_back_to_akshare_when_tencent_misses(self):
        with patch("core.market_data.fetch_tencent_a_quotes") as mock_tencent, patch(
            "core.market_data.fetch_akshare_a_quotes"
        ) as mock_ak:
            mock_tencent.return_value = ({}, {"source": "Tencent qt.gtimg.cn fallback", "ok": False, "message": "timeout"})
            mock_ak.return_value = (
                {
                    "600519": {
                        "symbol": "600519",
                        "name": "贵州茅台",
                        "market": "A",
                        "latest": 1234.5,
                        "prev_close": 1200.0,
                        "change_pct": 2.88,
                        "data_source": "AKShare stock_zh_a_spot_em",
                    }
                },
                {"source": "AKShare stock_zh_a_spot_em", "ok": True, "message": ""},
            )

            quote, health = fetch_a_share_quote("600519")

            self.assertEqual(quote["data_source"], "AKShare stock_zh_a_spot_em")
            self.assertIn("Tencent failed first", health["message"])
            mock_tencent.assert_called_once_with(["600519"])
            mock_ak.assert_called_once_with(["600519"])


if __name__ == "__main__":
    unittest.main()
