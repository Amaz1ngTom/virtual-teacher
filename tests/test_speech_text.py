from __future__ import annotations

import unittest

from app.speech_text import prepare_speech_text


class SpeechTextTests(unittest.TestCase):
    def test_python_type_names_use_teaching_pronunciations(self):
        display = "type(x).__name__ 的结果是 str，而不是 int 或 bool。"

        self.assertEqual(
            prepare_speech_text(display),
            "type x 的类型名称 的结果是 string，而不是 integer 或 boolean。",
        )

    def test_identifiers_explain_underscores_without_changing_display_text(self):
        display = "user_name 合法，但 2name 和 __name__ 的含义不同。"

        self.assertEqual(
            prepare_speech_text(display),
            "user，下划线，name 合法，但 数字二开头的 name 和 "
            "双下划线 name 双下划线 的含义不同。",
        )

    def test_does_not_replace_str_inside_longer_identifier(self):
        display = "string_value 与 constraint 保持不变，str 单独转换。"

        self.assertEqual(
            prepare_speech_text(display),
            "string，下划线，value 与 constraint 保持不变，string 单独转换。",
        )


if __name__ == "__main__":
    unittest.main()
