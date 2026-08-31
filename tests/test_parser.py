# -*- coding: utf-8 -*-
"""parser 本地语法校验单元测试."""

from __future__ import annotations

import unittest

from nsat.errors import ParseError
from nsat.langs import detect_language
from nsat.parser import detect_references, validate


class TestHeader(unittest.TestCase):
    def test_header_present(self):
        f = validate("我想编译成 Python\n输出 [x]")
        self.assertEqual(f.header, "我想编译成 Python")

    def test_header_blank(self):
        f = validate("\n输出 [x]")
        self.assertEqual(f.header, "")

    def test_header_cannot_be_comment(self):
        with self.assertRaises(ParseError):
            validate("// 注释\n输出 [x]")

    def test_empty_file(self):
        with self.assertRaises(ParseError):
            validate("")


class TestIndent(unittest.TestCase):
    GOOD = "目标语言：Python\n循环 [i] 从 [1] 到 [3]：\n    输出 [i]\n输出 结束"

    def test_good(self):
        validate(self.GOOD)

    def test_missing_indent_after_colon(self):
        with self.assertRaises(ParseError) as ctx:
            validate("目标语言：Python\n循环 [i] 从 [1] 到 [3]：\n输出 [i]")
        self.assertIn("缩进", str(ctx.exception))

    def test_indent_without_colon(self):
        with self.assertRaises(ParseError):
            validate("目标语言：Python\n输出 [x]\n    输出 [y]")

    def test_tab_space_mixing(self):
        with self.assertRaises(ParseError):
            validate("目标语言：Python\n循环 [i] 从 [1] 到 [3]：\n\t输出 [i]\n    输出 [i]")

    def test_bad_indent_unit(self):
        with self.assertRaises(ParseError):
            validate("目标语言：Python\n循环 [i] 从 [1] 到 [3]：\n  输出 [i]")  # 3 空格

    def test_colon_at_eof(self):
        with self.assertRaises(ParseError):
            validate("目标语言：Python\n循环 [i] 从 [1] 到 [3]：")

    def test_fullwidth_colon(self):
        validate("我想写成 Python\n如果 [x] 大于 [0]：\n    输出 [x]")
        validate("我想写成 Python\n如果 [x] 大于 [0]:\n    输出 [x]")


class TestBrackets(unittest.TestCase):
    def test_unclosed(self):
        with self.assertRaises(ParseError):
            validate("我想编译成 Python\n输出 [x")

    def test_extra_close(self):
        with self.assertRaises(ParseError):
            validate("我想编译成 Python\n输出 x]")

    def test_nested(self):
        with self.assertRaises(ParseError):
            validate("我想编译成 Python\n输出 [[x]]")


class TestComment(unittest.TestCase):
    def test_comment_ignored(self):
        f = validate("我想编译成 Python\n输出 [x] // 这行尾注释")
        self.assertEqual(f.lines[1].code, "输出 [x]")

    def test_slash_slash_inside_bracket_not_comment(self):
        f = validate("我想编译成 Python\n输出 [https://example.com]")
        self.assertIn("[https://example.com]", f.lines[1].code)

    def test_full_line_comment(self):
        f = validate("我想编译成 Python\n// 整行注释\n输出 [x]")
        self.assertTrue(f.lines[1].is_blank or not f.lines[1].code)


class TestDetectReferences(unittest.TestCase):
    def test_refs(self):
        refs = detect_references("引用文件 [utils.nsat]\n输出 [x]")
        self.assertEqual(refs, ["utils.nsat"])

    def test_dup_dedup(self):
        refs = detect_references("引用 [a.nsat]\n引用 [a.nsat]\n引用 [b.nsat]")
        self.assertEqual(refs, ["a.nsat", "b.nsat"])


class TestDetectLanguage(unittest.TestCase):
    def test_python(self):
        self.assertEqual(detect_language("我想把这个文件编译成 Python"), "python")
        self.assertEqual(detect_language("target: python"), "python")
        self.assertEqual(detect_language("用 python3 写"), "python")

    def test_rust(self):
        self.assertEqual(detect_language("用 Rust 写"), "rust")

    def test_go(self):
        self.assertEqual(detect_language("目标语言：Go"), "go")

    def test_blank(self):
        self.assertIsNone(detect_language(""))

    def test_ambiguous(self):
        # Python 别名 py 与 ... 这种情况较少；此处验证不匹配
        self.assertIsNone(detect_language("随便写一个"))


if __name__ == "__main__":
    unittest.main()