#!/usr/bin/env python3
"""
測試 get_cb_balance_sheets() 的 fallback 邏輯
"""
import unittest
from unittest.mock import patch
from pathlib import Path

from config import FRED_CB_CACHE
from data_fetcher import get_cb_balance_sheets
from utils import save_text_cache


class TestFredFallback(unittest.TestCase):
    """測試 FRED 快取 fallback 機制"""

    def setUp(self):
        """測試前準備：設定快取內容"""
        # 建立假快取數據
        fake_cache_data = (
            "Fed 總資產：7,500,000 百萬美元（2026-03-28，較 2025-12-28 +5.50%）\n"
            "日銀總資產：750,000 百萬日圓（2026-03-28，較 2025-12-28 -2.30%）\n"
            "方向：偏向日圓升值\n"
            "解讀：聯準會近期擴表速度快於日銀，美元供給增加快於日圓，長期來看對日圓升值有利。"
        )
        save_text_cache(FRED_CB_CACHE, fake_cache_data)

    def tearDown(self):
        """測試後清理：刪除測試快取"""
        if Path(FRED_CB_CACHE).exists():
            Path(FRED_CB_CACHE).unlink()

    @patch("data_provider.requests.get")
    def test_fallback_used_on_timeout(self, mock_get):
        """
        測試流程：
        1. mock requests.get 拋 requests.exceptions.Timeout
        2. 呼叫 get_cb_balance_sheets()
        3. 確認回傳不是 None
        4. 確認回傳字串中包含 'fallback_used=True'
        """
        import requests
        # 設定 mock 拋出 Timeout 例外
        mock_get.side_effect = requests.exceptions.Timeout("Connection timeout")

        # 呼叫被測函式
        result = get_cb_balance_sheets()

        # 驗證結果不為 None
        assert result is not None, "get_cb_balance_sheets() should return cached data on timeout"

        # 驗證結果字串中包含 fallback_used=True 標記
        assert "fallback_used=True" in result, \
            f"Expected 'fallback_used=True' in result, got: {result}"

        print("✅ Test PASSED: Fallback mechanism works correctly")


if __name__ == "__main__":
    unittest.main(verbosity=2)
