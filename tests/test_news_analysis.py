from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.news_analysis import analyze_mapped_headlines, build_rule_news_analysis, build_symbol_news_context


class NewsAnalysisTests(unittest.TestCase):
    def test_rule_analysis_detects_positive_industry_cycle(self):
        item = {
            "title": "存储巨头竞相扩产 半导体设备或迎内外共振 多股业绩有望高增长",
            "source": "东方财富",
            "matched_themes": ["半导体"],
            "related_positions": [{"symbol": "123456", "name": "示例科技", "account_id": "a-share-paper"}],
            "related_watchlist": [],
            "related_position_symbols": ["123456"],
            "related_watch_symbols": [],
        }
        result = build_rule_news_analysis(item)
        self.assertEqual(result["sentiment"], "bullish")
        self.assertIn(result["event_type"], {"industry_cycle", "earnings_positive"})
        self.assertGreaterEqual(result["impact_score"], 3)

    def test_pipeline_stays_rule_only_without_api_key(self):
        mapped = [{
            "title": "券商板块拉升，市场风险偏好回暖",
            "source": "测试源",
            "matched_themes": ["金融"],
            "related_positions": [],
            "related_watchlist": [{"symbol": "654321", "name": "示例证券", "account_id": "a-share-paper"}],
            "related_position_symbols": [],
            "related_watch_symbols": ["654321"],
        }]
        pipeline = analyze_mapped_headlines(mapped, {"news_analysis": {"enable_llm": True, "llm": {"api_key": ""}}})
        self.assertEqual(pipeline["processing"]["mode"], "rule_only")
        self.assertEqual(pipeline["items"][0]["news_analysis"]["mode"], "rule_only")

    def test_symbol_news_context_matches_by_name(self):
        headlines = [
            {"title": "示例科技受益于半导体扩产预期", "source": "测试源", "url": "", "published_at": ""},
            {"title": " unrelated headline ", "source": "测试源", "url": "", "published_at": ""},
        ]
        context = build_symbol_news_context("123456", "示例科技", "半导体", headlines, {"news_analysis": {"enable_llm": False}})
        self.assertTrue(context["has_hits"])
        self.assertEqual(context["hit_count"], 1)


if __name__ == "__main__":
    unittest.main()
