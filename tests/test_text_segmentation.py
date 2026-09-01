from __future__ import annotations

import unittest

from app.text_segmentation import segment_for_avatar, split_complete_sentences


class TextSegmentationTests(unittest.TestCase):
    def test_keeps_user_example_together_at_default_limit(self):
        text = (
            "Python是一种高级、解释型的编程语言，以其简洁易读的语法著称。"
            "它广泛应用于Web开发、数据分析、人工智能等领域。"
            "作为初学者，掌握Python变量基础是第一步，让我们继续学习"
            "'变量与赋值'吧！"
        )

        self.assertEqual(segment_for_avatar(text), [text])
        self.assertLessEqual(len(text), 110)

    def test_splits_only_between_complete_sentences(self):
        first = "第一句话用于解释一个知识点。"
        second = "第二句话继续说明这个知识点。"
        third = "第三句话提出问题！"

        self.assertEqual(
            segment_for_avatar(first + second + third, max_chars=31),
            [first + second, third],
        )

    def test_keeps_one_overlong_sentence_intact(self):
        sentence = "这是" + "很长" * 30 + "的一句话。"
        self.assertEqual(segment_for_avatar(sentence, max_chars=20), [sentence])

    def test_overlong_sentence_falls_back_to_chinese_commas(self):
        first = "这是第一部分，"
        second = "这是第二部分，"
        third = "这是最后一部分。"

        self.assertEqual(
            segment_for_avatar(
                first + second + third,
                max_chars=len(first + second),
            ),
            [first + second, third],
        )

    def test_overlong_english_sentence_falls_back_to_commas(self):
        text = "First clause, second clause, final clause."
        first_segment = "First clause, second clause,"
        self.assertEqual(
            segment_for_avatar(text, max_chars=len(first_segment)),
            [first_segment, "final clause."],
        )

    def test_does_not_split_decimal_or_version_number(self):
        text = "Python 3.10 很常用。下一句开始。"
        self.assertEqual(
            split_complete_sentences(text),
            ["Python 3.10 很常用。", "下一句开始。"],
        )

    def test_includes_closing_quote_with_sentence(self):
        text = "老师说：“继续学习！”然后开始下一题。"
        self.assertEqual(
            split_complete_sentences(text),
            ["老师说：“继续学习！”", "然后开始下一题。"],
        )


if __name__ == "__main__":
    unittest.main()
