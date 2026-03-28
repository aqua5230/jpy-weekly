"""
單元測試 evaluate_jpy_direction()
針對邊界情境與 6 個關鍵場景
"""
import unittest
from decision_engine import evaluate_jpy_direction


class TestEvaluateJpyDirection(unittest.TestCase):
    """evaluate_jpy_direction() 邊界情境測試"""

    def test_case_1_p1_strong_rise_all_support(self):
        """
        測試 1: P1強升 + P2~P4全支持 
        → direction=升, confidence=高
        """
        p1 = {"direction": "升", "strength": "強"}
        p2 = {"direction": "升", "strength": "中"}
        p3 = {"direction": "升", "strength": "中"}
        p4 = {"direction": "升", "strength": "中"}

        result = evaluate_jpy_direction(p1, p2, p3, p4)
        
        self.assertEqual(result["direction"], "升")
        self.assertEqual(result["confidence"], "高")
        self.assertEqual(result["leader"], "P1")
        self.assertEqual(result["supporting"], ["P2", "P3", "P4"])
        self.assertEqual(result["opposing"], [])

    def test_case_2_p1_strong_rise_all_oppose(self):
        """
        測試 2: P1強升 + P2~P4全反對 
        → direction=升（P1主導），confidence=低
        """
        p1 = {"direction": "升", "strength": "強"}
        p2 = {"direction": "貶", "strength": "中"}
        p3 = {"direction": "貶", "strength": "中"}
        p4 = {"direction": "貶", "strength": "中"}

        result = evaluate_jpy_direction(p1, p2, p3, p4)
        
        self.assertEqual(result["direction"], "升")
        self.assertEqual(result["confidence"], "低")
        self.assertEqual(result["leader"], "P1")
        self.assertEqual(result["supporting"], [])
        self.assertEqual(result["opposing"], ["P2", "P3", "P4"])

    def test_case_3_p1_weak_rise_all_oppose(self):
        """
        測試 3: P1弱升 + P2~P4全反對 
        → direction=中性（唯一例外）
        """
        p1 = {"direction": "升", "strength": "弱"}
        p2 = {"direction": "貶", "strength": "中"}
        p3 = {"direction": "貶", "strength": "中"}
        p4 = {"direction": "貶", "strength": "中"}

        result = evaluate_jpy_direction(p1, p2, p3, p4)
        
        self.assertEqual(result["direction"], "中性")
        # 強反對時信心應該較低
        self.assertIn(result["confidence"], ["低", "中"])
        self.assertEqual(result["leader"], "P1")

    def test_case_4_p1_weak_rise_partial_support(self):
        """
        測試 4: P1弱升 + P2~P4部分支持 
        → direction=升, confidence視分數而定
        """
        p1 = {"direction": "升", "strength": "弱"}
        p2 = {"direction": "升", "strength": "中"}
        p3 = {"direction": "升", "strength": "中"}
        p4 = {"direction": "中性", "strength": "中"}

        result = evaluate_jpy_direction(p1, p2, p3, p4)
        
        self.assertEqual(result["direction"], "升")
        # 部分支持時信心應該為中或高
        self.assertIn(result["confidence"], ["中", "高"])
        self.assertEqual(result["supporting"], ["P2", "P3"])

    def test_case_5_p4_strong_oppose_penalty(self):
        """
        測試 5: P4強反對時（額外-1分）
        → confidence比沒有P4強反對時低
        
        P4強反對的總懲罰 = -2.0 (強度值) - 1.0 (額外懲罰) = -3.0 vs P4中等反對的 -1.0 = 差 2.0
        """
        # 無 P4 強反對的版本（只有中等反對）
        p1_without_penalty = {"direction": "升", "strength": "中"}
        p2_without = {"direction": "升", "strength": "弱"}
        p3_without = {"direction": "升", "strength": "弱"}
        p4_without = {"direction": "貶", "strength": "中"}  # 中等反對

        result_without = evaluate_jpy_direction(
            p1_without_penalty, p2_without, p3_without, p4_without
        )
        score_without = result_without["score"]

        # 有 P4 強反對的版本（應該額外扣 1 分 + 強度值 2）
        p1_with_penalty = {"direction": "升", "strength": "中"}
        p2_with = {"direction": "升", "strength": "弱"}
        p3_with = {"direction": "升", "strength": "弱"}
        p4_with = {"direction": "貶", "strength": "強"}  # 強反對 → 額外扣 1 + 強度扣 2

        result_with = evaluate_jpy_direction(
            p1_with_penalty, p2_with, p3_with, p4_with
        )
        score_with = result_with["score"]

        # P4 強反對時應該多扣 2 分（-2強度 + -1懲罰 vs -1中等反對）
        self.assertEqual(score_without - score_with, 2.0)
        # 信心應該相對低或相同
        confidence_map = {"高": 3, "中": 2, "低": 1}
        self.assertGreaterEqual(
            confidence_map[result_without["confidence"]],
            confidence_map[result_with["confidence"]]
        )

    def test_case_6_complex_score_calculation(self):
        """
        測試 6: P1中升 + P4中立 + P2反對P3支持
        → 測試 score 計算正確
        """
        p1 = {"direction": "升", "strength": "中"}
        p2 = {"direction": "貶", "strength": "弱"}
        p3 = {"direction": "升", "strength": "中"}
        p4 = {"direction": "中性", "strength": "弱"}

        result = evaluate_jpy_direction(p1, p2, p3, p4)

        # 手動計算預期 score：
        # P1 "中" → 1
        # P2 "弱" + "貶" (反對) → -0.5
        # P3 "中" + "升" (支持) → +1
        # P4 "中性" → 0
        # 無 P4 強反對額外懲罰
        # 總計: 1 - 0.5 + 1 = 1.5
        expected_score = 1.5

        self.assertEqual(result["direction"], "升")
        self.assertAlmostEqual(result["score"], expected_score, places=1)
        # score=1.5 應該落在 [0, 2) → confidence="中"
        self.assertEqual(result["confidence"], "中")
        self.assertEqual(result["supporting"], ["P3"])
        self.assertEqual(result["opposing"], ["P2"])


if __name__ == "__main__":
    unittest.main()
